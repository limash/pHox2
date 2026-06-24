"""
Quality-control evaluation for a completed measurement cycle.

The five checks mirror the original pHox instrument (`pHox_gui.py:qc`).
Each flag is tri-state: ``None`` = not evaluated, ``False`` = fail, ``True`` = pass.
This module is pure (no I/O, no hardware) so it is trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_DYE_THRESHOLD_COUNTS = 5.0
_BIOFOULING_INT_TIME_MS = 2000.0


@dataclass(frozen=True)
class QCFlags:
    """Tri-state quality-control flags for one measurement."""

    flow: bool | None = None
    dye: bool | None = None
    biofouling: bool | None = None
    temp_sensor: bool | None = None
    udp: bool | None = None
    overall: bool | None = None


def evaluate_qc(
    *,
    dark: np.ndarray,
    blank: np.ndarray,
    injection_spectra: dict[int, np.ndarray],
    voltages: list[float],
    blue_px: int,
    blue_now: float | None,
    integration_time_ms: float,
    fb_pumping: int | None,
    flow_threshold: float,
) -> QCFlags:
    """
    Evaluate the five QC checks and the overall flag.

    Parameters
    ----------
    dark, blank:
        Dark and blank intensity spectra (counts).
    injection_spectra:
        Post-injection raw spectra keyed by 0-based injection index.
    voltages:
        Per-injection ADC voltages (temperature probe).
    blue_px:
        Pixel index of the blue / λ1 wavelength used for the flow check.
    blue_now:
        Fresh blue-pixel intensity read ~3 s after the cycle (fresh sample),
        or ``None`` if not available.
    integration_time_ms:
        Spectrometer integration time at measurement time.
    fb_pumping:
        Ferrybox pump status (1/0/None).
    flow_threshold:
        Minimum blue-pixel rise for the flow check to pass.
    """
    # Flow: fresh blue level must rise above the last-injection blue level.
    flow: bool | None = None
    if blue_now is not None and injection_spectra:
        last_idx = max(injection_spectra)
        blue_last = float(injection_spectra[last_idx][blue_px])
        flow = (blue_now - blue_last) > flow_threshold

    # Dye is coming: blank minus first injection should show absorption.
    dye: bool | None = None
    if 0 in injection_spectra:
        dye = bool(float(np.mean(blank - injection_spectra[0])) > _DYE_THRESHOLD_COUNTS)

    # Biofouling: a high integration time means the window is fouled.
    biofouling = bool(integration_time_ms < _BIOFOULING_INT_TIME_MS)

    # Temperature sensor: readings must vary (a stuck probe reads constant).
    temp_sensor: bool | None = None
    if voltages:
        temp_sensor = not all(v == voltages[0] for v in voltages)

    # UDP/Ferrybox connection alive.
    udp = fb_pumping is not None

    overall = all([flow, dye, biofouling, temp_sensor, udp])
    return QCFlags(
        flow=flow,
        dye=dye,
        biofouling=biofouling,
        temp_sensor=temp_sensor,
        udp=udp,
        overall=overall,
    )
