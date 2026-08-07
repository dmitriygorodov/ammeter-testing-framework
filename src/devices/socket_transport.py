from __future__ import annotations

import math
import socket
from dataclasses import dataclass

from .constants import MAX_FRAME_BYTES
from .errors import (
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class SocketTransport:
    """One-request-per-connection, LF-framed IPv4 TCP transport."""

    host: str
    port: int
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_frame_bytes: int = MAX_FRAME_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must be a non-empty string")
        if self.host != self.host.strip():
            object.__setattr__(self, "host", self.host.strip())
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65_535
        ):
            raise ValueError("port must be an integer between 1 and 65535")
        _validate_positive_finite(self.timeout_seconds, "timeout_seconds")
        if (
            isinstance(self.max_frame_bytes, bool)
            or not isinstance(self.max_frame_bytes, int)
            or self.max_frame_bytes <= 0
        ):
            raise ValueError("max_frame_bytes must be a positive integer")

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    def request(self, command: bytes) -> bytes:
        self._validate_command(command)
        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout_seconds,
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(command + b"\n")
                return self._receive_frame(connection)
        except socket.timeout as exc:
            raise AmmeterTimeoutError(
                f"Timed out communicating with ammeter at {self.endpoint}"
            ) from exc
        except OSError as exc:
            raise AmmeterConnectionError(
                f"Could not communicate with ammeter at {self.endpoint}: {exc}"
            ) from exc

    def _validate_command(self, command: bytes) -> None:
        if not isinstance(command, bytes) or not command:
            raise ValueError("command must be non-empty bytes")
        if b"\r" in command or b"\n" in command:
            raise ValueError("command must not contain line delimiters")
        if len(command) > self.max_frame_bytes:
            raise ValueError(
                f"command must not exceed {self.max_frame_bytes} encoded bytes"
            )

    def _receive_frame(self, connection: socket.socket) -> bytes:
        buffer = bytearray()
        while True:
            chunk = connection.recv(
                min(256, self.max_frame_bytes + 1 - len(buffer))
            )
            if not chunk:
                raise AmmeterProtocolError(
                    "Ammeter closed the connection before completing its response"
                )

            newline_index = chunk.find(b"\n")
            if newline_index >= 0:
                buffer.extend(chunk[:newline_index])
                if chunk[newline_index + 1 :]:
                    raise AmmeterProtocolError(
                        "Ammeter sent data after the response delimiter"
                    )
                break

            buffer.extend(chunk)
            if len(buffer) > self.max_frame_bytes:
                raise AmmeterProtocolError(
                    "Ammeter response exceeds maximum frame size"
                )

        if b"\r" in buffer:
            raise AmmeterProtocolError(
                "Ammeter response contains an invalid carriage return"
            )
        return bytes(buffer)


def _validate_positive_finite(value: float, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a positive finite number")
