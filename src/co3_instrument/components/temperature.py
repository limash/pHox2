"""
In-cuvette temperature sensor.

Converts a raw ADC voltage to degrees Celsius using a linear calibration:
    T (°C) = coef[0] × V + coef[1]
"""
from __future__ import annotations

import logging

from co3_instrument.components.interfaces import ITemperatureSensor
from co3_instrument.hardware.interfaces import IAnalogInput

logger = logging.getLogger(__name__)


class ADCTemperatureSensor(ITemperatureSensor):
    """Temperature probe read via an ADC channel."""

    def __init__(
        self,
        adc: IAnalogInput,
        channel: int,
        coefficients: list[float],
        n_averages: int = 3,
    ) -> None:
        if len(coefficients) != 2:
            raise ValueError("coefficients must have exactly 2 elements [slope, intercept]")
        self._adc = adc
        self._channel = channel
        self._coef = coefficients
        self._n = n_averages

    def read_temperature(self) -> float:
        """Return cuvette temperature in °C."""
        voltage = self._adc.average_voltage(self._channel, self._n)
        temperature = self._coef[0] * voltage + self._coef[1]
        logger.debug("T_cuvette = %.3f °C  (V = %.5f)", temperature, voltage)
        return temperature

    def read_voltage(self) -> float:
        """Return the raw averaged voltage (for logging in EVL files)."""
        return self._adc.average_voltage(self._channel, self._n)
