from __future__ import annotations

from typing import Protocol

from .models import CurrentMeasurement


class MeasurementTransport(Protocol):
    """Request/response transport used by a measurement device adapter."""

    def request(self, command: bytes) -> bytes:
        """Send one command and return one unframed response payload."""

        ...


class Ammeter(Protocol):
    """Unified domain contract implemented by every ammeter driver."""

    @property
    def name(self) -> str:
        ...

    def read_current(self) -> CurrentMeasurement:
        ...
