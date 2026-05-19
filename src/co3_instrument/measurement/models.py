"""
Data models for CO3 and pH measurement results.

Using frozen dataclasses for immutability — measurement results should not be
mutated after they are produced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class CO3InjectionResult:
    """
    Per-injection intermediate result (one row in the EVL file).
    """

    injection_index: int          # 0-based
    vol_injected_ml: float
    dilution: float
    voltage: float                # raw ADC voltage for temperature
    t_cuvette: float              # °C
    salinity_input: float         # Ferrybox / manual salinity before dilution
    salinity_corrected: float     # after dilution correction
    a1: float                     # absorbance at λ1
    a2: float                     # absorbance at λ2
    a3: float                     # absorbance at λ3 (reference)
    r_ratio: float
    e1: float
    e3e2: float
    log_beta1_e2: float
    co3_umol_per_kg: float


@dataclass(frozen=True)
class SpectralData:
    """Raw intensity spectra captured during a measurement cycle."""

    wavelengths: np.ndarray       # (n_pixels,)  nm
    dark: np.ndarray              # (n_pixels,)  counts
    blank: np.ndarray             # (n_pixels,)  counts
    # post-injection spectra keyed by 0-based injection index
    injections: dict[int, np.ndarray] = field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


@dataclass(frozen=True)
class CO3MeasurementResult:
    """
    Final output of a complete CO3 measurement cycle.

    This is the primary DTO returned by CO3InstrumentAPI.run_single_measurement().
    """

    timestamp: datetime
    ship_code: str

    # ── Final CO3 value (from single injection, or mean of multiple) ──────
    co3_umol_per_kg: float
    t_cuvette: float              # °C at time of measurement
    salinity_input: float         # before dilution
    salinity_corrected: float     # after dilution
    voltage: float                # raw ADC voltage

    # ── Absorbance readings ───────────────────────────────────────────────
    a1: float
    a2: float
    a3: float
    r_ratio: float

    # ── Chemistry coefficients ────────────────────────────────────────────
    e1: float
    e3e2: float
    log_beta1_e2: float

    # ── Volumetric info ───────────────────────────────────────────────────
    vol_injected_ml: float
    dye: str

    # ── Per-injection details ─────────────────────────────────────────────
    injections: tuple[CO3InjectionResult, ...]
    spectra: SpectralData

    def summary(self) -> str:
        return (
            f"CO3 = {self.co3_umol_per_kg:.1f} µmol/kg | "
            f"T_cuvette = {self.t_cuvette:.3f} °C | "
            f"S_corr = {self.salinity_corrected:.3f} | "
            f"R = {self.r_ratio:.4f} | "
            f"timestamp = {self.timestamp.isoformat(timespec='seconds')}"
        )


# ── pH data models ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class pHInjectionResult:
    """Per-injection intermediate result for the pH instrument (one EVL row)."""

    injection_index: int          # 0-based
    vol_injected_ml: float
    dilution: float
    voltage: float                # raw ADC voltage for temperature
    t_cuvette: float              # °C
    salinity_input: float         # before dilution
    salinity_corrected: float     # after dilution correction
    a1: float                     # absorbance at λ1 (434 nm)
    a2: float                     # absorbance at λ2 (578/596 nm)
    a_nir: float                  # absorbance at NIR reference (730 nm)
    r_ratio: float                # A2 / A1
    e1: float
    e2e3: float
    pK: float
    pH: float
    dye: str


@dataclass(frozen=True)
class pHMeasurementResult:
    """
    Final output of a complete pH measurement cycle.

    Returned by pHInstrumentAPI.run_single_measurement().
    """

    timestamp: datetime
    ship_code: str

    # ── Final pH values ───────────────────────────────────────────────────
    pH_cuvette: float             # intercept of multi-injection regression
    pH_insitu: float              # T-corrected to Ferrybox temperature
    r_square: float               # regression r²
    slope: float                  # regression slope (mL⁻¹)

    # ── Representative injection values (from last injection) ─────────────
    t_cuvette: float              # °C
    salinity_input: float
    salinity_corrected: float
    voltage: float
    a1: float
    a2: float
    a_nir: float
    r_ratio: float
    e1: float
    e2e3: float
    pK: float

    # ── Volumetric / metadata ─────────────────────────────────────────────
    vol_injected_ml: float        # total dye volume injected (mL)
    dye: str

    # ── Per-injection details ─────────────────────────────────────────────
    injections: tuple[pHInjectionResult, ...]
    spectra: SpectralData

    def summary(self) -> str:
        return (
            f"pH_cuvette = {self.pH_cuvette:.4f} | "
            f"pH_insitu = {self.pH_insitu:.4f} | "
            f"T_cuvette = {self.t_cuvette:.3f} °C | "
            f"S_corr = {self.salinity_corrected:.3f} | "
            f"r² = {self.r_square:.4f} | "
            f"timestamp = {self.timestamp.isoformat(timespec='seconds')}"
        )

