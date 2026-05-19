"""
Real spectrometer driver using the seabreeze library.

Install:
    pip install seabreeze
    seabreeze_os_setup   # installs udev rules
"""
from __future__ import annotations

import asyncio
import logging
import re

import numpy as np

from phox2.hardware.interfaces import ISpectrometer

logger = logging.getLogger(__name__)


class SeabreezeSpectrometer(ISpectrometer):
    """Spectrometer driver backed by the ``seabreeze`` / ``pyseabreeze`` library."""

    def __init__(self, spec_cfg) -> None:
        try:
            import seabreeze  # type: ignore
            seabreeze.use("pyseabreeze")
            from seabreeze.spectrometers import Spectrometer  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "seabreeze is required for real hardware mode. "
                "Install it with: pip install seabreeze"
            ) from exc

        self._spec = Spectrometer.from_first_available()
        self._busy = False
        self._integration_time_ms: float = float(spec_cfg.integration_time_ms)
        self._spec.integration_time_micros(int(self._integration_time_ms * 1_000))

        # Detect model from string representation
        spec_str = str(self._spec)
        self._sensor_type = "FLMT"
        for code in ("STS", "FLMT"):
            if re.search(code, spec_str):
                self._sensor_type = code
                break
        logger.info("Seabreeze spectrometer '%s' (type=%s)", self._spec, self._sensor_type)

    @property
    def sensor_type(self) -> str:
        return self._sensor_type

    def get_wavelengths(self) -> np.ndarray:
        return self._spec.wavelengths()

    async def get_intensities(self, n_averages: int = 1) -> np.ndarray:
        while self._busy:
            await asyncio.sleep(0.05)
        self._busy = True
        try:
            sp = await asyncio.get_running_loop().run_in_executor(
                None, self._read_averaged, n_averages
            )
        finally:
            self._busy = False
        return sp

    def get_intensities_sync(self, n_averages: int = 1) -> np.ndarray:
        return self._read_averaged(n_averages)

    async def set_integration_time(self, time_ms: float) -> None:
        while self._busy:
            await asyncio.sleep(0.05)
        self._busy = True
        try:
            self._spec.integration_time_micros(int(time_ms * 1_000))
            self._integration_time_ms = time_ms
        finally:
            self._busy = False
        logger.debug("Integration time set to %.1f ms", time_ms)

    def reset_measurement_state(self) -> None:
        """No-op for real hardware."""

    def close(self) -> None:
        self._spec.close()
        logger.info("Spectrometer closed")

    # ── private ──────────────────────────────────────────────────────────────

    def _read_averaged(self, n_averages: int) -> np.ndarray:
        if n_averages < 2:
            return self._spec.intensities()
        readings = np.stack([self._spec.intensities() for _ in range(n_averages)])
        return readings.mean(axis=0)
