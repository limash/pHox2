"""
Instrument component interfaces (Interface Segregation Principle).

Each interface covers a single, focused hardware role.  Components never
expose unrelated behaviour — a valve knows nothing about pumps, and vice-versa.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class IValve(ABC):
    """Bistable inlet valve."""

    @abstractmethod
    async def open(self) -> None:
        """Open the inlet valve (sample flows in)."""

    @abstractmethod
    async def close(self) -> None:
        """Close the inlet valve (sample is isolated)."""


class IWaterPump(ABC):
    """Peristaltic water / sample pump."""

    @abstractmethod
    async def run(self, duration_s: float) -> None:
        """Run the pump for *duration_s* seconds."""


class IDyePump(ABC):
    """Solenoid dye injection pump."""

    @abstractmethod
    async def pulse(self, n_shots: int) -> None:
        """Fire *n_shots* solenoid pulses to inject dye."""


class IStirrer(ABC):
    """Magnetic stirrer."""

    @abstractmethod
    def start(self) -> None:
        """Energise the stirrer motor."""

    @abstractmethod
    def stop(self) -> None:
        """De-energise the stirrer motor."""


class ILightSource(ABC):
    """UV lamp (or LED array)."""

    @abstractmethod
    def turn_on(self) -> None:
        """Switch the light source on."""

    @abstractmethod
    def turn_off(self) -> None:
        """Switch the light source off."""


class IShutter(ABC):
    """Mechanical or electronic optical shutter."""

    @abstractmethod
    def open(self) -> None:
        """Open the shutter (light reaches detector)."""

    @abstractmethod
    def close(self) -> None:
        """Close the shutter (detector sees dark)."""


class IDrain(ABC):
    """Cuvette drain system (drain valve + air pump)."""

    @abstractmethod
    async def drain(self, duration_s: float) -> None:
        """Open drain and run air pump for *duration_s* seconds, then close."""


class ITemperatureSensor(ABC):
    """In-cuvette temperature probe (ADC-based thermistor / PT100)."""

    @abstractmethod
    def read_temperature(self) -> float:
        """Return cuvette temperature in degrees Celsius."""

    @abstractmethod
    def read_voltage(self) -> float:
        """Return the raw averaged ADC voltage (used for live display and EVL logging)."""


class ILEDArray(ABC):
    """Multi-channel LED array (used by pH instrument)."""

    @abstractmethod
    def turn_on(self) -> None:
        """Apply the configured duty cycles to all LED channels."""

    @abstractmethod
    def turn_off(self) -> None:
        """Set all LED channels to zero duty cycle (dark)."""

    @abstractmethod
    def set_duty_cycle(self, channel: int, duty: int) -> None:
        """Set PWM duty cycle for *channel* (0-based index; 0–100)."""
