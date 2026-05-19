"""
Real ADC driver using ADCDifferentialPi (I²C, 18-bit MCP3424).

Install on Raspberry Pi:
    pip install ADCDifferentialPi
"""
from __future__ import annotations

import logging

from co3_instrument.hardware.interfaces import IAnalogInput

logger = logging.getLogger(__name__)


class ADCDifferentialPiReader(IAnalogInput):
    """ADC driver backed by the ``ADCDifferentialPi`` library."""

    def __init__(self, adc_cfg) -> None:
        try:
            from ADCDifferentialPi import ADCDifferentialPi  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "ADCDifferentialPi is required for real hardware mode."
            ) from exc

        self._adc = ADCDifferentialPi(0x68, 0x69, 14)
        self._adc.set_pga(1)
        logger.info("ADCDifferentialPi driver initialised")

    def read_voltage(self, channel: int) -> float:
        voltage = self._adc.read_voltage(channel)
        logger.debug("ADC ch%d → %.5f V", channel, voltage)
        return float(voltage)

    def average_voltage(self, channel: int, n: int) -> float:
        total = 0.0
        valid = 0
        for _ in range(n):
            try:
                total += self.read_voltage(channel)
                valid += 1
            except Exception:
                logger.warning("ADC read failed on ch%d", channel, exc_info=True)
        if valid == 0:
            logger.error("All ADC reads failed on ch%d", channel)
            return -999.0
        return round(total / valid, 5)
