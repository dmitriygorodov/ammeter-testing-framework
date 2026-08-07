"""Deterministic, hardware-free evidence builders for Phase 6 tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.devices.models import CurrentMeasurement
from src.testing.analysis import ResultAnalyzer
from src.testing.archive_models import ArchivedTestResult, RunMetadata
from src.testing.models import (
    AnalyzedSamplingResult,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


BASE_UTC = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def analyzed_result(
    values: tuple[float, ...],
    *,
    ammeter_name: str,
    sampling_frequency_hz: float = 10.0,
    total_duration_seconds: float | None = None,
    stop_reason: SamplingStopReason = SamplingStopReason.COUNT_REACHED,
    acquisition_duration_seconds: float = 0.01,
    plan_override: SamplingPlan | None = None,
    completion_offsets: tuple[float, ...] | None = None,
) -> AnalyzedSamplingResult:
    """Build coherent raw evidence and its independently calculated summary."""

    if not values:
        raise ValueError("Phase 6 fixtures require at least one sample")
    plan = (
        plan_override
        if plan_override is not None
        else SamplingPlan(
            sampling_frequency_hz=sampling_frequency_hz,
            measurements_count=len(values),
            total_duration_seconds=total_duration_seconds,
        )
    )
    if completion_offsets is not None and len(completion_offsets) != len(values):
        raise ValueError("completion_offsets must match the evidence length")
    period_seconds = plan.period_seconds
    samples = tuple(
        SampledMeasurement(
            sample_index=index,
            scheduled_offset_seconds=index * period_seconds,
            started_offset_seconds=index * period_seconds,
            completed_offset_seconds=(
                completion_offsets[index]
                if completion_offsets is not None
                else index * period_seconds + acquisition_duration_seconds
            ),
            measurement=CurrentMeasurement(
                ammeter_name=ammeter_name,
                current_a=value,
                measured_at_utc=(
                    BASE_UTC
                    + timedelta(
                        seconds=(
                            completion_offsets[index]
                            if completion_offsets is not None
                            else index * period_seconds
                            + acquisition_duration_seconds
                        )
                    )
                ),
                monotonic_time_s=(
                    100.0
                    + (
                        completion_offsets[index]
                        if completion_offsets is not None
                        else index * period_seconds
                        + acquisition_duration_seconds
                    )
                ),
                latency_seconds=(
                    completion_offsets[index] - index * period_seconds
                    if completion_offsets is not None
                    else acquisition_duration_seconds
                ),
            ),
        )
        for index, value in enumerate(values)
    )
    elapsed_seconds = samples[-1].completed_offset_seconds
    run = SamplingRunResult(
        ammeter_name=ammeter_name,
        plan=plan,
        samples=samples,
        started_at_utc=BASE_UTC,
        completed_at_utc=BASE_UTC + timedelta(seconds=elapsed_seconds),
        started_monotonic_s=100.0,
        completed_monotonic_s=100.0 + elapsed_seconds,
        stop_reason=stop_reason,
    )
    return AnalyzedSamplingResult(
        sampling_result=run,
        statistics=ResultAnalyzer().analyze(run),
    )


def archived_result(
    values: tuple[float, ...],
    *,
    ammeter_name: str,
    run_number: int,
    comparison_group: str | None = "bench-2026-08-06",
    test_name: str = "reference_accuracy",
    dut_id: str | None = "dut-42",
    station_id: str | None = "station-a",
    sampling_frequency_hz: float = 10.0,
    total_duration_seconds: float | None = None,
    stop_reason: SamplingStopReason = SamplingStopReason.COUNT_REACHED,
    acquisition_duration_seconds: float = 0.01,
    analyzed_override: AnalyzedSamplingResult | None = None,
) -> ArchivedTestResult:
    """Wrap coherent evidence in a typed archive record without filesystem I/O."""

    analyzed = (
        analyzed_override
        if analyzed_override is not None
        else analyzed_result(
            values,
            ammeter_name=ammeter_name,
            sampling_frequency_hz=sampling_frequency_hz,
            total_duration_seconds=total_duration_seconds,
            stop_reason=stop_reason,
            acquisition_duration_seconds=acquisition_duration_seconds,
        )
    )
    attributes = (
        ()
        if comparison_group is None
        else (("comparison_group", comparison_group),)
    )
    return ArchivedTestResult(
        run_id=str(UUID(int=run_number)),
        archived_at_utc=BASE_UTC + timedelta(seconds=run_number),
        metadata=RunMetadata(
            test_name=test_name,
            dut_id=dut_id,
            station_id=station_id,
            attributes=attributes,
        ),
        analyzed_result=analyzed,
        content_sha256="0" * 64,
    )


def representative_cohort() -> tuple[ArchivedTestResult, ...]:
    """Return three compatible runs with distinct/tied metric outcomes."""

    return (
        archived_result(
            (9.0, 11.0),
            ammeter_name="alpha",
            run_number=1,
        ),
        archived_result(
            (10.5, 10.5),
            ammeter_name="bravo",
            run_number=2,
        ),
        archived_result(
            (9.0, 9.0),
            ammeter_name="charlie",
            run_number=3,
        ),
    )
