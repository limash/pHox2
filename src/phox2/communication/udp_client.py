"""
Concrete Ferrybox UDP client implementations.

Two classes are provided:

``FerryboxUDPClient``
    Real implementation using ``asyncio.DatagramProtocol``.  Binds a local
    UDP socket, caches the latest incoming Ferrybox packet, and can transmit
    measurement results back to the Ferrybox host.

``NullFerryboxClient``
    No-op implementation used when ``ferrybox.enabled`` is ``false`` in the
    config.  All methods are safe to call and do nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from phox2.communication.interfaces import IFerryboxClient
from phox2.communication.models import FerryboxData, IUDPPayload

logger = logging.getLogger(__name__)


class _FerryboxProtocol(asyncio.DatagramProtocol):
    """
    Internal asyncio protocol that handles raw UDP datagrams from the Ferrybox.

    Each received datagram is expected to be a UTF-8 encoded, newline-delimited
    JSON object of the form::

        {"type": "ferrybox_data", "salinity": 35.012, "temperature": 18.5,
         "timestamp": "2026-05-19T12:00:00"}

    Malformed packets are logged and silently discarded.
    """

    def __init__(self, on_data: "asyncio.Future[None] | None" = None) -> None:
        self._on_data_callbacks: list[asyncio.Callable[[FerryboxData], None]] = []

    def add_callback(self, cb: "asyncio.Callable[[FerryboxData], None]") -> None:
        self._on_data_callbacks.append(cb)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            payload = json.loads(data.decode("utf-8").strip())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Ferrybox: malformed datagram from %s: %s", addr, exc)
            return

        if payload.get("type") != "ferrybox_data":
            logger.debug("Ferrybox: ignoring packet type %r from %s", payload.get("type"), addr)
            return

        try:
            salinity = float(payload["salinity"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Ferrybox: missing/invalid salinity in packet from %s: %s", addr, exc)
            return

        temperature: float | None = None
        if "temperature" in payload:
            try:
                temperature = float(payload["temperature"])
            except (TypeError, ValueError):
                pass  # optional field — ignore if malformed

        fb_data = FerryboxData(
            salinity=salinity,
            timestamp=datetime.now(tz=timezone.utc),
            temperature=temperature,
        )
        for cb in self._on_data_callbacks:
            cb(fb_data)

    def error_received(self, exc: Exception) -> None:
        logger.error("Ferrybox UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is not None:
            logger.warning("Ferrybox UDP connection lost: %s", exc)


class FerryboxUDPClient(IFerryboxClient):
    """
    Bidirectional Ferrybox UDP client backed by ``asyncio.DatagramProtocol``.

    Binds a local UDP socket on *local_port* and sends outgoing datagrams to
    (*ferrybox_host*, *ferrybox_port*).

    Parameters
    ----------
    ferrybox_host:
        IP address or hostname of the Ferrybox.
    ferrybox_port:
        UDP port the Ferrybox listens on for instrument results.
    local_port:
        Local UDP port to bind for receiving Ferrybox data.
    """

    def __init__(
        self,
        ferrybox_host: str,
        ferrybox_port: int,
        local_port: int,
    ) -> None:
        self._host = ferrybox_host
        self._ferrybox_port = ferrybox_port
        self._local_port = local_port
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _FerryboxProtocol | None = None
        self._latest: FerryboxData | None = None

    # ── IFerryboxClient ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Bind the local UDP socket and start listening."""
        loop = asyncio.get_running_loop()
        protocol = _FerryboxProtocol()
        protocol.add_callback(self._on_data)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            local_addr=("0.0.0.0", self._local_port),
        )
        self._transport = transport  # type: ignore[assignment]
        self._protocol = protocol
        logger.info(
            "Ferrybox UDP client started — listening on :%d, sending to %s:%d",
            self._local_port,
            self._host,
            self._ferrybox_port,
        )

    async def stop(self) -> None:
        """Close the UDP socket."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            self._protocol = None
            logger.info("Ferrybox UDP client stopped")

    def get_latest_data(self) -> FerryboxData | None:
        """Return the most recently received Ferrybox packet (cached, sync)."""
        return self._latest

    async def send_result(self, result: IUDPPayload) -> None:
        """Serialise *result* and transmit it to the Ferrybox (fire-and-forget)."""
        if self._transport is None:
            logger.warning("Ferrybox client not started; skipping send_result()")
            return
        try:
            payload = result.to_udp_payload()
            data = (json.dumps(payload) + "\n").encode("utf-8")
            self._transport.sendto(data, (self._host, self._ferrybox_port))
            logger.debug("Ferrybox: sent %s payload to %s:%d", payload.get("type"), self._host, self._ferrybox_port)
        except Exception as exc:
            logger.error("Ferrybox: failed to send result: %s", exc)

    # ── Internal ──────────────────────────────────────────────────────────

    def _on_data(self, data: FerryboxData) -> None:
        self._latest = data
        logger.debug(
            "Ferrybox: received — S=%.3f, T=%s",
            data.salinity,
            f"{data.temperature:.2f} °C" if data.temperature is not None else "n/a",
        )


class NullFerryboxClient(IFerryboxClient):
    """
    No-op Ferrybox client used when ``ferrybox.enabled: false``.

    Safe to inject into both instrument APIs: all methods do nothing and
    ``get_latest_data()`` always returns ``None``.
    """

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def get_latest_data(self) -> FerryboxData | None:
        return None

    async def send_result(self, result: IUDPPayload) -> None:
        pass
