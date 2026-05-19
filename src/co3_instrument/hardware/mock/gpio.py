"""
Mock GPIO digital output.

Logs all pin operations instead of driving real hardware.
Fully substitutable for PigpioDigitalOutput (Liskov Substitution Principle).
"""
from __future__ import annotations

import logging

from co3_instrument.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)


class MockDigitalOutput(IDigitalOutput):
    """GPIO handler that records state changes and logs them."""

    def __init__(self) -> None:
        self._states: dict[int, bool] = {}

    def set_high(self, pin: int) -> None:
        self._states[pin] = True
        logger.debug("MOCK GPIO pin %d → HIGH", pin)

    def set_low(self, pin: int) -> None:
        self._states[pin] = False
        logger.debug("MOCK GPIO pin %d → LOW", pin)

    # ── Inspection helpers (not part of the interface) ─────────────────────
    def get_state(self, pin: int) -> bool:
        """Return the current simulated state of *pin*."""
        return self._states.get(pin, False)

    def reset(self) -> None:
        """Reset all pin states to LOW."""
        self._states.clear()
