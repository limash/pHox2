"""
Real PWM output driver using lgpio.

lgpio uses the Linux GPIO character device (/dev/gpiochip0); no daemon needed.
Install with:
    sudo apt install python3-lgpio
    # or: pip install lgpio

Duty cycle is expressed as 0–100 (percentage), which maps directly to lgpio's
tx_pwm duty-cycle parameter (0.0–100.0).
"""
from __future__ import annotations

import logging

import lgpio  # type: ignore[import-untyped]

from phox2.hardware.interfaces import IPWMOutput

logger = logging.getLogger(__name__)

_GPIOCHIP = 0   # /dev/gpiochip0 — standard on Raspberry Pi
_PWM_FREQ = 1000  # Hz — suitable for LED brightness control


class LgpioPWMOutput(IPWMOutput):
    """GPIO PWM output via lgpio (Raspberry Pi, kernel 6.x compatible)."""

    def __init__(self) -> None:
        self._h = lgpio.gpiochip_open(_GPIOCHIP)
        logger.info("lgpio PWM driver initialised (gpiochip%d)", _GPIOCHIP)

    def configure_output(self, pin: int) -> None:
        """Claim *pin* as a GPIO output (call once during initialisation)."""
        lgpio.gpio_claim_output(self._h, pin)

    def set_pwm(self, pin: int, duty: int) -> None:
        duty_clamped = float(max(0, min(100, duty)))
        lgpio.tx_pwm(self._h, pin, _PWM_FREQ, duty_clamped)
        logger.debug("LgpioPWMOutput: pin %d → duty %d%%", pin, duty)

    def set_high(self, pin: int) -> None:
        lgpio.tx_pwm(self._h, pin, _PWM_FREQ, 100.0)
        logger.debug("LgpioPWMOutput: pin %d → HIGH", pin)

    def set_low(self, pin: int) -> None:
        lgpio.tx_pwm(self._h, pin, _PWM_FREQ, 0.0)
        logger.debug("LgpioPWMOutput: pin %d → LOW", pin)

    def close(self) -> None:
        """Release the lgpio chip handle."""
        lgpio.gpiochip_close(self._h)
        logger.info("lgpio PWM driver closed")
