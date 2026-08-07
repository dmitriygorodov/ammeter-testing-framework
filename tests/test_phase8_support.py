"""Deterministic archived history builders for Phase 8 tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.testing.archive_models import ArchivedTestResult, RunMetadata

from tests.test_phase5_support import analyzed_result


BASE_UTC = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


def historical_run(
    values: tuple[float, ...],
    *,
    run_number: int,
    elapsed_hours: float,
    ammeter_name: str = "greenlee",
    consistency_group: str | None = "bench-stability-2026",
    test_name: str = "long_term_stability",
    dut_id: str | None = "dut-42",
    station_id: str | None = "station-a",
    sampling_frequency_hz: float = 10.0,
) -> ArchivedTestResult:
    analyzed = analyzed_result(
        values,
        ammeter_name=ammeter_name,
        started_at_utc=BASE_UTC + timedelta(hours=elapsed_hours),
        sampling_frequency_hz=sampling_frequency_hz,
    )
    completed = analyzed.sampling_result.completed_at_utc
    attributes = (
        ()
        if consistency_group is None
        else (("consistency_group", consistency_group),)
    )
    return ArchivedTestResult(
        run_id=str(UUID(int=run_number)),
        archived_at_utc=completed + timedelta(seconds=1),
        metadata=RunMetadata(
            test_name=test_name,
            dut_id=dut_id,
            station_id=station_id,
            attributes=attributes,
        ),
        analyzed_result=analyzed,
        content_sha256="0" * 64,
    )


def representative_history() -> tuple[ArchivedTestResult, ...]:
    return (
        historical_run((9.0, 11.0), run_number=101, elapsed_hours=0.0),
        historical_run((10.0, 12.0), run_number=102, elapsed_hours=1.0),
        historical_run((11.0, 13.0), run_number=103, elapsed_hours=2.0),
    )
