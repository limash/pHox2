"""
Real GPIO handler using the pigpio library.

pigpio must be installed and the daemon (pigpiod) must be running:
    sudo pigpiod
"""
from __future__ import annotations

import logging

from phox2.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)


class PigpioDigitalOutput(IDigitalOutput):
    """GPIO driver backed by the ``pigpio`` C library."""

    def __init__(self) -> None:
        try:
            import pigpio  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pigpio is required for real hardware mode. "
                "Install it on the Raspberry Pi and start pigpiod."
            ) from exc

        self._rpi = pigpio.pi()
        if not self._rpi.connected:
            raise RuntimeError(
                "Cannot connect to the pigpio daemon. Run: sudo pigpiod"
            )
        self._pigpio = pigpio
        logger.info("pigpio GPIO driver initialised")

    def set_high(self, pin: int) -> None:
        self._rpi.write(pin, True)
        logger.debug("GPIO pin %d → HIGH", pin)

    def set_low(self, pin: int) -> None:
        self._rpi.write(pin, False)
        logger.debug("GPIO pin %d → LOW", pin)

    def configure_output(self, pin: int) -> None:
        """Set *pin* as a GPIO output (call once during initialisation)."""
        self._rpi.set_mode(pin, self._pigpio.OUTPUT)

    def close(self) -> None:
        """Release the pigpio connection."""
        if self._rpi.connected:
            self._rpi.stop()
        logger.info("pigpio GPIO driver closed")
