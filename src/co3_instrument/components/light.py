"""
Light source and shutter components.
"""
from __future__ import annotations

import logging

from co3_instrument.components.interfaces import ILightSource, IShutter
from co3_instrument.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)


class RelayLightSource(ILightSource):
    """UV lamp (or any relay-switched light source)."""

    def __init__(self, gpio: IDigitalOutput, pin: int) -> None:
        self._gpio = gpio
        self._pin = pin

    def turn_on(self) -> None:
        self._gpio.set_high(self._pin)
        logger.info("Light source ON")

    def turn_off(self) -> None:
        self._gpio.set_low(self._pin)
        logger.info("Light source OFF")


class RelayShutter(IShutter):
    """Mechanical shutter controlled by a relay."""

    def __init__(self, gpio: IDigitalOutput, pin: int) -> None:
        self._gpio = gpio
        self._pin = pin

    def open(self) -> None:
        self._gpio.set_high(self._pin)
        logger.debug("Shutter OPEN")

    def close(self) -> None:
        self._gpio.set_low(self._pin)
        logger.debug("Shutter CLOSED")
