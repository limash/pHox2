"""
Hardware abstraction interfaces.

Every concrete driver (real or mock) must implement one of these ABCs.
High-level modules depend *only* on these abstractions — never on concrete
classes — following the Dependency Inversion Principle.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class IDigitalOutput(ABC):
    """GPIO digital output (relay or logic-level pin)."""

    @abstractmethod
    def set_high(self, pin: int) -> None:
        """Drive *pin* HIGH (relay energised / logic 1)."""

    @abstractmethod
    def set_low(self, pin: int) -> None:
        """Drive *pin* LOW (relay de-energised / logic 0)."""


class IAnalogInput(ABC):
    """Analogue input channel (ADC)."""

    @abstractmethod
    def read_voltage(self, channel: int) -> float:
        """Return a single voltage reading on *channel* (volts)."""

    @abstractmethod
    def average_voltage(self, channel: int, n: int) -> float:
        """Return the mean of *n* consecutive voltage readings (volts)."""


class IPWMOutput(IDigitalOutput):
    """PWM (pulse-width modulation) output — used to drive LED arrays.

    Extends IDigitalOutput so it can be used wherever a digital GPIO driver
    is expected (valve, pumps, stirrer, drain).
    """

    @abstractmethod
    def set_pwm(self, pin: int, duty: int) -> None:
        """Set PWM duty cycle on *pin* (0 = off, 100 = fully on)."""


class ISpectrometer(ABC):
    """USB spectrometer."""

    @property
    @abstractmethod
    def sensor_type(self) -> str:
        """Model identifier, e.g. ``'STS'`` or ``'FLMT'``."""

    @abstractmethod
    def get_wavelengths(self) -> np.ndarray:
        """Return the wavelength (nm) for every detector pixel."""

    @abstractmethod
    async def get_intensities(self, n_averages: int = 1) -> np.ndarray:
        """Return intensity (counts) averaged over *n_averages* acquisitions."""

    @abstractmethod
    def get_intensities_sync(self, n_averages: int = 1) -> np.ndarray:
        """Synchronous variant of :meth:`get_intensities`."""

    @abstractmethod
    async def set_integration_time(self, time_ms: float) -> None:
        """Set integration time in milliseconds."""

    @abstractmethod
    def reset_measurement_state(self) -> None:
        """
        Prepare the spectrometer for a fresh measurement cycle.

        For real hardware this is a no-op.  Mock implementations use it to
        reset internal call-sequence state so that dark → blank → sample
        ordering is reproduced correctly for each new cycle.
        """
