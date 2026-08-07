from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class CurrentMeasurement:
    """One immutable, consistently reported current measurement."""

    ammeter_name: str
    current_a: float
    measured_at_utc: datetime
    monotonic_time_s: float
    latency_seconds: float

    unit: ClassVar[str] = "A"

    def __post_init__(self) -> None:
        if not isinstance(self.ammeter_name, str) or not self.ammeter_name.strip():
            raise ValueError("ammeter_name must be a non-empty string")
        if self.ammeter_name != self.ammeter_name.strip():
            raise ValueError("ammeter_name must not have surrounding whitespace")
        _require_finite_number(self.current_a, "current_a")
        _require_finite_number(self.monotonic_time_s, "monotonic_time_s")
        _require_finite_number(self.latency_seconds, "latency_seconds")
        if self.monotonic_time_s < 0:
            raise ValueError("monotonic_time_s must be nonnegative")
        if self.latency_seconds < 0:
            raise ValueError("latency_seconds must be nonnegative")
        if not isinstance(self.measured_at_utc, datetime):
            raise TypeError("measured_at_utc must be a datetime")
        if (
            self.measured_at_utc.tzinfo is None
            or self.measured_at_utc.utcoffset() != timedelta(0)
        ):
            raise ValueError("measured_at_utc must be timezone-aware UTC")

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready representation."""

        timestamp = (
            self.measured_at_utc.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return {
            "ammeter_name": self.ammeter_name,
            "current_a": self.current_a,
            "unit": self.unit,
            "measured_at_utc": timestamp,
            "monotonic_time_s": self.monotonic_time_s,
            "latency_seconds": self.latency_seconds,
        }


def _require_finite_number(value: float, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field_name} must be a finite number")
