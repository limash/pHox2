"""
Abstract interface for Ferrybox UDP communication.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from phox2.communication.models import FerryboxData, IUDPPayload


class IFerryboxClient(ABC):
    """
    Abstract contract for bidirectional Ferrybox UDP communication.

    Concrete implementations:
    - ``FerryboxUDPClient``  — real UDP socket using asyncio.DatagramProtocol
    - ``NullFerryboxClient`` — no-op; used when ferrybox.enabled is false
    - ``MockFerryboxClient`` — in-memory stub for unit tests

    All instrument APIs receive this via dependency injection; they never
    instantiate a concrete client directly.
    """

    @abstractmethod
    async def start(self) -> None:
        """Open the UDP socket and begin listening for Ferrybox datagrams."""

    @abstractmethod
    async def stop(self) -> None:
        """Close the UDP socket and release resources."""

    @abstractmethod
    def get_latest_data(self) -> FerryboxData | None:
        """
        Return the most recently received Ferrybox packet, or ``None`` if no
        packet has been received yet.

        This is a synchronous read of a cached value — no I/O is performed.
        """

    @abstractmethod
    async def send_result(self, result: IUDPPayload) -> None:
        """
        Serialise *result* and transmit it to the Ferrybox over UDP.

        Accepts any object satisfying the ``IUDPPayload`` protocol (i.e.
        any measurement result with a ``to_udp_payload()`` method).
        Fire-and-forget: errors are logged but not raised.
        """
