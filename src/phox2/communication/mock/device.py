"""
Standalone mock Ferrybox device for integration testing and manual smoke tests.

``MockFerryboxDevice`` is a self-contained async UDP server that acts as the
*other end* of the communication channel — i.e. it simulates the physical
Ferrybox system.

Behaviour
---------
* Binds on *device_port* to receive result datagrams from the instrument.
* Every *send_interval_s* seconds, transmits a synthetic ``ferrybox_data``
  JSON packet to (*instrument_host*, *instrument_port*).
* Stores all received result packets in ``received_results: list[dict]``.

Running as a standalone process
--------------------------------
::

    python -m phox2.communication.mock.device

Command-line flags::

    --device-port     UDP port this device listens on (default: 5556)
    --instrument-host Instrument IP/hostname        (default: 127.0.0.1)
    --instrument-port UDP port the instrument listens on (default: 5555)
    --salinity        Salinity value broadcast       (default: 35.0)
    --temperature     Sea temperature broadcast      (default: 18.5)
    --interval        Broadcast interval in seconds  (default: 5.0)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class _DeviceProtocol(asyncio.DatagramProtocol):
    """Internal protocol that receives instrument result datagrams."""

    def __init__(self, device: "MockFerryboxDevice") -> None:
        self._device = device

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            payload = json.loads(data.decode("utf-8").strip())
            self._device.received_results.append(payload)
            logger.info(
                "MockFerryboxDevice: received %r from %s",
                payload.get("type", "unknown"),
                addr,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("MockFerryboxDevice: malformed datagram from %s: %s", addr, exc)

    def error_received(self, exc: Exception) -> None:
        logger.error("MockFerryboxDevice UDP error: %s", exc)


class MockFerryboxDevice:
    """
    Async UDP server that simulates the Ferrybox side of the communication.

    Parameters
    ----------
    device_port:
        Local port this device binds to (for receiving instrument results).
    instrument_host:
        Hostname/IP of the instrument to send synthetic Ferrybox data to.
    instrument_port:
        UDP port the instrument listens on.
    salinity:
        Salinity value included in each broadcast packet.
    temperature:
        Temperature value included in each broadcast packet.
    send_interval_s:
        How often (seconds) to broadcast a synthetic Ferrybox data packet.

    Attributes
    ----------
    received_results : list[dict]
        All result datagrams received from the instrument, parsed into dicts.
    """

    def __init__(
        self,
        device_port: int = 5556,
        instrument_host: str = "127.0.0.1",
        instrument_port: int = 5555,
        salinity: float = 35.0,
        temperature: float = 18.5,
        send_interval_s: float = 5.0,
    ) -> None:
        self._device_port = device_port
        self._instrument_host = instrument_host
        self._instrument_port = instrument_port
        self._salinity = salinity
        self._temperature = temperature
        self._send_interval_s = send_interval_s

        self._transport: asyncio.DatagramTransport | None = None
        self._sender_task: asyncio.Task | None = None
        self.received_results: list[dict] = []

    async def start(self) -> None:
        """Bind the socket and begin broadcasting synthetic Ferrybox data."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DeviceProtocol(self),
            local_addr=("0.0.0.0", self._device_port),
        )
        self._transport = transport  # type: ignore[assignment]
        self._sender_task = asyncio.create_task(self._broadcast_loop())
        logger.info(
            "MockFerryboxDevice started — listening on :%d, broadcasting to %s:%d every %.1f s",
            self._device_port,
            self._instrument_host,
            self._instrument_port,
            self._send_interval_s,
        )

    async def stop(self) -> None:
        """Cancel the broadcast loop and close the socket."""
        if self._sender_task is not None:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass
            self._sender_task = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        logger.info("MockFerryboxDevice stopped")

    async def _broadcast_loop(self) -> None:
        while True:
            await asyncio.sleep(self._send_interval_s)
            self._send_ferrybox_data()

    def _send_ferrybox_data(self) -> None:
        if self._transport is None:
            return
        payload = {
            "type": "ferrybox_data",
            "salinity": self._salinity,
            "temperature": self._temperature,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        }
        data = (json.dumps(payload) + "\n").encode("utf-8")
        self._transport.sendto(data, (self._instrument_host, self._instrument_port))
        logger.debug(
            "MockFerryboxDevice: sent ferrybox_data S=%.3f T=%.2f to %s:%d",
            self._salinity,
            self._temperature,
            self._instrument_host,
            self._instrument_port,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    device = MockFerryboxDevice(
        device_port=args.device_port,
        instrument_host=args.instrument_host,
        instrument_port=args.instrument_port,
        salinity=args.salinity,
        temperature=args.temperature,
        send_interval_s=args.interval,
    )
    await device.start()
    print(
        f"MockFerryboxDevice running — press Ctrl+C to stop.\n"
        f"  Listening on        :{args.device_port}\n"
        f"  Sending to          {args.instrument_host}:{args.instrument_port}\n"
        f"  Broadcast interval  {args.interval} s\n"
        f"  Salinity            {args.salinity} PSU\n"
        f"  Temperature         {args.temperature} °C"
    )
    try:
        await asyncio.Event().wait()  # run until Ctrl+C
    except asyncio.CancelledError:
        pass
    finally:
        await device.stop()
        print(f"\nReceived {len(device.received_results)} result packet(s) from the instrument.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock Ferrybox UDP device")
    parser.add_argument("--device-port", type=int, default=5556)
    parser.add_argument("--instrument-host", default="127.0.0.1")
    parser.add_argument("--instrument-port", type=int, default=5555)
    parser.add_argument("--salinity", type=float, default=35.0)
    parser.add_argument("--temperature", type=float, default=18.5)
    parser.add_argument("--interval", type=float, default=5.0)
    asyncio.run(_main(parser.parse_args()))
