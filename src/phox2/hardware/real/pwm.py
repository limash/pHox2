"""
Real PWM output driver using pigpio.

Requires pigpiod daemon to be running:
    sudo pigpiod

Duty cycle is expressed as 0–100 (percentage); pigpio expects 0–255, so the
conversion is: pigpio_duty = round(duty / 100 * 255).
"""
from __future__ import annotations

import logging

from phox2.hardware.interfaces import IPWMOutput

logger = logging.getLogger(__name__)


class PigpioPWMOutput(IPWMOutput):
    """GPIO PWM output via pigpio (Raspberry Pi only)."""

    def __init__(self) -> None:
        import pigpio  # type: ignore[import]

        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError(
                "pigpio daemon not running. Start it with: sudo pigpiod"
            )

    def set_pwm(self, pin: int, duty: int) -> None:
        pigpio_duty = round(max(0, min(100, duty)) / 100 * 255)
        self._pi.set_PWM_dutycycle(pin, pigpio_duty)
        logger.debug("PigpioPWMOutput: pin %d → duty %d%% (%d/255)", pin, duty, pigpio_duty)

    def set_high(self, pin: int) -> None:
        self._pi.write(pin, 1)
        logger.debug("PigpioPWMOutput: pin %d → HIGH", pin)

    def set_low(self, pin: int) -> None:
        self._pi.write(pin, 0)
        logger.debug("PigpioPWMOutput: pin %d → LOW", pin)
