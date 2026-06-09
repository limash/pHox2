"""
CO3 Instrument public API.

This class is the single entry point for any code that wants to interact with
the CO3 instrument.  It hides the internal component structure behind a clean,
stable contract.

A future GUI module will import this class and nothing else from this package::

    from phox2.co3_api import CO3InstrumentAPI, InstrumentFactory

Usage (async context manager ensures safe shutdown)::

    async with CO3InstrumentAPI.from_config(cfg) as api:
        wavelengths = api.wavelengths                     # property
        result = await api.run_single_measurement(35.0)   # main measurement
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
from phox2.measurement.co3_cycle import CO3MeasurementCycle
from phox2.measurement.models import CO3MeasurementResult

logger = logging.getLogger(__name__)


class CO3InstrumentAPI:
    """
    Public API for the CO3 seawater carbonate instrument.

    All GUI, CLI, or remote-control code should interact with the instrument
    exclusively through this class.

    Parameters
    ----------
    cycle:
        Fully wired CO3MeasurementCycle (produced by InstrumentFactory).
    ferrybox_client:
        Ferrybox UDP client.  Pass ``NullFerryboxClient()`` (default) to
        disable Ferrybox communication.  Injected by ``from_config()``.
    """

    def __init__(self, cycle: CO3MeasurementCycle, ferrybox_client: IFerryboxClient | None = None) -> None:
        self._cycle = cycle
        self._ferrybox: IFerryboxClient = ferrybox_client if ferrybox_client is not None else NullFerryboxClient()
        self._initialised = False
        self._wavelengths: np.ndarray | None = None

    # ── Factory constructor ───────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: DictConfig) -> "CO3InstrumentAPI":
        """Build an API instance from a Hydra/OmegaConf config."""
        cycle = InstrumentFactory.build_cycle(cfg)
        ferrybox_client = InstrumentFactory.build_ferrybox_client(cfg)
        return cls(cycle, ferrybox_client)

    # ── Context manager (safe resource management) ────────────────────────

    async def __aenter__(self) -> "CO3InstrumentAPI":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        await self.disconnect()
        return False  # do not suppress exceptions

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Initialise hardware and resolve spectrometer pixel indices.

        Must be called before any measurement method.
        Calling a second time is a no-op.
        """
        if self._initialised:
            return
        logger.info("Connecting to CO3 instrument…")
        self._cycle.initialise()
        self._wavelengths = self._cycle._wavelengths
        self._initialised = True
        await self._ferrybox.start()
        logger.info("CO3 instrument ready")

    async def disconnect(self) -> None:
        """Safely shut down hardware (turn off light, open valve)."""
        logger.info("Disconnecting CO3 instrument…")
        # Best-effort safe state: open valve so sample flows freely
        try:
            await self._cycle._valve.open()
        except Exception:
            logger.warning("Could not open valve during disconnect", exc_info=True)
        try:
            self._cycle._light.turn_off()
            self._cycle._shutter.close()
        except Exception:
            logger.warning("Could not turn off light during disconnect", exc_info=True)
        await self._ferrybox.stop()
        logger.info("CO3 instrument disconnected")

    # ── Core measurement API ───────────────────────────────────────────────

    async def run_single_measurement(
        self,
        salinity: float,
        flush_before: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> CO3MeasurementResult:
        """
        Run a complete CO3 measurement cycle.

        Parameters
        ----------
        salinity:
            In-situ salinity (PSU).  Used for dilution correction.
            Typically from a Ferrybox or manual entry.
        flush_before:
            If True, run the water pump before measuring to flush stale
            sample out of the cuvette.
        on_step:
            Optional callback invoked at the start of each named cycle step
            (``"adjusting_light"``, ``"dark_blank"``, ``"measurement_N"``).
            Use this to drive progress-tracker widgets in the GUI.

        Returns
        -------
        MeasurementResult
            Immutable dataclass containing concentration, temperature,
            absorbance values, intermediate chemistry, raw spectra, and
            the Ferrybox snapshot taken at measurement start.
        """
        self._require_connected()
        fb = self._ferrybox.get_latest_data()
        fb_temp = fb.temperature if fb is not None else None
        fb_sal = fb.salinity if fb is not None else None
        logger.info("Starting single CO3 measurement (S=%.3f)", salinity)
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
        """
        Capture a single spectrum from the spectrometer.

        Useful for live display or light-source alignment checks.
        """
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
    # ── Manual control API (for GUI manual-control panel) ─────────────────

    async def open_valve(self) -> None:
        """Open the inlet valve."""
        await self._cycle._valve.open()

    async def close_valve(self) -> None:
        """Close the inlet valve."""
        await self._cycle._valve.close()

    def turn_on_light(self) -> None:
        """Switch the UV lamp on."""
        self._cycle._light.turn_on()

    def turn_off_light(self) -> None:
        """Switch the UV lamp off."""
        self._cycle._light.turn_off()

    def open_shutter(self) -> None:
        """Open the optical shutter."""
        self._cycle._shutter.open()

    def close_shutter(self) -> None:
        """Close the optical shutter."""
        self._cycle._shutter.close()

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
        """
        Drain the cuvette.

        Parameters
        ----------
        duration_s:
            Override drain duration.  Defaults to the config value.
        """
        d = duration_s if duration_s is not None else self._cycle._mcfg.drain_time_s
        await self._cycle._drain.drain(d)

    async def auto_adjust_integration_time(self) -> None:
        """
        Run the spectrometer auto-adjustment routine.

        Performs a binary search on integration time to bring the target
        pixel intensity within the configured tolerance band.
        """
        self._require_connected()
        await self._cycle._auto_adjust_integration_time()

    async def set_integration_time(self, time_ms: float) -> None:
        """Set the spectrometer integration time immediately (milliseconds)."""
        self._require_connected()
        self._cycle._integration_time_ms = time_ms
        await self._cycle._spec.set_integration_time(time_ms)

    # ── Private ───────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._initialised:
            raise RuntimeError(
                "CO3InstrumentAPI is not connected. "
                "Call await api.connect() or use it as an async context manager."
            )
