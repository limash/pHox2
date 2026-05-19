"""
Mock spectrometer.

Generates synthetic UV spectra designed to produce a physically realistic CO3
measurement result (~220 µmol/kg at S=35, T=20 °C).

Call-sequence awareness
-----------------------
The first call to ``get_intensities`` in a measurement cycle returns a *dark*
spectrum (shutter closed), the second returns a *blank* (no dye), and all
subsequent calls return a *sample* spectrum (with dye absorption).

Call ``reset_measurement_state()`` before each new measurement cycle so that
the ordering is reproduced correctly.
"""
from __future__ import annotations

import asyncio
import logging

import numpy as np

from phox2.hardware.interfaces import ISpectrometer

logger = logging.getLogger(__name__)


class MockSpectrometer(ISpectrometer):
    """
    Synthetic UV spectrometer for development and testing.

    Produces spectra engineered so that the CO3 calculation (Sharp & Byrne
    2019) yields ≈ 220 µmol/kg at S=35, T=20 °C.

    Absorbance values used:
      A1 (234 nm) = 0.300  →  R = (A2-A3)/(A1-A3) ≈ 0.428
      A2 (250 nm) = 0.134
      A3 (350 nm) = 0.010
    """

    _N_PIXELS = 2048
    _WVL_MIN_NM = 200.0
    _WVL_MAX_NM = 850.0

    _DARK_COUNTS: float = 200.0
    _DARK_NOISE: float = 10.0
    # Peak set to 61 000 so the CO3 UV pixels (234, 250 nm) fall inside the
    # default autoadjust window [57 000, 63 000] (threshold=60 000, ±5 %).
    _BLANK_PEAK_COUNTS: float = 61_000.0
    _BLANK_NOISE: float = 50.0

    # Dye absorbance at each measurement wavelength
    _A1 = 0.300   # 234 nm
    _A2 = 0.134   # 250 nm
    _A3 = 0.010   # 350 nm (reference)

    def __init__(self, cfg) -> None:
        self._wavelengths = np.linspace(
            self._WVL_MIN_NM, self._WVL_MAX_NM, self._N_PIXELS
        )
        self._integration_time_ms: float = float(cfg.integration_time_ms)
        self._call_count: int = 0
        self._rng = np.random.default_rng(seed=42)

    # ── ISpectrometer interface ────────────────────────────────────────────

    @property
    def sensor_type(self) -> str:
        return "FLMT"

    def get_wavelengths(self) -> np.ndarray:
        return self._wavelengths.copy()

    async def get_intensities(self, n_averages: int = 1) -> np.ndarray:
        await asyncio.sleep(0)  # yield to event loop
        return self._next_spectrum(n_averages)

    def get_intensities_sync(self, n_averages: int = 1) -> np.ndarray:
        return self._next_spectrum(n_averages)

    async def set_integration_time(self, time_ms: float) -> None:
        self._integration_time_ms = time_ms
        logger.debug("MOCK spectrometer integration time → %.1f ms", time_ms)
        await asyncio.sleep(0)

    def reset_measurement_state(self) -> None:
        """Reset call counter so the next call returns a dark spectrum."""
        self._call_count = 0
        logger.debug("MOCK spectrometer state reset")

    # ── Internal spectrum generation ───────────────────────────────────────

    def _next_spectrum(self, n_averages: int) -> np.ndarray:
        phase = self._call_count
        self._call_count += 1

        if phase == 0:
            gen = self._dark_spectrum
        elif phase == 1:
            gen = self._blank_spectrum
        else:
            gen = self._sample_spectrum

        spectra = np.stack([gen() for _ in range(max(1, n_averages))])
        return spectra.mean(axis=0)

    def _dark_spectrum(self) -> np.ndarray:
        noise = self._rng.normal(0.0, self._DARK_NOISE, self._N_PIXELS)
        return np.clip(self._DARK_COUNTS + noise, 0.0, None)

    def _blank_spectrum(self) -> np.ndarray:
        # Deuterium lamp: peak centred near 240 nm so UV measurement pixels
        # (234, 250 nm) land inside the autoadjust acceptance window.
        profile = self._BLANK_PEAK_COUNTS * np.exp(
            -((self._wavelengths - 240.0) / 200.0) ** 2
        )
        profile = np.clip(profile, 5_000.0, self._BLANK_PEAK_COUNTS)
        noise = self._rng.normal(0.0, self._BLANK_NOISE, self._N_PIXELS)
        return profile + noise

    def _sample_spectrum(self) -> np.ndarray:
        blank = self._blank_spectrum()
        dark_val = self._DARK_COUNTS
        blank_minus_dark = blank - dark_val

        # Apply narrow Gaussian absorption bands at each wavelength
        absorption = np.ones(self._N_PIXELS)
        for wl_nm, absorbance in [
            (234.0, self._A1),
            (250.0, self._A2),
            (350.0, self._A3),
        ]:
            transmittance = 10.0 ** (-absorbance)
            # σ ≈ 2.1 nm  (FWHM ≈ 5 nm, realistic for a sharp UV band)
            gaussian = np.exp(-((self._wavelengths - wl_nm) / 2.1) ** 2)
            absorption -= (1.0 - transmittance) * gaussian

        sample_minus_dark = blank_minus_dark * np.clip(absorption, 0.0, 1.0)
        noise = self._rng.normal(0.0, self._BLANK_NOISE * 0.5, self._N_PIXELS)
        return sample_minus_dark + dark_val + noise
