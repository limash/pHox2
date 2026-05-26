"""
Real GPIO handler using the lgpio library.

lgpio uses the Linux GPIO character device (/dev/gpiochip0) and works on
kernel 6.x without a daemon. Install with:
    sudo apt install python3-lgpio
    # or: pip install lgpio
"""
from __future__ import annotations

import logging

import lgpio  # type: ignore[import-untyped]

from phox2.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)

_GPIOCHIP = 0  # /dev/gpiochip0 — standard on Raspberry Pi


class LgpioDigitalOutput(IDigitalOutput):
    """GPIO driver backed by the ``lgpio`` library (kernel 6.x compatible)."""

    def __init__(self) -> None:
        self._h = lgpio.gpiochip_open(_GPIOCHIP)
        logger.info("lgpio GPIO driver initialised (gpiochip%d)", _GPIOCHIP)

    def set_high(self, pin: int) -> None:
        lgpio.gpio_write(self._h, pin, 1)
        logger.debug("GPIO pin %d → HIGH", pin)

    def set_low(self, pin: int) -> None:
        lgpio.gpio_write(self._h, pin, 0)
        logger.debug("GPIO pin %d → LOW", pin)

    def configure_output(self, pin: int) -> None:
        """Claim *pin* as a GPIO output (call once during initialisation)."""
        lgpio.gpio_claim_output(self._h, pin)

    def close(self) -> None:
        """Release the lgpio chip handle."""
        lgpio.gpiochip_close(self._h)
        logger.info("lgpio GPIO driver closed")
