"""Immutable sampling plans and timing-rich test-run records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, ClassVar

from src.devices.models import CurrentMeasurement

from .errors import SamplingConfigurationError


class SamplingStopReason(str, Enum):
    """The bound that stopped a successful sampling run."""

    COUNT_REACHED = "count_reached"
    DURATION_REACHED = "duration_reached"


@dataclass(frozen=True, slots=True, kw_only=True)
class SamplingPlan:
    """Fixed-rate sampling cadence with one or two independent stop bounds.

    The frequency defines start-to-start cadence. ``measurements_count`` and
    ``total_duration_seconds`` are independent caps; when both are present, the
    first cap reached stops the run.
    """

    sampling_frequency_hz: float
    measurements_count: int | None = None
    total_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        normalized_frequency = _require_positive_finite_number(
            self.sampling_frequency_hz,
            "sampling_frequency_hz",
        )
        object.__setattr__(
            self,
            "sampling_frequency_hz",
            normalized_frequency,
        )
        if not math.isfinite(1.0 / self.sampling_frequency_hz):
            raise SamplingConfigurationError(
                "sampling_frequency_hz is too small to produce a finite period"
            )

        if self.measurements_count is not None:
            if (
                isinstance(self.measurements_count, bool)
                or not isinstance(self.measurements_count, int)
                or self.measurements_count <= 0
            ):
                raise SamplingConfigurationError(
                    "measurements_count must be a positive integer"
                )

        if self.total_duration_seconds is not None:
            normalized_duration = _require_positive_finite_number(
                self.total_duration_seconds,
                "total_duration_seconds",
            )
            object.__setattr__(
                self,
                "total_duration_seconds",
                normalized_duration,
            )

        if (
            self.measurements_count is None
            and self.total_duration_seconds is None
        ):
            raise SamplingConfigurationError(
                "A sampling plan requires measurements_count, "
                "total_duration_seconds, or both"
            )

    @property
    def period_seconds(self) -> float:
        return 1.0 / self.sampling_frequency_hz

    @property
    def maximum_scheduled_samples(self) -> int:
        """Return the grid-point limit before acquisition overruns are known."""

        limits: list[int] = []
        if self.measurements_count is not None:
            limits.append(self.measurements_count)
        if self.total_duration_seconds is not None:
            grid_points = self.total_duration_seconds * self.sampling_frequency_hz
            if not math.isfinite(grid_points):
                raise SamplingConfigurationError(
                    "total_duration_seconds * sampling_frequency_hz is too large"
                )
            duration_limit = math.ceil(grid_points)
            limits.append(max(1, duration_limit))
        return min(limits)

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "sampling_frequency_hz": self.sampling_frequency_hz,
            "measurements_count": self.measurements_count,
            "total_duration_seconds": self.total_duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class SampledMeasurement:
    """One measurement plus its scheduled and observed run-relative timing."""

    sample_index: int
    scheduled_offset_seconds: float
    started_offset_seconds: float
    completed_offset_seconds: float
    measurement: CurrentMeasurement

    def __post_init__(self) -> None:
        if (
            isinstance(self.sample_index, bool)
            or not isinstance(self.sample_index, int)
            or self.sample_index < 0
        ):
            raise ValueError("sample_index must be a nonnegative integer")
        for field_name in (
            "scheduled_offset_seconds",
            "started_offset_seconds",
            "completed_offset_seconds",
        ):
            value = getattr(self, field_name)
            normalized_value = _require_nonnegative_finite_number(
                value,
                field_name,
            )
            object.__setattr__(self, field_name, normalized_value)
        if self.completed_offset_seconds < self.started_offset_seconds:
            raise ValueError(
                "completed_offset_seconds must not precede started_offset_seconds"
            )
        if not isinstance(self.measurement, CurrentMeasurement):
            raise TypeError("measurement must be a CurrentMeasurement")

    @property
    def start_lateness_seconds(self) -> float:
        return max(
            0.0,
            self.started_offset_seconds - self.scheduled_offset_seconds,
        )

    @property
    def acquisition_duration_seconds(self) -> float:
        return self.completed_offset_seconds - self.started_offset_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_index": self.sample_index,
            "scheduled_offset_seconds": self.scheduled_offset_seconds,
            "started_offset_seconds": self.started_offset_seconds,
            "completed_offset_seconds": self.completed_offset_seconds,
            "start_lateness_seconds": self.start_lateness_seconds,
            "acquisition_duration_seconds": self.acquisition_duration_seconds,
            "measurement": self.measurement.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SamplingRunResult:
    """Complete evidence returned by one successful sampling run."""

    ammeter_name: str
    plan: SamplingPlan
    samples: tuple[SampledMeasurement, ...]
    started_at_utc: datetime
    completed_at_utc: datetime
    started_monotonic_s: float
    completed_monotonic_s: float
    stop_reason: SamplingStopReason

    def __post_init__(self) -> None:
        if not isinstance(self.ammeter_name, str) or not self.ammeter_name.strip():
            raise ValueError("ammeter_name must be a non-empty string")
        if self.ammeter_name != self.ammeter_name.strip():
            raise ValueError("ammeter_name must not have surrounding whitespace")
        if not isinstance(self.plan, SamplingPlan):
            raise TypeError("plan must be a SamplingPlan")
        if not isinstance(self.samples, tuple):
            raise TypeError("samples must be a tuple")
        for expected_index, sample in enumerate(self.samples):
            if not isinstance(sample, SampledMeasurement):
                raise TypeError("samples must contain SampledMeasurement records")
            if sample.sample_index != expected_index:
                raise ValueError("sample indexes must be contiguous and zero-based")
        _require_utc_datetime(self.started_at_utc, "started_at_utc")
        _require_utc_datetime(self.completed_at_utc, "completed_at_utc")
        normalized_start = _require_nonnegative_finite_number(
            self.started_monotonic_s,
            "started_monotonic_s",
        )
        normalized_completion = _require_nonnegative_finite_number(
            self.completed_monotonic_s,
            "completed_monotonic_s",
        )
        object.__setattr__(
            self,
            "started_monotonic_s",
            normalized_start,
        )
        object.__setattr__(
            self,
            "completed_monotonic_s",
            normalized_completion,
        )
        if self.completed_monotonic_s < self.started_monotonic_s:
            raise ValueError(
                "completed_monotonic_s must not precede started_monotonic_s"
            )
        if not isinstance(self.stop_reason, SamplingStopReason):
            raise TypeError("stop_reason must be a SamplingStopReason")
        if (
            self.stop_reason is SamplingStopReason.COUNT_REACHED
            and (
                self.plan.measurements_count is None
                or len(self.samples) != self.plan.measurements_count
            )
        ):
            raise ValueError(
                "COUNT_REACHED requires the configured measurement count"
            )
        if (
            self.stop_reason is SamplingStopReason.DURATION_REACHED
            and self.plan.total_duration_seconds is None
        ):
            raise ValueError(
                "DURATION_REACHED requires total_duration_seconds"
            )

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def measurements(self) -> tuple[CurrentMeasurement, ...]:
        return tuple(sample.measurement for sample in self.samples)

    @property
    def elapsed_seconds(self) -> float:
        return self.completed_monotonic_s - self.started_monotonic_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "ammeter_name": self.ammeter_name,
            "plan": self.plan.to_dict(),
            "sample_count": self.sample_count,
            "stop_reason": self.stop_reason.value,
            "started_at_utc": _datetime_to_json(self.started_at_utc),
            "completed_at_utc": _datetime_to_json(self.completed_at_utc),
            "started_monotonic_s": self.started_monotonic_s,
            "completed_monotonic_s": self.completed_monotonic_s,
            "elapsed_seconds": self.elapsed_seconds,
            "samples": [sample.to_dict() for sample in self.samples],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentStatistics:
    """Full-precision current statistics for one completed sampling run."""

    ammeter_name: str
    sample_count: int
    mean_current_a: float
    median_current_a: float
    standard_deviation_current_a: float
    minimum_current_a: float
    maximum_current_a: float

    unit: ClassVar[str] = "A"

    def __post_init__(self) -> None:
        if not isinstance(self.ammeter_name, str) or not self.ammeter_name.strip():
            raise ValueError("ammeter_name must be a non-empty string")
        if self.ammeter_name != self.ammeter_name.strip():
            raise ValueError("ammeter_name must not have surrounding whitespace")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count <= 0
        ):
            raise ValueError("sample_count must be a positive integer")

        for field_name in (
            "mean_current_a",
            "median_current_a",
            "standard_deviation_current_a",
            "minimum_current_a",
            "maximum_current_a",
        ):
            normalized_value = _require_finite_statistic(
                getattr(self, field_name),
                field_name,
            )
            object.__setattr__(self, field_name, normalized_value)

        if self.standard_deviation_current_a < 0:
            raise ValueError(
                "standard_deviation_current_a must be nonnegative"
            )
        if self.minimum_current_a > self.maximum_current_a:
            raise ValueError(
                "minimum_current_a must not exceed maximum_current_a"
            )
        if not (
            self.minimum_current_a
            <= self.mean_current_a
            <= self.maximum_current_a
        ):
            raise ValueError("mean_current_a must be within the observed range")
        if not (
            self.minimum_current_a
            <= self.median_current_a
            <= self.maximum_current_a
        ):
            raise ValueError("median_current_a must be within the observed range")

    def to_dict(self) -> dict[str, int | float | str]:
        """Return a stable JSON-ready representation with explicit units."""

        return {
            "ammeter_name": self.ammeter_name,
            "sample_count": self.sample_count,
            "unit": self.unit,
            "mean_current_a": self.mean_current_a,
            "median_current_a": self.median_current_a,
            "standard_deviation_current_a": (
                self.standard_deviation_current_a
            ),
            "minimum_current_a": self.minimum_current_a,
            "maximum_current_a": self.maximum_current_a,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyzedSamplingResult:
    """Original sampling evidence paired with its statistical summary."""

    sampling_result: SamplingRunResult
    statistics: CurrentStatistics

    def __post_init__(self) -> None:
        if not isinstance(self.sampling_result, SamplingRunResult):
            raise TypeError("sampling_result must be a SamplingRunResult")
        if not isinstance(self.statistics, CurrentStatistics):
            raise TypeError("statistics must be CurrentStatistics")
        if self.statistics.ammeter_name != self.sampling_result.ammeter_name:
            raise ValueError(
                "statistics and sampling_result must identify the same ammeter"
            )
        if self.statistics.sample_count != self.sampling_result.sample_count:
            raise ValueError(
                "statistics sample_count must match the sampling result"
            )

    @property
    def ammeter_name(self) -> str:
        return self.sampling_result.ammeter_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "ammeter_name": self.ammeter_name,
            "sampling_result": self.sampling_result.to_dict(),
            "statistics": self.statistics.to_dict(),
        }


def _require_positive_finite_number(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise SamplingConfigurationError(
            f"{field_name} must be a positive finite number"
        )
    try:
        normalized_value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise SamplingConfigurationError(
            f"{field_name} must be a positive finite number"
        ) from exc
    if not math.isfinite(normalized_value) or normalized_value <= 0:
        raise SamplingConfigurationError(
            f"{field_name} must be a positive finite number"
        )
    return normalized_value


def _require_nonnegative_finite_number(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise ValueError(f"{field_name} must be a nonnegative finite number")
    try:
        normalized_value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a nonnegative finite number"
        ) from exc
    if not math.isfinite(normalized_value) or normalized_value < 0:
        raise ValueError(f"{field_name} must be a nonnegative finite number")
    return normalized_value


def _require_finite_statistic(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        normalized_value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(normalized_value):
        raise ValueError(f"{field_name} must be a finite number")
    return normalized_value


def _require_utc_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _datetime_to_json(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
