"""
Mock ADC analogue input.

Returns synthetic temperature voltages that translate to realistic cuvette
temperatures via the linear calibration T = coef[0]*V + coef[1].
"""
from __future__ import annotations

import logging
import random

from phox2.hardware.interfaces import IAnalogInput

logger = logging.getLogger(__name__)

# Voltage corresponding to ~20 °C with default calibration [-1.234, 15.678]
# Solve: 20 = -1.234 * V + 15.678  →  V ≈ -3.38  (not physical)
# Use a typical probe output instead: ~0.6 V → T ≈ 14.9 °C
_DEFAULT_VOLTAGE = 0.6


class MockAnalogInput(IAnalogInput):
    """ADC that returns a fixed voltage with small random noise."""

    def __init__(self, temperature_cfg) -> None:
        # Back-calculate voltage from target temperature (20 °C) using coefs
        coef = list(temperature_cfg.calibration_coefficients)
        # T = coef[0]*V + coef[1]  →  V = (T - coef[1]) / coef[0]
        target_t = 20.0
        if coef[0] != 0:
            self._base_voltage = (target_t - coef[1]) / coef[0]
        else:
            self._base_voltage = _DEFAULT_VOLTAGE
        self._noise = 0.002  # ±2 mV noise

    def read_voltage(self, channel: int) -> float:
        voltage = self._base_voltage + random.gauss(0, self._noise)
        logger.debug("MOCK ADC ch%d → %.5f V", channel, voltage)
        return round(voltage, 5)

    def average_voltage(self, channel: int, n: int) -> float:
        readings = [self.read_voltage(channel) for _ in range(n)]
        avg = sum(readings) / len(readings)
        return round(avg, 5)
