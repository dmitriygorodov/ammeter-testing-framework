from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timezone

from .constants import MAX_FRAME_BYTES
from .contracts import MeasurementTransport
from .errors import AmmeterProtocolError
from .models import CurrentMeasurement


WallClock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


class SocketAmmeter:
    """Transport-independent ammeter adapter for the emulator protocol."""

    def __init__(
        self,
        name: str,
        command: bytes,
        transport: MeasurementTransport,
        *,
        wall_clock: WallClock | None = None,
        monotonic_clock: MonotonicClock | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if name != name.strip():
            raise ValueError("name must not have surrounding whitespace")
        if not isinstance(command, bytes) or not command:
            raise ValueError("command must be non-empty bytes")
        if b"\r" in command or b"\n" in command:
            raise ValueError("command must not contain line delimiters")
        if len(command) > MAX_FRAME_BYTES:
            raise ValueError(f"command must not exceed {MAX_FRAME_BYTES} bytes")
        if not callable(getattr(transport, "request", None)):
            raise TypeError("transport must implement MeasurementTransport")

        self._name = name
        self._command = command
        self._transport = transport
        self._wall_clock = (
            wall_clock
            if wall_clock is not None
            else lambda: datetime.now(timezone.utc)
        )
        self._monotonic_clock = (
            monotonic_clock if monotonic_clock is not None else time.monotonic
        )

    @property
    def name(self) -> str:
        return self._name

    def read_current(self) -> CurrentMeasurement:
        started_at = self._monotonic_clock()
        payload = self._transport.request(self._command)
        completed_at = self._monotonic_clock()
        current_a = self._parse_current(payload)
        return CurrentMeasurement(
            ammeter_name=self.name,
            current_a=current_a,
            measured_at_utc=self._wall_clock(),
            monotonic_time_s=completed_at,
            latency_seconds=completed_at - started_at,
        )

    @staticmethod
    def _parse_current(payload: bytes) -> float:
        if not isinstance(payload, bytes):
            raise AmmeterProtocolError("Ammeter response payload must be bytes")
        if not payload:
            raise AmmeterProtocolError("Ammeter returned an empty response")
        if b"\r" in payload or b"\n" in payload:
            raise AmmeterProtocolError("Ammeter response contains a frame delimiter")
        try:
            response = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AmmeterProtocolError("Ammeter response is not valid UTF-8") from exc
        if response.startswith("ERROR "):
            raise AmmeterProtocolError(response.removeprefix("ERROR "))
        try:
            current_a = float(response)
        except ValueError as exc:
            raise AmmeterProtocolError(
                f"Ammeter returned a non-numeric measurement: {response!r}"
            ) from exc
        if not math.isfinite(current_a):
            raise AmmeterProtocolError("Ammeter returned a non-finite measurement")
        return current_a
