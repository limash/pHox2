"""
In-memory mock Ferrybox client for unit tests.

``MockFerryboxClient`` satisfies ``IFerryboxClient`` without any networking.
Inject it wherever an ``IFerryboxClient`` is expected and inspect
``sent_payloads`` after the test to verify what was transmitted.
"""
from __future__ import annotations

from phox2.communication.interfaces import IFerryboxClient
from phox2.communication.models import FerryboxData, IUDPPayload


class MockFerryboxClient(IFerryboxClient):
    """
    In-memory stub for unit tests — no sockets, no I/O.

    Parameters
    ----------
    preset_data:
        Optional ``FerryboxData`` returned by ``get_latest_data()``.
        Pass ``None`` (default) to simulate no packet received yet.

    Attributes
    ----------
    sent_payloads : list[dict]
        Accumulates the dicts produced by each ``result.to_udp_payload()``
        call, in order.  Inspect this in tests to verify what was sent.
    started : bool
        ``True`` after ``start()`` has been called.
    stopped : bool
        ``True`` after ``stop()`` has been called.
    """

    def __init__(self, preset_data: FerryboxData | None = None) -> None:
        self._preset_data = preset_data
        self.sent_payloads: list[dict] = []
        self.started: bool = False
        self.stopped: bool = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def get_latest_data(self) -> FerryboxData | None:
        return self._preset_data

    def set_preset_data(self, data: FerryboxData | None) -> None:
        """Update the value returned by ``get_latest_data()`` at runtime."""
        self._preset_data = data

    async def send_result(self, result: IUDPPayload) -> None:
        self.sent_payloads.append(result.to_udp_payload())
