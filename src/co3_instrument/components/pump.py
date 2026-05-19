"""
Pump components.

RelayWaterPump   — simple relay-switched peristaltic pump.
SolenoidDyePump  — pulsed solenoid pump; each "shot" is a short on/off cycle.
RelayStirrer     — magnetic stirrer (relay on/off).
"""
from __future__ import annotations

import asyncio
import logging

from co3_instrument.components.interfaces import IDyePump, IStirrer, IWaterPump
from co3_instrument.hardware.interfaces import IDigitalOutput

logger = logging.getLogger(__name__)

# Solenoid dye-pump pulse timings (seconds)
_DYE_ON_S = 0.15
_DYE_OFF_S = 0.35


class RelayWaterPump(IWaterPump):
    """Water / sample pump controlled by a single relay."""

    def __init__(self, gpio: IDigitalOutput, pin: int) -> None:
        self._gpio = gpio
        self._pin = pin

    async def run(self, duration_s: float) -> None:
        logger.info("Water pump ON (%.1f s)", duration_s)
        self._gpio.set_high(self._pin)
        await asyncio.sleep(duration_s)
        self._gpio.set_low(self._pin)
        logger.info("Water pump OFF")


class SolenoidDyePump(IDyePump):
    """
    Dye injection pump driven by a solenoid valve.

    Each shot: relay HIGH for _DYE_ON_S, then LOW for _DYE_OFF_S.
    """

    def __init__(self, gpio: IDigitalOutput, pin: int) -> None:
        self._gpio = gpio
        self._pin = pin

    async def pulse(self, n_shots: int) -> None:
        logger.info("Dye pump: %d shots", n_shots)
        for i in range(n_shots):
            self._gpio.set_high(self._pin)
            logger.debug("Dye shot %d/%d ON", i + 1, n_shots)
            await asyncio.sleep(_DYE_ON_S)
            self._gpio.set_low(self._pin)
            await asyncio.sleep(_DYE_OFF_S)


class RelayStirrer(IStirrer):
    """Magnetic stirrer controlled by a relay."""

    def __init__(self, gpio: IDigitalOutput, pin: int) -> None:
        self._gpio = gpio
        self._pin = pin

    def start(self) -> None:
        self._gpio.set_high(self._pin)
        logger.debug("Stirrer ON")

    def stop(self) -> None:
        self._gpio.set_low(self._pin)
        logger.debug("Stirrer OFF")
