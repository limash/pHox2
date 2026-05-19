"""
pH measurement cycle.

Orchestrates hardware components and the pH calculator to produce a
pHMeasurementResult.  Follows the same 8-step sequence as CO3MeasurementCycle
with these key differences:

* Uses ILEDArray instead of ILightSource + IShutter
  (dark = LEDs off; blank = LEDs on, no dye)
* Runs n_cycles (default 4) injection cycles for multi-injection regression
* Calls pHCalculator.compute() per injection and pHCalculator.regress() at end

Dependency injection via component interfaces keeps this class testable and
replaceable without touching any hardware code.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from co3_instrument.components.interfaces import (
    IDrain,
    IDyePump,
    ILEDArray,
    IStirrer,
    ITemperatureSensor,
    IValve,
    IWaterPump,
)
from co3_instrument.hardware.interfaces import ISpectrometer
from co3_instrument.measurement.cycle import MeasurementConfig, SpectrometerAdjustConfig
from co3_instrument.measurement.models import (
    SpectralData,
    pHInjectionResult,
    pHMeasurementResult,
)
from co3_instrument.physics.ph_calculator import pHCalculator

logger = logging.getLogger(__name__)


@dataclass
class pHConfig:
    """pH-instrument-specific wavelength and dye configuration."""

    wavelength_1_nm: float   # acid-form peak (434 nm for MCP and TB)
    wavelength_2_nm: float   # base-form peak (578 nm MCP / 596 nm TB)
    nir_nm: float            # NIR reference (730 nm)
    dye: str                 # "MCP" or "TB"

    @classmethod
    def from_omegaconf(cls, cfg) -> "pHConfig":
        return cls(
            wavelength_1_nm=float(cfg.wavelength_1_nm),
            wavelength_2_nm=float(cfg.wavelength_2_nm),
            nir_nm=float(cfg.nir_nm),
            dye=str(cfg.dye),
        )


class pHMeasurementCycle:
    """
    Runs the full pH measurement sequence.

    Constructor parameters are all abstractions (IValve, IDyePump, …);
    no concrete classes are referenced here.
    """

    def __init__(
        self,
        spectrometer: ISpectrometer,
        valve: IValve,
        water_pump: IWaterPump,
        dye_pump: IDyePump,
        stirrer: IStirrer,
        led_array: ILEDArray,
        drain: IDrain,
        temp_sensor: ITemperatureSensor,
        calculator: pHCalculator,
        meas_cfg: MeasurementConfig,
        ph_cfg: pHConfig,
        light_threshold_counts: float,
        adj_cfg: SpectrometerAdjustConfig,
        integration_time_ms: float,
        ship_code: str = "UNKNOWN",
        t_ferrybox: float | None = None,
    ) -> None:
        self._spec = spectrometer
        self._valve = valve
        self._water_pump = water_pump
        self._dye_pump = dye_pump
        self._stirrer = stirrer
        self._leds = led_array
        self._drain = drain
        self._temp = temp_sensor
        self._calc = calculator
        self._mcfg = meas_cfg
        self._ph = ph_cfg
        self._threshold = light_threshold_counts
        self._adj = adj_cfg
        self._integration_time_ms = integration_time_ms
        self._ship_code = ship_code
        self._t_ferrybox = t_ferrybox

        # Resolved during initialise()
        self._wavelengths: np.ndarray | None = None
        self._px1: int | None = None   # pixel for λ1
        self._px2: int | None = None   # pixel for λ2
        self._px_nir: int | None = None  # pixel for NIR reference

    def initialise(self) -> None:
        """
        Resolve spectrometer wavelengths to pixel indices.

        Must be called once before the first measurement.
        """
        self._wavelengths = self._spec.get_wavelengths()
        self._px1 = pHCalculator.find_pixel(self._wavelengths, self._ph.wavelength_1_nm)
        self._px2 = pHCalculator.find_pixel(self._wavelengths, self._ph.wavelength_2_nm)
        self._px_nir = pHCalculator.find_pixel(self._wavelengths, self._ph.nir_nm)
        logger.info(
            "pH wavelength pixels: λ1=%.0f nm (px %d), λ2=%.0f nm (px %d), NIR=%.0f nm (px %d)",
            self._ph.wavelength_1_nm, self._px1,
            self._ph.wavelength_2_nm, self._px2,
            self._ph.nir_nm, self._px_nir,
        )

    # ── Public entry point ────────────────────────────────────────────────

    async def run(
        self,
        salinity: float,
        flush_before: bool = False,
    ) -> pHMeasurementResult:
        """
        Execute a complete pH measurement cycle.

        Parameters
        ----------
        salinity:
            In-situ salinity (PSU) used for dilution correction.
        flush_before:
            If True, run the water pump for pump_time_s before measuring.
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
        if self._adj.enabled:
            await self._auto_adjust_integration_time()

        self._spec.reset_measurement_state()

        # ── 3. Dark measurement (LEDs off) ───────────────────────────────
        logger.info("Step: dark measurement")
        self._leds.turn_off()
        await self._sleep(1.0)
        dark = await self._spec.get_intensities()
        await self._sleep(2.0)
        self._leds.turn_on()

        # ── 4. Blank measurement ─────────────────────────────────────────
        logger.info("Step: blank measurement")
        blank = await self._spec.get_intensities()

        # ── 5. Dye injection cycles ──────────────────────────────────────
        injections: list[pHInjectionResult] = []
        injection_spectra: dict[int, np.ndarray] = {}

        for n in range(self._mcfg.n_cycles):
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
        pH_cuvette, pH_insitu, r_square, slope = pHCalculator.regress(
            ph_values=[inj.pH for inj in injections],
            vol_injected_ml=[inj.vol_injected_ml for inj in injections],
            t_cuvette_values=[inj.t_cuvette for inj in injections],
            t_ferrybox=self._t_ferrybox,
        )

        last = injections[-1]
        spectral = SpectralData(
            wavelengths=self._wavelengths,
            dark=dark,
            blank=blank,
            injections=injection_spectra,
        )

        result = pHMeasurementResult(
            timestamp=timestamp,
            ship_code=self._ship_code,
            pH_cuvette=round(pH_cuvette, 4),
            pH_insitu=round(pH_insitu, 4),
            r_square=round(r_square, 4),
            slope=round(slope, 6),
            t_cuvette=last.t_cuvette,
            salinity_input=last.salinity_input,
            salinity_corrected=last.salinity_corrected,
            voltage=last.voltage,
            a1=last.a1,
            a2=last.a2,
            a_nir=last.a_nir,
            r_ratio=last.r_ratio,
            e1=last.e1,
            e2e3=last.e2e3,
            pK=last.pK,
            vol_injected_ml=last.vol_injected_ml,
            dye=self._ph.dye,
            injections=tuple(injections),
            spectra=spectral,
        )
        logger.info(result.summary())
        return result

    # ── Private helpers ───────────────────────────────────────────────────

    @property
    def _ta(self) -> float:
        """Time-acceleration divisor."""
        return max(1.0, self._mcfg.time_acceleration)

    async def _sleep(self, duration_s: float) -> None:
        await asyncio.sleep(duration_s / self._ta)

    async def _injection_cycle(
        self,
        n: int,
        salinity: float,
        dark: np.ndarray,
        blank: np.ndarray,
    ) -> tuple[pHInjectionResult, np.ndarray]:
        """Run one dye injection and return the pHInjectionResult + raw spectrum."""
        logger.info("pH injection cycle %d/%d", n + 1, self._mcfg.n_cycles)

        self._stirrer.start()
        await self._dye_pump.pulse(self._mcfg.dye_n_shots)
        await self._sleep(self._mcfg.mix_time_s)
        self._stirrer.stop()
        await self._sleep(self._mcfg.wait_time_s)

        voltage = self._temp.read_voltage()
        t_cuvette = self._temp.read_temperature()
        post_inj = await self._spec.get_intensities()

        abs_spectrum = pHCalculator.compute_absorbance(post_inj, blank, dark)
        a1 = round(float(abs_spectrum[self._px1]), 5)
        a2 = round(float(abs_spectrum[self._px2]), 5)
        a_nir = round(float(abs_spectrum[self._px_nir]), 5)

        vol_injected = (
            self._mcfg.dye_volume_per_shot_ml
            * self._mcfg.dye_n_shots
            * (n + 1)
        )
        dilution = pHCalculator.compute_dilution(
            self._mcfg.cuvette_volume_ml,
            self._mcfg.dye_volume_per_shot_ml,
            self._mcfg.dye_n_shots,
            n + 1,
        )
        s_corr = salinity * dilution

        chem = self._calc.compute(a1, a2, a_nir, t_cuvette, s_corr, self._ph.dye)

        result = pHInjectionResult(
            injection_index=n,
            vol_injected_ml=round(vol_injected, 3),
            dilution=round(dilution, 5),
            voltage=round(voltage, 5),
            t_cuvette=round(t_cuvette, 3),
            salinity_input=salinity,
            salinity_corrected=round(s_corr, 3),
            a1=a1,
            a2=a2,
            a_nir=a_nir,
            r_ratio=round(chem.r_ratio, 4),
            e1=round(chem.e1, 6),
            e2e3=round(chem.e2e3, 6),
            pK=round(chem.pK, 6),
            pH=round(chem.pH, 4),
            dye=self._ph.dye,
        )
        return result, post_inj

    async def _auto_adjust_integration_time(self) -> None:
        """Binary-search integration time to hit the target LED intensity."""
        target = self._threshold
        lo = target * (1.0 - self._adj.tolerance_fraction)
        hi = target * (1.0 + self._adj.tolerance_fraction)
        step = self._adj.step_ms
        direction: str | None = None

        logger.info("pH auto-adjusting integration time (target=%.0f counts)", target)

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
