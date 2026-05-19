"""
CO3²⁻ concentration calculator (Sharp & Byrne 2019).

This module is intentionally free of any hardware or I/O concerns.
It is a pure computation layer — testable with simple unit tests
and reusable regardless of the surrounding infrastructure.

Reference
---------
Sharp, J.D. & Byrne, R.H. (2019). Carbonate ion concentrations in seawater:
spectrophotometric determination, *Anal. Chim. Acta*, 1062, 45–56.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CO3ChemistryResult:
    """Intermediate and final outputs from the Sharp & Byrne calculation."""

    co3_umol_per_kg: float
    r_ratio: float          # (A2 - A3) / (A1 - A3)
    e1: float
    e3e2: float
    log_beta1_e2: float
    a1: float               # absorbance at λ1 (234 nm)
    a2: float               # absorbance at λ2 (250 nm)
    a3: float               # absorbance at λ3 (350 nm, reference)


@dataclass(frozen=True)
class AbsorbanceReadings:
    """Absorbance at the three CO3 measurement wavelengths."""

    a1: float   # 234 nm — main peak
    a2: float   # 250 nm — secondary peak
    a3: float   # 350 nm — reference baseline


class CO3Calculator:
    """
    Computes CO3²⁻ concentration from UV absorbance spectra.

    All methods are pure (no side-effects) and depend only on numpy.
    """

    def compute(
        self,
        absorbance: AbsorbanceReadings,
        temperature_c: float,
        salinity_corrected: float,
    ) -> CO3ChemistryResult:
        """
        Calculate [CO3²⁻] in µmol/kg using Sharp & Byrne (2019).

        Parameters
        ----------
        absorbance:
            Measured absorbance at the three wavelengths.
        temperature_c:
            In-cuvette temperature (°C).
        salinity_corrected:
            Salinity corrected for dye dilution (PSU).

        Returns
        -------
        CO3ChemistryResult
            All intermediate variables plus the final concentration.
        """
        s = salinity_corrected
        t = temperature_c

        e1 = (
            1.09519e-1
            + 4.49666e-3 * s
            + 1.95519e-3 * t
            + 2.44460e-5 * t ** 2
            - 2.01796e-5 * s * t
        )

        e3e2 = (
            32.4812e-1
            - 79.7676e-3 * s
            + 6.28521e-4 * s ** 2
            - 11.8691e-3 * t
            - 3.58709e-5 * t ** 2
            + 32.5849e-5 * s * t
        )

        log_beta1_e2 = (
            55.6674e-1
            - 51.0194e-3 * s
            + 4.61423e-4 * s ** 2
            - 13.6998e-5 * s * t
        )

        r = (absorbance.a2 - absorbance.a3) / (absorbance.a1 - absorbance.a3)

        denominator = 1.0 - r * e3e2
        if abs(denominator) < 1e-12:
            raise ValueError("Singular denominator in CO3 calculation (check absorbance values).")

        arg = (r - e1) / denominator

        if arg <= 0:
            raise ValueError(
                f"CO3 calculation failed: log argument is non-positive (arg={arg:.6f}). "
                "Check that the dye was injected and the absorbance readings are valid."
            )

        co3 = 1.0e6 * (10.0 ** -(log_beta1_e2 + math.log10(arg)))

        logger.debug(
            "CO3 calc: R=%.4f e1=%.4f e3e2=%.4f log_beta=%.4f arg=%.4f → %.2f µmol/kg",
            r, e1, e3e2, log_beta1_e2, arg, co3,
        )

        return CO3ChemistryResult(
            co3_umol_per_kg=co3,
            r_ratio=r,
            e1=e1,
            e3e2=e3e2,
            log_beta1_e2=log_beta1_e2,
            a1=absorbance.a1,
            a2=absorbance.a2,
            a3=absorbance.a3,
        )

    @staticmethod
    def compute_absorbance(
        post_injection: np.ndarray,
        blank: np.ndarray,
        dark: np.ndarray,
    ) -> np.ndarray:
        """
        Compute absorbance spectrum from raw intensity measurements.

            A = -log10( (I_sample - I_dark) / (I_blank - I_dark) )

        Parameters
        ----------
        post_injection:
            Intensity spectrum after dye injection.
        blank:
            Intensity spectrum of clean (dye-free) sample.
        dark:
            Intensity spectrum with shutter closed (background counts).
        """
        blank_minus_dark = blank - dark
        sample_minus_dark = post_injection - dark

        # Guard against division by zero or negative transmittance
        blank_minus_dark = np.where(blank_minus_dark <= 0, 1e-6, blank_minus_dark)
        ratio = sample_minus_dark / blank_minus_dark
        ratio = np.clip(ratio, 1e-6, None)

        return -np.log10(ratio)

    @staticmethod
    def find_pixel(wavelengths: np.ndarray, target_nm: float) -> int:
        """Return the pixel index whose wavelength is nearest to *target_nm*."""
        return int(np.abs(wavelengths - target_nm).argmin())

    @staticmethod
    def compute_dilution(
        cuvette_volume_ml: float,
        dye_volume_per_shot_ml: float,
        n_shots: int,
        injection_number: int,
    ) -> float:
        """
        Dilution factor after cumulative dye injections.

            dilution = V_cuvette / (V_cuvette + V_dye_total)

        *injection_number* is 1-based (first injection = 1).
        """
        vol_injected = dye_volume_per_shot_ml * n_shots * injection_number
        return cuvette_volume_ml / (cuvette_volume_ml + vol_injected)
