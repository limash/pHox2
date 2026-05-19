"""
File storage for CO3 measurement results.

Writes three file types per measurement cycle:
  .spt — transposed intensity spectra (wavelengths × named columns)
  .evl — per-injection intermediate values
  .log — one-row summary appended to the daily log file

All paths are derived from the base_path configuration key.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from co3_instrument.measurement.models import MeasurementResult

logger = logging.getLogger(__name__)

_TIMESTAMP_FMT = "%Y%m%d_%H%M%S"
_LOG_TIMESTAMP_FMT = "%Y-%m-%d_%H:%M"


class FileStorage:
    """
    Persists CO3 measurement results to the file system.

    Single Responsibility: this class does nothing but I/O.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._data_dir = self._base / "data_co3"
        self._log_file = self._data_dir / "CO3.log"

    def save(self, result: MeasurementResult, filename_stem: str | None = None) -> None:
        """
        Persist all outputs for a single measurement cycle.

        Parameters
        ----------
        result:
            The result returned by the instrument API.
        filename_stem:
            Custom file stem (e.g. "20260512_130000").  If None, derived from
            the result timestamp.
        """
        stem = filename_stem or result.timestamp.strftime(_TIMESTAMP_FMT)

        self._save_spt(result, stem)
        self._save_evl(result, stem)
        self._append_log(result)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _save_spt(self, result: MeasurementResult, stem: str) -> None:
        spt_dir = self._data_dir / "spt"
        spt_dir.mkdir(parents=True, exist_ok=True)
        path = spt_dir / f"{stem}.spt"

        spectra = result.spectra
        df = pd.DataFrame({"Wavelengths": spectra.wavelengths})
        df["dark"] = spectra.dark
        df["blank"] = spectra.blank
        for idx, sp in spectra.injections.items():
            df[str(idx)] = sp

        # Transpose: rows = column names, columns = pixel values
        df.T.to_csv(path, index=True, header=False)
        logger.info("SPT saved → %s", path)

    def _save_evl(self, result: MeasurementResult, stem: str) -> None:
        evl_dir = self._data_dir / "evl"
        evl_dir.mkdir(parents=True, exist_ok=True)
        path = evl_dir / f"{stem}.evl"

        rows = [
            {
                "CO3": inj.co3_umol_per_kg,
                "e1": inj.e1,
                "e3e2": inj.e3e2,
                "log_beta1_e2": inj.log_beta1_e2,
                "Voltage": inj.voltage,
                "S": inj.salinity_input,
                "A1": inj.a1,
                "A2": inj.a2,
                "R": inj.r_ratio,
                "T_cuvette": inj.t_cuvette,
                "Vol_injected": inj.vol_injected_ml,
                "S_corr": inj.salinity_corrected,
                "A350": inj.a3,
            }
            for inj in result.injections
        ]
        pd.DataFrame(rows).to_csv(path, index=False)
        logger.info("EVL saved → %s", path)

    def _append_log(self, result: MeasurementResult) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame(
            [
                {
                    "Time": result.timestamp.strftime(_LOG_TIMESTAMP_FMT),
                    "SHIP": result.ship_code,
                    "co3": result.co3_umol_per_kg,
                    "T_cuvette": result.t_cuvette,
                    "S_input": result.salinity_input,
                    "S_corr": result.salinity_corrected,
                    "voltage": result.voltage,
                    "A1": result.a1,
                    "A2": result.a2,
                    "A3": result.a3,
                    "R": result.r_ratio,
                    "dye": result.dye,
                }
            ]
        )
        write_header = not self._log_file.exists()
        row.to_csv(self._log_file, mode="a", index=False, header=write_header)
        logger.info("Log appended → %s", self._log_file)
