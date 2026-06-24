"""
File storage for CO3 and pH measurement results.

Writes three file types per measurement cycle:
  .spt — transposed intensity spectra (wavelengths × named columns)
  .evl — per-injection intermediate values
  .log — one-row summary appended to the shared log file

All paths are derived from the base_path configuration key.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from phox2.measurement.models import CO3MeasurementResult, pHMeasurementResult

logger = logging.getLogger(__name__)

_TIMESTAMP_FMT = "%Y%m%d_%H%M%S"
_LOG_TIMESTAMP_FMT = "%Y-%m-%d_%H:%M"


class CO3FileStorage:
    """
    Persists CO3 measurement results to the file system.

    Single Responsibility: this class does nothing but I/O.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._data_dir = self._base / "data_co3"
        self._log_file = self._data_dir / "CO3.log"

    def save(self, result: CO3MeasurementResult, filename_stem: str | None = None) -> None:
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

    def _save_spt(self, result: CO3MeasurementResult, stem: str) -> None:
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

    def _save_evl(self, result: CO3MeasurementResult, stem: str) -> None:
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

    def _append_log(self, result: CO3MeasurementResult) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame(
            [
                {
                    "Time": result.timestamp.strftime(_LOG_TIMESTAMP_FMT),
                    "Lon": result.longitude,
                    "Lat": result.latitude,
                    "fb_temp": result.fb_temp,
                    "fb_sal": result.fb_sal,
                    "SHIP": result.ship_code,
                    "co3": result.co3_umol_per_kg,
                    "box_id": result.box_id,
                    "T_cuvette": result.t_cuvette,
                    "flow_QC": result.qc_flow,
                    "dye_coming_qc": result.qc_dye,
                    "biofouling_qc": result.qc_biofouling,
                    "temp_sens_qc": result.qc_temp_sensor,
                    "UDP_conn_qc": result.qc_udp,
                    "overall_qc": result.qc_overall,
                }
            ]
        )
        write_header = not self._log_file.exists()
        row.to_csv(self._log_file, mode="a", index=False, header=write_header)
        logger.info("Log appended → %s", self._log_file)


class pHFileStorage:
    """
    Persists pH measurement results to the file system.

    Writes to ``{base}/data_pH/`` mirroring the CO3FileStorage layout.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._data_dir = self._base / "data_pH"
        self._log_file = self._data_dir / "pH.log"

    def save(self, result: pHMeasurementResult, filename_stem: str | None = None) -> None:
        """Persist all outputs for a single pH measurement cycle."""
        stem = filename_stem or result.timestamp.strftime(_TIMESTAMP_FMT)
        self._save_spt(result, stem)
        self._save_evl(result, stem)
        self._append_log(result)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _save_spt(self, result: pHMeasurementResult, stem: str) -> None:
        spt_dir = self._data_dir / "spt"
        spt_dir.mkdir(parents=True, exist_ok=True)
        path = spt_dir / f"{stem}.spt"

        spectra = result.spectra
        df = pd.DataFrame({"Wavelengths": spectra.wavelengths})
        df["dark"] = spectra.dark
        df["blank"] = spectra.blank
        for idx, sp in spectra.injections.items():
            df[str(idx)] = sp

        df.T.to_csv(path, index=True, header=False)
        logger.info("SPT saved → %s", path)

    def _save_evl(self, result: pHMeasurementResult, stem: str) -> None:
        evl_dir = self._data_dir / "evl"
        evl_dir.mkdir(parents=True, exist_ok=True)
        path = evl_dir / f"{stem}.evl"

        rows = [
            {
                "pH": inj.pH,
                "pK": inj.pK,
                "e1": inj.e1,
                "e2e3": inj.e2e3,
                "Voltage": inj.voltage,
                "salinity": inj.salinity_input,
                "A1": inj.a1,
                "A2": inj.a2,
                "T_cuvette": inj.t_cuvette,
                "S_corr": inj.salinity_corrected,
                "Anir": inj.a_nir,
                "Vol_injected": inj.vol_injected_ml,
                "DYE": inj.dye,
            }
            for inj in result.injections
        ]
        pd.DataFrame(rows).to_csv(path, index=False)
        logger.info("EVL saved → %s", path)

    def _append_log(self, result: pHMeasurementResult) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        row = pd.DataFrame(
            [
                {
                    "Time": result.timestamp.strftime(_LOG_TIMESTAMP_FMT),
                    "Lon": result.longitude,
                    "Lat": result.latitude,
                    "fb_temp": result.fb_temp,
                    "fb_sal": result.fb_sal,
                    "SHIP": result.ship_code,
                    "pH_cuvette": result.pH_cuvette,
                    "T_cuvette": result.t_cuvette,
                    "perturbation": result.slope,
                    "evalAnir": result.a_nir,
                    "pH_insitu": result.pH_insitu,
                    "r_square": result.r_square,
                    "box_id": result.box_id,
                    "flow_QC": result.qc_flow,
                    "dye_coming_qc": result.qc_dye,
                    "biofouling_qc": result.qc_biofouling,
                    "temp_sens_qc": result.qc_temp_sensor,
                    "UDP_conn_qc": result.qc_udp,
                    "overall_qc": result.qc_overall,
                }
            ]
        )
        write_header = not self._log_file.exists()
        row.to_csv(self._log_file, mode="a", index=False, header=write_header)
        logger.info("Log appended → %s", self._log_file)

