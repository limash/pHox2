"""
Drain system: opens a drain valve and simultaneously runs an air pump to
push liquid out of the cuvette.
"""
from __future__ import annotations

import asyncio
import logging

from phox2.components.interfaces import IDrain
from phox2.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)


class AirPressureDrain(IDrain):
    """
    Cuvette drain that uses gravity + compressed air.

    Both drain relay and air-pump relay are energised for *duration_s*
    seconds, then both are de-energised.
    """

    def __init__(
        self,
        gpio: IDigitalOutput,
        drain_pin: int,
        air_pin: int,
    ) -> None:
        self._gpio = gpio
        self._drain_pin = drain_pin
        self._air_pin = air_pin

    async def drain(self, duration_s: float) -> None:
        logger.info("Draining cuvette (%.0f s)", duration_s)
        self._gpio.set_high(self._drain_pin)
        self._gpio.set_high(self._air_pin)
        await asyncio.sleep(duration_s)
        self._gpio.set_low(self._air_pin)
        self._gpio.set_low(self._drain_pin)
        logger.info("Draining complete")
