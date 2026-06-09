"""
CO3 measurement cycle.

Orchestrates hardware components and the CO3 calculator to produce a
MeasurementResult.  This class owns the *sequence* of operations; it has
no knowledge of files, UDP, or the GUI.

Dependency injection via component interfaces keeps this class testable
and replaceable without touching any hardware code.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from phox2.components.interfaces import (
    IDrain,
    IDyePump,
    ILightSource,
    IShutter,
    IStirrer,
    ITemperatureSensor,
    IValve,
    IWaterPump,
)
from phox2.hardware.interfaces import ISpectrometer
from phox2.measurement.models import (
    CO3InjectionResult,
    CO3MeasurementResult,
    SpectralData,
)
from phox2.physics.co3_calculator import (
    AbsorbanceReadings,
    CO3Calculator,
)

logger = logging.getLogger(__name__)


@dataclass
class MeasurementConfig:
    cuvette_volume_ml: float
    dye_volume_per_shot_ml: float
    dye_n_shots: int
    n_cycles: int
    mix_time_s: float
    wait_time_s: float
    pump_time_s: float
    drain_after: bool
    drain_time_s: float
    time_acceleration: float = 1.0

    @classmethod
    def from_omegaconf(cls, cfg) -> "MeasurementConfig":
        return cls(
            cuvette_volume_ml=float(cfg.cuvette_volume_ml),
            dye_volume_per_shot_ml=float(cfg.dye_volume_per_shot_ml),
            dye_n_shots=int(cfg.dye_n_shots),
            n_cycles=int(cfg.n_cycles),
            mix_time_s=float(cfg.mix_time_s),
            wait_time_s=float(cfg.wait_time_s),
            pump_time_s=float(cfg.pump_time_s),
            drain_after=bool(cfg.drain_after),
            drain_time_s=float(cfg.drain_time_s),
            time_acceleration=float(cfg.time_acceleration),
        )


@dataclass
class CO3Config:
    wavelength_1_nm: float
    wavelength_2_nm: float
    wavelength_3_nm: float
    dye: str

    @classmethod
    def from_omegaconf(cls, cfg) -> "CO3Config":
        return cls(
            wavelength_1_nm=float(cfg.wavelength_1_nm),
            wavelength_2_nm=float(cfg.wavelength_2_nm),
            wavelength_3_nm=float(cfg.wavelength_3_nm),
            dye=str(cfg.dye),
        )


@dataclass
class SpectrometerAdjustConfig:
    mode: str  # "ON" | "OFF" | "ON_NORED"
    tolerance_fraction: float
    max_iterations: int
    step_ms: float

    @classmethod
    def from_omegaconf(cls, cfg) -> "SpectrometerAdjustConfig":
        return cls(
            mode=str(cfg.mode),
            tolerance_fraction=float(cfg.tolerance_fraction),
            max_iterations=int(cfg.max_iterations),
            step_ms=float(cfg.step_ms),
        )


class CO3MeasurementCycle:
    """
    Runs the full CO3 measurement sequence.

    Constructor parameters are all abstractions (IValve, IDyePump, …);
    no concrete classes are referenced here — Open/Closed + Dependency
    Inversion principles in action.
    """

    def __init__(
        self,
        spectrometer: ISpectrometer,
        valve: IValve,
        water_pump: IWaterPump,
        dye_pump: IDyePump,
        stirrer: IStirrer,
        light_source: ILightSource,
        shutter: IShutter,
        drain: IDrain,
        temp_sensor: ITemperatureSensor,
        calculator: CO3Calculator,
        meas_cfg: MeasurementConfig,
        co3_cfg: CO3Config,
        light_threshold_counts: float,
        adj_cfg: SpectrometerAdjustConfig,
        integration_time_ms: float,
        ship_code: str = "UNKNOWN",
    ) -> None:
        self._spec = spectrometer
        self._valve = valve
        self._water_pump = water_pump
        self._dye_pump = dye_pump
        self._stirrer = stirrer
        self._light = light_source
        self._shutter = shutter
        self._drain = drain
        self._temp = temp_sensor
        self._calc = calculator
        self._mcfg = meas_cfg
        self._co3 = co3_cfg
        self._threshold = light_threshold_counts
        self._adj = adj_cfg
        self._integration_time_ms = integration_time_ms
        self._ship_code = ship_code

        # Resolved during initialise()
        self._wavelengths: np.ndarray | None = None
        self._px1: int | None = None   # pixel for λ1
        self._px2: int | None = None   # pixel for λ2
        self._px3: int | None = None   # pixel for λ3

    def initialise(self) -> None:
        """
        Resolve spectrometer wavelengths to pixel indices.

        Must be called once before the first measurement.
        """
        self._wavelengths = self._spec.get_wavelengths()
        self._px1 = CO3Calculator.find_pixel(self._wavelengths, self._co3.wavelength_1_nm)
        self._px2 = CO3Calculator.find_pixel(self._wavelengths, self._co3.wavelength_2_nm)
        self._px3 = CO3Calculator.find_pixel(self._wavelengths, self._co3.wavelength_3_nm)
        logger.info(
            "Wavelength pixels: λ1=%.0f nm (px %d), λ2=%.0f nm (px %d), λ3=%.0f nm (px %d)",
            self._co3.wavelength_1_nm, self._px1,
            self._co3.wavelength_2_nm, self._px2,
            self._co3.wavelength_3_nm, self._px3,
        )

    # ── Public entry point ────────────────────────────────────────────────

    async def run(
        self,
        salinity: float,
        flush_before: bool = False,
        fb_temp: float | None = None,
        fb_sal: float | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> CO3MeasurementResult:
        """
        Execute a complete CO3 measurement cycle.

        Parameters
        ----------
        salinity:
            In-situ salinity (PSU) used for dilution correction.
        flush_before:
            If True, run the water pump for pump_time_s before measuring
            to flush the sample chamber.
        fb_temp:
            Ferrybox sea-surface temperature (°C) at measurement start, or None.
        fb_sal:
            Ferrybox salinity (PSU) at measurement start, or None.
        on_step:
            Optional callback invoked at the start of each named step.  The
            string argument matches the GUI progress-tracker labels:
            ``"adjusting_light"``, ``"dark_blank"``, ``"measurement_N"``
            (N is 1-based).
        """
        if self._wavelengths is None:
            raise RuntimeError("Call initialise() before run().")

        self._spec.reset_measurement_state()
        timestamp = datetime.now()

        # ── 0. Optional flush ────────────────────────────────────────────
        if flush_before:
            logger.info("Flushing sample chamber")
            await self._water_pump.run(self._mcfg.pump_time_s / self._ta)

        # ── 1. Close valve ───────────────────────────────────────────────
        await self._valve.close()

        # ── 2. Auto-adjust integration time ─────────────────────────────
        if self._adj.mode != "OFF":
            if on_step:
                on_step("adjusting_light")
            await self._auto_adjust_integration_time()

        # Reset spectrometer call-sequence state AFTER autoadjust so that the
        # next call is treated as the start of dark → blank → sample ordering.
        self._spec.reset_measurement_state()

        # ── 3. Dark measurement ──────────────────────────────────────────
        logger.info("Step: dark measurement")
        if on_step:
            on_step("dark_blank")
        self._shutter.close()
        await self._sleep(1.0)
        dark = await self._spec.get_intensities()
        await self._sleep(2.0)
        self._shutter.open()

        # ── 4. Blank measurement ─────────────────────────────────────────
        logger.info("Step: blank measurement")
        blank = await self._spec.get_intensities()

        # ── 5. Dye injection cycles ──────────────────────────────────────
        injections: list[CO3InjectionResult] = []
        injection_spectra: dict[int, np.ndarray] = {}

        for n in range(self._mcfg.n_cycles):
            if on_step:
                on_step(f"measurement_{n + 1}")
            inj_result, post_inj_sp = await self._injection_cycle(
                n=n,
                salinity=salinity,
                dark=dark,
                blank=blank,
            )
            injections.append(inj_result)
            injection_spectra[n] = post_inj_sp

        # ── 6. Drain ─────────────────────────────────────────────────────
        if self._mcfg.drain_after:
            await self._drain.drain(self._mcfg.drain_time_s / self._ta)

        # ── 7. Open valve ─────────────────────────────────────────────────
        await self._valve.open()

        # ── 8. Build result ───────────────────────────────────────────────
        # With n_cycles=1 (typical for CO3) take the single result directly.
        # Multiple cycles: take the mean CO3 (could be extended to regression).
        primary = injections[0] if len(injections) == 1 else self._mean_result(injections)

        spectral = SpectralData(
            wavelengths=self._wavelengths,
            dark=dark,
            blank=blank,
            injections=injection_spectra,
        )

        result = CO3MeasurementResult(
            timestamp=timestamp,
            ship_code=self._ship_code,
            co3_umol_per_kg=primary.co3_umol_per_kg,
            t_cuvette=primary.t_cuvette,
            salinity_input=primary.salinity_input,
            salinity_corrected=primary.salinity_corrected,
            voltage=primary.voltage,
            a1=primary.a1,
            a2=primary.a2,
            a3=primary.a3,
            r_ratio=primary.r_ratio,
            e1=primary.e1,
            e3e2=primary.e3e2,
            log_beta1_e2=primary.log_beta1_e2,
            vol_injected_ml=primary.vol_injected_ml,
            dye=self._co3.dye,
            injections=tuple(injections),
            spectra=spectral,
            fb_temp=fb_temp,
            fb_sal=fb_sal,
        )
        logger.info(result.summary())
        return result

    # ── Private helpers ───────────────────────────────────────────────────

    @property
    def _ta(self) -> float:
        """Time-acceleration divisor (1 = real time)."""
        return max(1.0, self._mcfg.time_acceleration)

    async def _sleep(self, duration_s: float) -> None:
        await asyncio.sleep(duration_s / self._ta)

    async def _injection_cycle(
        self,
        n: int,
        salinity: float,
        dark: np.ndarray,
        blank: np.ndarray,
    ) -> tuple[CO3InjectionResult, np.ndarray]:
        """Run one dye injection and return the InjectionResult + raw spectrum."""
        logger.info("Injection cycle %d/%d", n + 1, self._mcfg.n_cycles)

        # Stir + inject
        self._stirrer.start()
        await self._dye_pump.pulse(self._mcfg.dye_n_shots)
        await self._sleep(self._mcfg.mix_time_s)
        self._stirrer.stop()
        await self._sleep(self._mcfg.wait_time_s)

        # Temperature at time of measurement
        voltage = self._temp.read_voltage()
        t_cuvette = self._temp.read_temperature()

        # Spectrum after dye
        post_inj = await self._spec.get_intensities()

        # Absorbance
        abs_spectrum = CO3Calculator.compute_absorbance(post_inj, blank, dark)
        abs_at_px = AbsorbanceReadings(
            a1=round(float(abs_spectrum[self._px1]), 5),
            a2=round(float(abs_spectrum[self._px2]), 5),
            a3=round(float(abs_spectrum[self._px3]), 5),
        )

        # Dilution + chemistry
        vol_injected = (
            self._mcfg.dye_volume_per_shot_ml
            * self._mcfg.dye_n_shots
            * (n + 1)
        )
        dilution = CO3Calculator.compute_dilution(
            self._mcfg.cuvette_volume_ml,
            self._mcfg.dye_volume_per_shot_ml,
            self._mcfg.dye_n_shots,
            n + 1,
        )
        s_corr = salinity * dilution

        chemistry = self._calc.compute(abs_at_px, t_cuvette, s_corr)

        result = CO3InjectionResult(
            injection_index=n,
            vol_injected_ml=round(vol_injected, 3),
            dilution=round(dilution, 5),
            voltage=round(voltage, 5),
            t_cuvette=round(t_cuvette, 3),
            salinity_input=salinity,
            salinity_corrected=round(s_corr, 3),
            a1=abs_at_px.a1,
            a2=abs_at_px.a2,
            a3=abs_at_px.a3,
            r_ratio=round(chemistry.r_ratio, 4),
            e1=round(chemistry.e1, 6),
            e3e2=round(chemistry.e3e2, 6),
            log_beta1_e2=round(chemistry.log_beta1_e2, 6),
            co3_umol_per_kg=round(chemistry.co3_umol_per_kg, 2),
        )
        return result, post_inj

    async def _auto_adjust_integration_time(self) -> None:
        """Binary-search integration time to hit the target intensity."""
        target = self._threshold
        lo = target * (1.0 - self._adj.tolerance_fraction)
        hi = target * (1.0 + self._adj.tolerance_fraction)
        step = self._adj.step_ms
        direction: str | None = None

        logger.info("Auto-adjusting integration time (target=%.0f counts)", target)

        for _ in range(self._adj.max_iterations):
            await self._spec.set_integration_time(self._integration_time_ms)
            await self._sleep(0.5)
            spectrum = await self._spec.get_intensities()
            level = max(spectrum[self._px1], spectrum[self._px2])

            if lo <= level <= hi:
                logger.info("Integration time adjusted to %.1f ms", self._integration_time_ms)
                return

            if level < lo:
                if direction == "decrease":
                    step /= 2
                direction = "increase"
                self._integration_time_ms += step
            else:
                if direction == "increase":
                    step /= 2
                direction = "decrease"
                self._integration_time_ms = max(1.0, self._integration_time_ms - step)

            if self._integration_time_ms > 5_000:
                logger.warning("Integration time ceiling reached (5000 ms)")
                break

        logger.warning("Auto-adjust did not converge; using %.1f ms", self._integration_time_ms)

    @staticmethod
    def _mean_result(injections: list[CO3InjectionResult]) -> CO3InjectionResult:
        """Return the first injection (extend to mean/regression if n_cycles > 1)."""
        return injections[0]
