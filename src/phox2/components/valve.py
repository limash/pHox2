"""
Bistable inlet valve.

The valve uses three GPIO pins:
  enable_pin  — energises the driver coil
  ch1_pin     — direction A  (open)
  ch2_pin     — direction B  (close)

A short pulse (toggle_duration_s) flips the bistable mechanism; the valve
holds its position without power after the pulse.
"""
from __future__ import annotations

import asyncio
import logging

from phox2.components.interfaces import IValve
from phox2.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)


class BistableValve(IValve):
    """Bistable (latching) solenoid valve driven by three GPIO pins."""

    def __init__(
        self,
        gpio: IDigitalOutput,
        enable_pin: int,
        ch1_pin: int,
        ch2_pin: int,
        toggle_duration_s: float = 0.3,
    ) -> None:
        self._gpio = gpio
        self._enable = enable_pin
        self._ch1 = ch1_pin
        self._ch2 = ch2_pin
        self._toggle_s = toggle_duration_s

    async def open(self) -> None:
        logger.info("Valve → OPEN")
        await self._pulse(active_ch=self._ch1, inactive_ch=self._ch2)

    async def close(self) -> None:
        logger.info("Valve → CLOSE")
        await self._pulse(active_ch=self._ch2, inactive_ch=self._ch1)

    async def _pulse(self, active_ch: int, inactive_ch: int) -> None:
        self._gpio.set_high(active_ch)
        self._gpio.set_low(inactive_ch)
        self._gpio.set_high(self._enable)
        await asyncio.sleep(self._toggle_s)
        self._gpio.set_low(active_ch)
        self._gpio.set_low(inactive_ch)
        self._gpio.set_low(self._enable)
