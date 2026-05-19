"""
Shared data models for the Ferrybox UDP communication layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FerryboxData:
    """
    A snapshot of data received from the Ferrybox over UDP.

    Parameters
    ----------
    salinity:
        In-situ salinity (PSU).
    timestamp:
        Time the Ferrybox packet was received (local clock).
    temperature:
        Optional sea-surface temperature (°C) provided by the Ferrybox.
    """

    salinity: float
    timestamp: datetime
    temperature: float | None = None


@runtime_checkable
class IUDPPayload(Protocol):
    """
    Structural protocol for objects that can be serialised and sent over UDP.

    Any measurement result implementing ``to_udp_payload()`` satisfies this
    protocol without any inheritance.  This keeps ``IFerryboxClient`` open
    to new instrument types without changing the interface.
    """

    def to_udp_payload(self) -> dict:
        """Return a JSON-serialisable dict representation of the result."""
        ...
