"""Shared deterministic evidence builders for the Phase 5 tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.devices.models import CurrentMeasurement
from src.testing.analysis import ResultAnalyzer
from src.testing.models import (
    AnalyzedSamplingResult,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


BASE_UTC = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def analyzed_result(
    values: tuple[float, ...] = (1.0, 2.0, 3.0),
    *,
    ammeter_name: str = "greenlee",
    started_at_utc: datetime = BASE_UTC,
    sampling_frequency_hz: float = 10.0,
) -> AnalyzedSamplingResult:
    """Build coherent raw and analyzed evidence without device access."""

    if not values:
        raise ValueError("Phase 5 archive fixtures require at least one value")
    plan = SamplingPlan(
        sampling_frequency_hz=sampling_frequency_hz,
        measurements_count=len(values),
    )
    period_seconds = plan.period_seconds
    samples = tuple(
        SampledMeasurement(
            sample_index=index,
            scheduled_offset_seconds=index * period_seconds,
            started_offset_seconds=index * period_seconds,
            completed_offset_seconds=index * period_seconds + 0.01,
            measurement=CurrentMeasurement(
                ammeter_name=ammeter_name,
                current_a=value,
                measured_at_utc=(
                    started_at_utc
                    + timedelta(seconds=index * period_seconds + 0.01)
                ),
                monotonic_time_s=100.0 + index * period_seconds + 0.01,
                latency_seconds=0.01,
            ),
        )
        for index, value in enumerate(values)
    )
    elapsed_seconds = samples[-1].completed_offset_seconds
    sampling_result = SamplingRunResult(
        ammeter_name=ammeter_name,
        plan=plan,
        samples=samples,
        started_at_utc=started_at_utc,
        completed_at_utc=started_at_utc + timedelta(seconds=elapsed_seconds),
        started_monotonic_s=100.0,
        completed_monotonic_s=100.0 + elapsed_seconds,
        stop_reason=SamplingStopReason.COUNT_REACHED,
    )
    return AnalyzedSamplingResult(
        sampling_result=sampling_result,
        statistics=ResultAnalyzer().analyze(sampling_result),
    )
