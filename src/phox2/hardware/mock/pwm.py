"""
Mock PWM output driver.

Logs all operations; does not interact with any hardware.
Used for development and testing on non-Raspberry-Pi machines.
"""
from __future__ import annotations

import logging

from phox2.hardware.interfaces import IPWMOutput

logger = logging.getLogger(__name__)


class MockPWMOutput(IPWMOutput):
    """In-memory PWM output that records every write for inspection."""

    def __init__(self) -> None:
        # pin → current duty cycle (0–100)
        self._duties: dict[int, int] = {}

    def set_pwm(self, pin: int, duty: int) -> None:
        self._duties[pin] = duty
        logger.debug("MockPWMOutput: pin %d → duty %d%%", pin, duty)

    def set_high(self, pin: int) -> None:
        self._duties[pin] = 100
        logger.debug("MockPWMOutput: pin %d → HIGH", pin)

    def set_low(self, pin: int) -> None:
        self._duties[pin] = 0
        logger.debug("MockPWMOutput: pin %d → LOW", pin)
