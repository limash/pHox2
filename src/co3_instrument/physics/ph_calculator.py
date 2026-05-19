"""
pH calculator (Clayton & Byrne 1993; Liu et al. 2011; TB equations).

Pure computation layer — no hardware or I/O concerns.

Supported dyes
--------------
* ``"MCP"`` — m-Cresol Purple (Clayton & Byrne 1993 + Liu et al. 2011 update).
  Wavelengths: 434 nm (A1), 578 nm (A2), 730 nm (NIR reference).
* ``"TB"``  — Thymol Blue.
  Wavelengths: 434 nm (A1), 596 nm (A2), 730 nm (NIR reference).

References
----------
Clayton, T.D. & Byrne, R.H. (1993). Spectrophotometric seawater pH
measurements: total hydrogen ion concentration scale calibration of
m-cresol purple and at-sea results. *Deep-Sea Res.*, 40, 2115–2129.

Liu, X. et al. (2011). Spectrophotometric measurements of pH in-situ:
laboratory and field evaluations of instrumental performance. *Environ.
Sci. Technol.*, 45, 4862–4868.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_DPH_DT = -0.0155  # pH drift per °C (temperature correction slope)

_SUPPORTED_DYES = ("MCP", "TB")


@dataclass(frozen=True)
class pHChemistryResult:
    """Per-injection pH chemistry result."""

    pH: float           # calculated pH (total scale)
    pK: float           # pK at measurement T and S
    e1: float           # indicator constant e1
    e2e3: float         # indicator constant e2/e3 (MCP) or ratio (TB)
    a1: float           # absorbance at λ1
    a2: float           # absorbance at λ2
    a_nir: float        # absorbance at NIR reference wavelength
    r_ratio: float      # A2 / A1


class pHCalculator:
    """
    Computes seawater pH from visible absorbance spectra.

    All public methods are pure (no side-effects).
    """

    def compute(
        self,
        a1: float,
        a2: float,
        a_nir: float,
        t_cuvette: float,
        s_corr: float,
        dye: str,
    ) -> pHChemistryResult:
        """
        Calculate pH from per-injection absorbance values.

        Parameters
        ----------
        a1:
            Absorbance at the acid-form peak wavelength (434 nm for both dyes).
        a2:
            Absorbance at the base-form peak wavelength (578 nm MCP / 596 nm TB).
        a_nir:
            Absorbance at the NIR reference (730 nm) — subtracted to remove
            baseline drift.
        t_cuvette:
            In-cuvette temperature (°C).
        s_corr:
            Salinity corrected for dye dilution (PSU).
        dye:
            Dye identifier: ``"MCP"`` or ``"TB"``.

        Returns
        -------
        pHChemistryResult
        """
        if dye not in _SUPPORTED_DYES:
            raise ValueError(f"Unsupported dye '{dye}'. Choose from {_SUPPORTED_DYES}.")

        r = a2 / a1 if a1 != 0.0 else 0.0

        if dye == "MCP":
            return self._compute_mcp(a1, a2, a_nir, r, t_cuvette, s_corr)
        else:
            return self._compute_tb(a1, a2, a_nir, r, t_cuvette, s_corr)

    # ── Dye-specific kernels ──────────────────────────────────────────────

    @staticmethod
    def _compute_mcp(
        a1: float,
        a2: float,
        a_nir: float,
        r: float,
        t_cuvette: float,
        s_corr: float,
    ) -> pHChemistryResult:
        """MCP: Clayton & Byrne (1993) + Liu et al. (2011) correction."""
        t_k = 273.15 + t_cuvette

        e1 = -0.007762 + 4.5174e-5 * t_k
        e2e3 = -0.020813 + 2.60262e-4 * t_k + 1.0436e-4 * (s_corr - 35.0)

        pK = (
            5.561224
            - 0.547716 * s_corr ** 0.5
            + 0.123791 * s_corr
            - 0.0280156 * s_corr ** 1.5
            + 0.00344940 * s_corr ** 2
            - 0.000167297 * s_corr ** 2.5
            + (52.640726 * s_corr ** 0.5) / t_k
            + 815.984591 / t_k
        )

        arg = (r - e1) / (1.0 - r * e2e3)

        if arg <= 0.0:
            logger.warning("MCP pH: log argument non-positive (arg=%.6f); returning 99.9999", arg)
            pH = 99.9999
        else:
            pH = pK + math.log10(arg)

        logger.debug("MCP pH: R=%.4f e1=%.4f e2e3=%.4f pK=%.4f → pH=%.4f", r, e1, e2e3, pK, pH)
        return pHChemistryResult(pH=pH, pK=pK, e1=e1, e2e3=e2e3, a1=a1, a2=a2, a_nir=a_nir, r_ratio=r)

    @staticmethod
    def _compute_tb(
        a1: float,
        a2: float,
        a_nir: float,
        r: float,
        t_cuvette: float,
        s_corr: float,
    ) -> pHChemistryResult:
        """TB: Thymol Blue equations."""
        t_k = 273.15 + t_cuvette

        e1 = -0.00132 + 1.6e-5 * t_k
        e2 = 7.2326 - 0.0299717 * t_k + 4.6e-5 * (t_k ** 2)
        e3 = 0.0223 + 0.0003917 * t_k

        pK = 4.706 * (s_corr / t_k) + 26.3300 - 7.17218 * math.log(t_k) - 0.017316 * s_corr

        arg = (r - e1) / (e2 - r * e3)

        if arg <= 0.0:
            logger.warning("TB pH: log argument non-positive (arg=%.6f); returning 99.9999", arg)
            pH = 99.9999
        else:
            pH = 0.0047 + pK + math.log10(arg)

        # Store e2/e3 combined as e2e3 for log-file compatibility
        e2e3 = e2 / e3 if e3 != 0.0 else 0.0

        logger.debug("TB pH: R=%.4f e1=%.4f pK=%.4f → pH=%.4f", r, e1, pK, pH)
        return pHChemistryResult(pH=pH, pK=pK, e1=e1, e2e3=e2e3, a1=a1, a2=a2, a_nir=a_nir, r_ratio=r)

    # ── Multi-injection regression ────────────────────────────────────────

    @staticmethod
    def regress(
        ph_values: list[float],
        vol_injected_ml: list[float],
        t_cuvette_values: list[float],
        t_ferrybox: float | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Temperature-drift-corrected pH regression across multiple injections.

        Applies a T-drift correction referenced to the first injection, then
        fits pH vs. injected volume to extrapolate to zero-dye pH. Selects
        the fit (all points, drop first, or drop last) with the highest r².

        Parameters
        ----------
        ph_values:
            Per-injection pH readings.
        vol_injected_ml:
            Cumulative dye volume injected at each step (mL).
        t_cuvette_values:
            In-cuvette temperature at each injection (°C).
        t_ferrybox:
            Ferrybox seawater temperature (°C) for in-situ correction.
            If None, in-situ pH equals cuvette pH.

        Returns
        -------
        (pH_cuvette, pH_insitu, r_square, slope)
        """
        ph = np.array(ph_values, dtype=float)
        vol = np.array(vol_injected_ml, dtype=float)
        t = np.array(t_cuvette_values, dtype=float)

        # Temperature-drift correction (reference = first injection T)
        t_ref = t[0]
        ph_corr = ph + _DPH_DT * (t_ref - t)

        if np.std(ph_corr) <= 0.001:
            pH_cuvette = float(np.mean(ph_corr))
            slope = 0.0
            r_square = 0.0
        else:
            # Try full set, drop-first, drop-last; keep best r²
            candidates: list[tuple[float, float, float]] = []  # (intercept, slope, r²)
            for indices in (
                slice(None),          # all
                slice(1, None),       # drop first
                slice(None, -1),      # drop last
            ):
                x = vol[indices]
                y = ph_corr[indices]
                if len(x) < 2:
                    continue
                slope_c, intercept_c = np.polyfit(x, y, 1)
                y_hat = slope_c * x + intercept_c
                ss_res = float(np.sum((y - y_hat) ** 2))
                ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 0.0
                candidates.append((intercept_c, slope_c, r2))

            best = max(candidates, key=lambda c: c[2])
            pH_cuvette, slope, r_square = best

        t_mean = float(np.mean(t))
        if t_ferrybox is not None:
            pH_insitu = pH_cuvette + _DPH_DT * (t_ferrybox - t_mean)
        else:
            pH_insitu = pH_cuvette

        logger.debug(
            "pH regression: cuvette=%.4f insitu=%.4f r²=%.4f slope=%.6f",
            pH_cuvette, pH_insitu, r_square, slope,
        )
        return pH_cuvette, pH_insitu, r_square, slope

    # ── Tris buffer reference ─────────────────────────────────────────────

    @staticmethod
    def theoretical_tris_ph(t_cuvette: float, salinity: float = 35.0) -> float:
        """
        Theoretical pH of a Tris buffer at temperature *t_cuvette* (°C).

        Used to verify instrument calibration against a known reference.
        """
        t_k = t_cuvette + 273.15
        s = salinity
        pH_tris = (
            (11911.08 - 18.2499 * s - 0.039336 * s ** 2) / t_k
            - 366.27059
            + 0.53993607 * s
            + 0.00016329 * s ** 2
            + (64.52243 - 0.084041 * s) * math.log(t_k)
            - 0.11149858 * t_k
        )
        return pH_tris

    # ── Absorbance utilities (shared with CO3 pattern) ────────────────────

    @staticmethod
    def compute_absorbance(
        post_injection: np.ndarray,
        blank: np.ndarray,
        dark: np.ndarray,
    ) -> np.ndarray:
        """
        Compute absorbance spectrum: A = -log10((I_sample - I_dark) / (I_blank - I_dark)).
        """
        blank_minus_dark = blank - dark
        sample_minus_dark = post_injection - dark
        blank_minus_dark = np.where(blank_minus_dark <= 0, 1e-6, blank_minus_dark)
        ratio = sample_minus_dark / blank_minus_dark
        ratio = np.clip(ratio, 1e-6, None)
        return -np.log10(ratio)

    @staticmethod
    def find_pixel(wavelengths: np.ndarray, target_nm: float) -> int:
        """Return the pixel index nearest to *target_nm*."""
        return int(np.abs(wavelengths - target_nm).argmin())

    @staticmethod
    def compute_dilution(
        cuvette_volume_ml: float,
        dye_volume_per_shot_ml: float,
        n_shots: int,
        injection_number: int,
    ) -> float:
        """Dilution factor after cumulative injections (injection_number is 1-based)."""
        vol_injected = dye_volume_per_shot_ml * n_shots * injection_number
        return cuvette_volume_ml / (cuvette_volume_ml + vol_injected)
