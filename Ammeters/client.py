"""Backward-compatible one-shot client built on the unified device layer."""

from __future__ import annotations

from src.devices.ammeter import SocketAmmeter
from src.devices.errors import (
    AmmeterClientError,
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
)
from src.devices.socket_transport import (
    DEFAULT_HOST,
    DEFAULT_TIMEOUT_SECONDS,
    SocketTransport,
)


def request_current_from_ammeter(
    port: int,
    command: bytes,
    host: str = DEFAULT_HOST,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> float:
    """Request one current measurement and return its value in amperes.

    New framework code uses ``SocketAmmeter.read_current()`` and receives a
    typed ``CurrentMeasurement``. This wrapper preserves the starter's function
    signature for existing callers and Phase 1 compatibility.
    """

    transport = SocketTransport(
        host=host,
        port=port,
        timeout_seconds=timeout,
    )
    ammeter = SocketAmmeter(
        name=f"{transport.host}:{transport.port}",
        command=command,
        transport=transport,
    )
    return ammeter.read_current().current_a


__all__ = [
    "AmmeterClientError",
    "AmmeterConnectionError",
    "AmmeterProtocolError",
    "AmmeterTimeoutError",
    "request_current_from_ammeter",
]
