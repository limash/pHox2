"""
Light source and shutter components.
"""
from __future__ import annotations

import logging

from phox2.components.interfaces import ILEDArray, ILightSource, IShutter
from phox2.hardware.interfaces import IDigitalOutput, IPWMOutput

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


class PWMLEDArray(ILEDArray):
    """
    Multi-channel LED array driven by PWM (pH instrument).

    Parameters
    ----------
    pwm:
        PWM output driver (mock or real).
    pins:
        BCM pin numbers for each LED channel (index = channel number).
    initial_duties:
        Duty cycle (0–100) to restore when turn_on() is called.
    """

    def __init__(
        self,
        pwm: IPWMOutput,
        pins: list[int],
        initial_duties: list[int],
    ) -> None:
        if len(pins) != len(initial_duties):
            raise ValueError("pins and initial_duties must have the same length")
        self._pwm = pwm
        self._pins = pins
        self._duties = list(initial_duties)

    def turn_on(self) -> None:
        for pin, duty in zip(self._pins, self._duties):
            self._pwm.set_pwm(pin, duty)
        logger.info("LED array ON: duties=%s", self._duties)

    def turn_off(self) -> None:
        for pin in self._pins:
            self._pwm.set_pwm(pin, 0)
        logger.debug("LED array OFF (dark)")

    def set_duty_cycle(self, channel: int, duty: int) -> None:
        if channel < 0 or channel >= len(self._pins):
            raise ValueError(f"Channel {channel} out of range (0–{len(self._pins) - 1})")
        self._duties[channel] = duty
        self._pwm.set_pwm(self._pins[channel], duty)
        logger.debug("LED channel %d → duty %d%%", channel, duty)

