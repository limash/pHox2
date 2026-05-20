"""
pH Instrument public API.

This class is the single entry point for any code that wants to interact with
the pH instrument.  It hides the internal component structure behind a clean,
stable contract.

Usage (async context manager ensures safe shutdown)::

    async with pHInstrumentAPI.from_config(cfg) as api:
        wavelengths = api.wavelengths
        result = await api.run_single_measurement(35.0)
        print(result.summary())
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Type

import numpy as np
from omegaconf import DictConfig

from phox2.communication.interfaces import IFerryboxClient
from phox2.communication.udp_client import NullFerryboxClient
from phox2.factory import InstrumentFactory
from phox2.measurement.models import pHMeasurementResult
from phox2.measurement.ph_cycle import pHMeasurementCycle

logger = logging.getLogger(__name__)


class pHInstrumentAPI:
    """
    Public API for the pH seawater spectrophotometric instrument.

    All GUI, CLI, or remote-control code should interact with the instrument
    exclusively through this class.

    Parameters
    ----------
    cycle:
        Fully wired pHMeasurementCycle (produced by InstrumentFactory).
    ferrybox_client:
        Ferrybox UDP client.  Pass ``NullFerryboxClient()`` (default) to
        disable Ferrybox communication.  Injected by ``from_config()``.
    """

    def __init__(self, cycle: pHMeasurementCycle, ferrybox_client: IFerryboxClient | None = None) -> None:
        self._cycle = cycle
        self._ferrybox: IFerryboxClient = ferrybox_client if ferrybox_client is not None else NullFerryboxClient()
        self._initialised = False
        self._wavelengths: np.ndarray | None = None

    # ── Factory constructor ───────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: DictConfig) -> "pHInstrumentAPI":
        """Build an API instance from a Hydra/OmegaConf config."""
        cycle = InstrumentFactory.build_ph_cycle(cfg)
        ferrybox_client = InstrumentFactory.build_ferrybox_client(cfg)
        return cls(cycle, ferrybox_client)

    # ── Context manager ───────────────────────────────────────────────────

    async def __aenter__(self) -> "pHInstrumentAPI":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        await self.disconnect()
        return False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Initialise hardware and resolve spectrometer pixel indices.

        Must be called before any measurement method.  Calling a second time
        is a no-op.
        """
        if self._initialised:
            return
        logger.info("Connecting to pH instrument…")
        self._cycle.initialise()
        self._wavelengths = self._cycle._wavelengths
        self._initialised = True
        await self._ferrybox.start()
        logger.info("pH instrument ready")

    async def disconnect(self) -> None:
        """Safely shut down hardware (turn off LEDs, open valve)."""
        logger.info("Disconnecting pH instrument…")
        try:
            await self._cycle._valve.open()
        except Exception:
            logger.warning("Could not open valve during disconnect", exc_info=True)
        try:
            self._cycle._leds.turn_off()
        except Exception:
            logger.warning("Could not turn off LEDs during disconnect", exc_info=True)
        await self._ferrybox.stop()
        logger.info("pH instrument disconnected")

    # ── Core measurement API ───────────────────────────────────────────────

    async def run_single_measurement(
        self,
        salinity: float,
        flush_before: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> pHMeasurementResult:
        """
        Run a complete pH measurement cycle.

        Parameters
        ----------
        salinity:
            In-situ salinity (PSU).  Used for dilution correction.
        flush_before:
            If True, run the water pump before measuring to flush stale
            sample out of the cuvette.
        on_step:
            Optional callback invoked at the start of each named cycle step
            (``"adjusting_light"``, ``"dark_blank"``, ``"injection_N"``).
            Use this to drive progress-tracker widgets in the GUI.

        Returns
        -------
        pHMeasurementResult
            Immutable dataclass with pH_cuvette, pH_insitu, regression stats,
            temperature, per-injection details, raw spectra, and the Ferrybox
            snapshot taken at measurement start.
        """
        self._require_connected()
        fb = self._ferrybox.get_latest_data()
        fb_temp = fb.temperature if fb is not None else None
        fb_sal = fb.salinity if fb is not None else None
        logger.info("Starting single pH measurement (S=%.3f)", salinity)
        result = await self._cycle.run(
            salinity=salinity,
            flush_before=flush_before,
            fb_temp=fb_temp,
            fb_sal=fb_sal,
            on_step=on_step,
        )
        await self._ferrybox.send_result(result)
        return result

    # ── Ferrybox data ─────────────────────────────────────────────────────

    def get_ferrybox_data(self):
        """
        Return the most recently received Ferrybox data packet, or ``None``.

        The caller may use this to obtain the current salinity before calling
        ``run_single_measurement()``.
        """
        return self._ferrybox.get_latest_data()

    # ── Status / introspection API ────────────────────────────────────────

    @property
    def wavelengths(self) -> np.ndarray:
        """Spectrometer wavelength array (nm), one element per pixel."""
        self._require_connected()
        return self._wavelengths.copy()  # type: ignore[union-attr]  # pyright: ignore[reportOptionalMemberAccess]

    async def get_spectrum(self) -> np.ndarray:
        """Capture a single spectrum from the spectrometer."""
        self._require_connected()
        return await self._cycle._spec.get_intensities()

    def get_temperature(self) -> float:
        """Return the current in-cuvette temperature (°C)."""
        self._require_connected()
        return self._cycle._temp.read_temperature()
    def get_voltage(self) -> float:
        """Return the current raw ADC voltage from the temperature probe."""
        self._require_connected()
        return self._cycle._temp.read_voltage()
    # ── LED manual controls ───────────────────────────────────────────────

    def turn_on_leds(self) -> None:
        """Apply configured duty cycles to all LED channels."""
        self._cycle._leds.turn_on()

    def turn_off_leds(self) -> None:
        """Set all LED channels to zero (dark state)."""
        self._cycle._leds.turn_off()

    def set_led_duty_cycle(self, channel: int, duty: int) -> None:
        """
        Set PWM duty cycle for *channel* (0-based; 0–100).

        Channels: 0 = Blue (434 nm), 1 = Orange (578/596 nm), 2 = Red (730 nm).
        """
        self._cycle._leds.set_duty_cycle(channel, duty)

    # ── Shared manual controls ────────────────────────────────────────────

    async def open_valve(self) -> None:
        """Open the inlet valve."""
        await self._cycle._valve.open()

    async def close_valve(self) -> None:
        """Close the inlet valve."""
        await self._cycle._valve.close()

    async def run_water_pump(self, duration_s: float) -> None:
        """Run the water pump for *duration_s* seconds."""
        await self._cycle._water_pump.run(duration_s)

    async def pulse_dye_pump(self, n_shots: int) -> None:
        """Fire the dye solenoid pump *n_shots* times."""
        await self._cycle._dye_pump.pulse(n_shots)

    def start_stirrer(self) -> None:
        """Energise the magnetic stirrer."""
        self._cycle._stirrer.start()

    def stop_stirrer(self) -> None:
        """De-energise the magnetic stirrer."""
        self._cycle._stirrer.stop()

    async def drain_cuvette(self, duration_s: float | None = None) -> None:
        """Drain the cuvette for *duration_s* seconds (defaults to config value)."""
        d = duration_s if duration_s is not None else self._cycle._mcfg.drain_time_s
        await self._cycle._drain.drain(d)
    async def auto_adjust_integration_time(self) -> None:
        """
        Run the LED auto-adjustment routine.

        Performs a binary search on integration time to bring the target
        pixel intensity within the configured tolerance band.
        """
        self._require_connected()
        await self._cycle._auto_adjust_integration_time()
    # ── Internal helpers ──────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._initialised:
            raise RuntimeError("Call connect() (or use async with) before using the API.")
