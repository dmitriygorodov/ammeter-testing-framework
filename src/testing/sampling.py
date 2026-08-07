"""Drift-resistant, synchronous measurement scheduling."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timezone

from src.devices.contracts import Ammeter

from .models import (
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


MonotonicClock = Callable[[], float]
WallClock = Callable[[], datetime]
Sleeper = Callable[[float], None]


class SamplingRunner:
    """Collect measurements on absolute monotonic deadlines without drift."""

    def __init__(
        self,
        *,
        monotonic_clock: MonotonicClock | None = None,
        wall_clock: WallClock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._monotonic_clock = (
            monotonic_clock if monotonic_clock is not None else time.monotonic
        )
        self._wall_clock = (
            wall_clock
            if wall_clock is not None
            else lambda: datetime.now(timezone.utc)
        )
        self._sleeper = sleeper if sleeper is not None else time.sleep
        for dependency, name in (
            (self._monotonic_clock, "monotonic_clock"),
            (self._wall_clock, "wall_clock"),
            (self._sleeper, "sleeper"),
        ):
            if not callable(dependency):
                raise TypeError(f"{name} must be callable")

    def run(self, ammeter: Ammeter, plan: SamplingPlan) -> SamplingRunResult:
        """Run one synchronous sampling plan and return immutable timing evidence."""

        if not callable(getattr(ammeter, "read_current", None)):
            raise TypeError("ammeter must implement the Ammeter protocol")
        ammeter_name = getattr(ammeter, "name", None)
        if not isinstance(ammeter_name, str) or not ammeter_name.strip():
            raise TypeError("ammeter.name must be a non-empty string")
        if ammeter_name != ammeter_name.strip():
            raise TypeError("ammeter.name must not have surrounding whitespace")
        if not isinstance(plan, SamplingPlan):
            raise TypeError("plan must be a SamplingPlan")

        started_at_utc = self._wall_clock()
        started_monotonic_s = self._read_monotonic()
        duration_deadline = (
            started_monotonic_s + plan.total_duration_seconds
            if plan.total_duration_seconds is not None
            else None
        )
        samples: list[SampledMeasurement] = []
        stop_reason = SamplingStopReason.DURATION_REACHED

        for sample_index in range(plan.maximum_scheduled_samples):
            scheduled_offset_seconds = sample_index * plan.period_seconds
            scheduled_time = started_monotonic_s + scheduled_offset_seconds
            sample_started_s = self._wait_until(scheduled_time)

            # The first sample is always immediate. Later starts use a half-open
            # duration window; a request already in flight is never discarded.
            if (
                sample_index > 0
                and duration_deadline is not None
                and sample_started_s >= duration_deadline
            ):
                stop_reason = SamplingStopReason.DURATION_REACHED
                break

            measurement = ammeter.read_current()
            sample_completed_s = self._read_monotonic()
            samples.append(
                SampledMeasurement(
                    sample_index=sample_index,
                    scheduled_offset_seconds=scheduled_offset_seconds,
                    started_offset_seconds=(
                        sample_started_s - started_monotonic_s
                    ),
                    completed_offset_seconds=(
                        sample_completed_s - started_monotonic_s
                    ),
                    measurement=measurement,
                )
            )

            if (
                duration_deadline is not None
                and sample_completed_s >= duration_deadline
            ):
                stop_reason = SamplingStopReason.DURATION_REACHED
                break
            if (
                plan.measurements_count is not None
                and len(samples) == plan.measurements_count
            ):
                stop_reason = SamplingStopReason.COUNT_REACHED
                break
        else:
            if (
                plan.measurements_count is not None
                and len(samples) == plan.measurements_count
            ):
                stop_reason = SamplingStopReason.COUNT_REACHED
            else:
                stop_reason = SamplingStopReason.DURATION_REACHED

        completed_monotonic_s = self._read_monotonic()
        completed_at_utc = self._wall_clock()
        return SamplingRunResult(
            ammeter_name=ammeter_name,
            plan=plan,
            samples=tuple(samples),
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            started_monotonic_s=started_monotonic_s,
            completed_monotonic_s=completed_monotonic_s,
            stop_reason=stop_reason,
        )

    def _wait_until(self, deadline: float) -> float:
        while True:
            current_time = self._read_monotonic()
            remaining_seconds = deadline - current_time
            if remaining_seconds <= 0:
                return current_time
            self._sleeper(remaining_seconds)

    def _read_monotonic(self) -> float:
        value = self._monotonic_clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise RuntimeError(
                "monotonic_clock must return a nonnegative finite number"
            )
        return float(value)
