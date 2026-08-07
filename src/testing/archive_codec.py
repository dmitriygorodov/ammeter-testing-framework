"""Strict schema-v1 JSON codec for archived ammeter test results."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import datetime
from typing import Any, Mapping

from src.devices.models import CurrentMeasurement

from .analysis import ResultAnalyzer
from .archive_models import (
    ArchivedTestResult,
    RunMetadata,
    RunStatus,
)
from .errors import ResultArchiveCorruptionError
from .models import (
    AnalyzedSamplingResult,
    CurrentStatistics,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Encode a JSON mapping deterministically for hashing and persistence."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def calculate_content_sha256(content: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(content)).hexdigest()


def decode_archive_document(
    document: object,
    *,
    expected_run_id: str,
) -> ArchivedTestResult:
    """Restore and semantically validate one complete schema-v1 document."""

    try:
        return _decode_archive_document(
            _require_mapping(document, "archive document"),
            expected_run_id=expected_run_id,
        )
    except ResultArchiveCorruptionError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ResultArchiveCorruptionError(
            "Archive document contains invalid typed evidence"
        ) from exc


def _decode_archive_document(
    document: Mapping[str, Any],
    *,
    expected_run_id: str,
) -> ArchivedTestResult:
    _require_exact_keys(
        document,
        {
            "schema_version",
            "run_id",
            "status",
            "archived_at_utc",
            "metadata",
            "analyzed_result",
            "integrity",
        },
        "archive document",
    )
    schema_version = document["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != ArchivedTestResult.schema_version
    ):
        raise ResultArchiveCorruptionError(
            f"Unsupported archive schema version: {schema_version!r}"
        )

    run_id = document["run_id"]
    if run_id != expected_run_id:
        raise ResultArchiveCorruptionError(
            "Archive filename and document run IDs do not match"
        )

    integrity = _require_mapping(document["integrity"], "integrity")
    _require_exact_keys(
        integrity,
        {"algorithm", "content_sha256"},
        "integrity",
    )
    if integrity["algorithm"] != ArchivedTestResult.integrity_algorithm:
        raise ResultArchiveCorruptionError(
            f"Unsupported integrity algorithm: {integrity['algorithm']!r}"
        )
    stored_digest = integrity["content_sha256"]
    if not isinstance(stored_digest, str):
        raise ResultArchiveCorruptionError(
            "integrity.content_sha256 must be a string"
        )

    content = {
        key: value for key, value in document.items() if key != "integrity"
    }
    try:
        calculated_digest = calculate_content_sha256(content)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResultArchiveCorruptionError(
            "Archive content is not strict JSON"
        ) from exc
    if not hmac.compare_digest(stored_digest, calculated_digest):
        raise ResultArchiveCorruptionError(
            "Archive content SHA-256 verification failed"
        )

    try:
        status = RunStatus(document["status"])
    except (TypeError, ValueError) as exc:
        raise ResultArchiveCorruptionError(
            f"Unsupported archived run status: {document['status']!r}"
        ) from exc

    archived = ArchivedTestResult(
        run_id=run_id,
        archived_at_utc=_parse_utc_datetime(
            document["archived_at_utc"],
            "archived_at_utc",
        ),
        metadata=_decode_metadata(document["metadata"]),
        analyzed_result=_decode_analyzed_result(document["analyzed_result"]),
        content_sha256=stored_digest,
        status=status,
    )
    if not _strict_json_equal(archived.content_dict(), content):
        raise ResultArchiveCorruptionError(
            "Archive content is not the canonical typed representation"
        )

    validate_analyzed_result_semantics(archived.analyzed_result)
    return archived


def _decode_metadata(value: object) -> RunMetadata:
    metadata = _require_mapping(value, "metadata")
    _require_exact_keys(
        metadata,
        {
            "test_name",
            "operator",
            "dut_id",
            "station_id",
            "notes",
            "tags",
            "attributes",
        },
        "metadata",
    )
    tags = metadata["tags"]
    if not isinstance(tags, list):
        raise ResultArchiveCorruptionError("metadata.tags must be a list")
    attributes = _require_mapping(metadata["attributes"], "metadata.attributes")
    return RunMetadata(
        test_name=metadata["test_name"],
        operator=metadata["operator"],
        dut_id=metadata["dut_id"],
        station_id=metadata["station_id"],
        notes=metadata["notes"],
        tags=tuple(tags),
        attributes=tuple(attributes.items()),
    )


def _decode_analyzed_result(value: object) -> AnalyzedSamplingResult:
    analyzed = _require_mapping(value, "analyzed_result")
    _require_exact_keys(
        analyzed,
        {"ammeter_name", "sampling_result", "statistics"},
        "analyzed_result",
    )
    restored = AnalyzedSamplingResult(
        sampling_result=_decode_sampling_result(analyzed["sampling_result"]),
        statistics=_decode_statistics(analyzed["statistics"]),
    )
    _require_round_trip(restored.to_dict(), analyzed, "analyzed_result")
    return restored


def _decode_sampling_result(value: object) -> SamplingRunResult:
    run = _require_mapping(value, "sampling_result")
    _require_exact_keys(
        run,
        {
            "ammeter_name",
            "plan",
            "sample_count",
            "stop_reason",
            "started_at_utc",
            "completed_at_utc",
            "started_monotonic_s",
            "completed_monotonic_s",
            "elapsed_seconds",
            "samples",
        },
        "sampling_result",
    )
    raw_samples = run["samples"]
    if not isinstance(raw_samples, list):
        raise ResultArchiveCorruptionError(
            "sampling_result.samples must be a list"
        )
    try:
        stop_reason = SamplingStopReason(run["stop_reason"])
    except (TypeError, ValueError) as exc:
        raise ResultArchiveCorruptionError(
            f"Invalid sampling stop reason: {run['stop_reason']!r}"
        ) from exc
    restored = SamplingRunResult(
        ammeter_name=run["ammeter_name"],
        plan=_decode_sampling_plan(run["plan"]),
        samples=tuple(_decode_sample(sample) for sample in raw_samples),
        started_at_utc=_parse_utc_datetime(
            run["started_at_utc"],
            "sampling_result.started_at_utc",
        ),
        completed_at_utc=_parse_utc_datetime(
            run["completed_at_utc"],
            "sampling_result.completed_at_utc",
        ),
        started_monotonic_s=run["started_monotonic_s"],
        completed_monotonic_s=run["completed_monotonic_s"],
        stop_reason=stop_reason,
    )
    _require_round_trip(restored.to_dict(), run, "sampling_result")
    validate_sampling_semantics(restored)
    return restored


def _decode_sampling_plan(value: object) -> SamplingPlan:
    plan = _require_mapping(value, "sampling plan")
    _require_exact_keys(
        plan,
        {
            "sampling_frequency_hz",
            "measurements_count",
            "total_duration_seconds",
        },
        "sampling plan",
    )
    restored = SamplingPlan(
        sampling_frequency_hz=plan["sampling_frequency_hz"],
        measurements_count=plan["measurements_count"],
        total_duration_seconds=plan["total_duration_seconds"],
    )
    _require_round_trip(restored.to_dict(), plan, "sampling plan")
    return restored


def _decode_sample(value: object) -> SampledMeasurement:
    sample = _require_mapping(value, "sample")
    _require_exact_keys(
        sample,
        {
            "sample_index",
            "scheduled_offset_seconds",
            "started_offset_seconds",
            "completed_offset_seconds",
            "start_lateness_seconds",
            "acquisition_duration_seconds",
            "measurement",
        },
        "sample",
    )
    restored = SampledMeasurement(
        sample_index=sample["sample_index"],
        scheduled_offset_seconds=sample["scheduled_offset_seconds"],
        started_offset_seconds=sample["started_offset_seconds"],
        completed_offset_seconds=sample["completed_offset_seconds"],
        measurement=_decode_measurement(sample["measurement"]),
    )
    _require_round_trip(restored.to_dict(), sample, "sample")
    return restored


def _decode_measurement(value: object) -> CurrentMeasurement:
    measurement = _require_mapping(value, "measurement")
    _require_exact_keys(
        measurement,
        {
            "ammeter_name",
            "current_a",
            "unit",
            "measured_at_utc",
            "monotonic_time_s",
            "latency_seconds",
        },
        "measurement",
    )
    if measurement["unit"] != CurrentMeasurement.unit:
        raise ResultArchiveCorruptionError(
            f"Unsupported measurement unit: {measurement['unit']!r}"
        )
    restored = CurrentMeasurement(
        ammeter_name=measurement["ammeter_name"],
        current_a=measurement["current_a"],
        measured_at_utc=_parse_utc_datetime(
            measurement["measured_at_utc"],
            "measurement.measured_at_utc",
        ),
        monotonic_time_s=measurement["monotonic_time_s"],
        latency_seconds=measurement["latency_seconds"],
    )
    _require_round_trip(restored.to_dict(), measurement, "measurement")
    return restored


def _decode_statistics(value: object) -> CurrentStatistics:
    statistics = _require_mapping(value, "statistics")
    _require_exact_keys(
        statistics,
        {
            "ammeter_name",
            "sample_count",
            "unit",
            "mean_current_a",
            "median_current_a",
            "standard_deviation_current_a",
            "minimum_current_a",
            "maximum_current_a",
        },
        "statistics",
    )
    if statistics["unit"] != CurrentStatistics.unit:
        raise ResultArchiveCorruptionError(
            f"Unsupported statistics unit: {statistics['unit']!r}"
        )
    restored = CurrentStatistics(
        ammeter_name=statistics["ammeter_name"],
        sample_count=statistics["sample_count"],
        mean_current_a=statistics["mean_current_a"],
        median_current_a=statistics["median_current_a"],
        standard_deviation_current_a=(
            statistics["standard_deviation_current_a"]
        ),
        minimum_current_a=statistics["minimum_current_a"],
        maximum_current_a=statistics["maximum_current_a"],
    )
    _require_round_trip(restored.to_dict(), statistics, "statistics")
    return restored


def _parse_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResultArchiveCorruptionError(
            f"{field_name} must be a canonical UTC timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ResultArchiveCorruptionError(
            f"{field_name} must be a canonical UTC timestamp"
        ) from exc
    canonical = parsed.isoformat().replace("+00:00", "Z")
    if canonical != value:
        raise ResultArchiveCorruptionError(
            f"{field_name} must be a canonical UTC timestamp"
        )
    return parsed


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ResultArchiveCorruptionError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ResultArchiveCorruptionError(
            f"{field_name} keys must be strings"
        )
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ResultArchiveCorruptionError(
            f"{field_name} has invalid keys; missing={missing}, "
            f"unexpected={unexpected}"
        )


def _require_round_trip(
    restored: Mapping[str, Any],
    stored: Mapping[str, Any],
    field_name: str,
) -> None:
    if not _strict_json_equal(restored, stored):
        raise ResultArchiveCorruptionError(
            f"{field_name} derived fields or types are inconsistent"
        )


def validate_sampling_semantics(run: SamplingRunResult) -> None:
    """Validate relationships not encoded by individual Phase 3 records."""

    if run.sample_count > run.plan.maximum_scheduled_samples:
        raise ResultArchiveCorruptionError(
            "sampling_result contains more samples than its plan permits"
        )
    clock_roundoff_tolerance = 2.0 * max(
        math.ulp(run.started_monotonic_s),
        math.ulp(run.completed_monotonic_s),
    )
    duration_seconds = run.plan.total_duration_seconds
    duration_deadline_offset = (
        (run.started_monotonic_s + duration_seconds)
        - run.started_monotonic_s
        if duration_seconds is not None
        else None
    )
    previous_completed_offset = 0.0
    for sample in run.samples:
        expected_scheduled_offset = (
            sample.sample_index * run.plan.period_seconds
        )
        if sample.scheduled_offset_seconds != expected_scheduled_offset:
            raise ResultArchiveCorruptionError(
                "sample scheduled offset does not match the sampling grid"
            )
        if (
            previous_completed_offset - sample.started_offset_seconds
            > clock_roundoff_tolerance
        ):
            raise ResultArchiveCorruptionError(
                "sample acquisitions overlap or are out of order"
            )
        if (
            sample.scheduled_offset_seconds - sample.started_offset_seconds
            > clock_roundoff_tolerance
        ):
            raise ResultArchiveCorruptionError(
                "sample acquisition started before its scheduled deadline"
            )
        if (
            sample.completed_offset_seconds - run.elapsed_seconds
            > clock_roundoff_tolerance
        ):
            raise ResultArchiveCorruptionError(
                "sample completion exceeds the recorded run duration"
            )
        if (
            sample.sample_index > 0
            and duration_deadline_offset is not None
            and sample.started_offset_seconds
            - duration_deadline_offset
            > clock_roundoff_tolerance
        ):
            raise ResultArchiveCorruptionError(
                "sample started outside the plan's half-open duration window"
            )
        previous_completed_offset = sample.completed_offset_seconds

    if duration_deadline_offset is not None:
        # Reproduce the scheduler's absolute-deadline arithmetic before
        # comparing serialized relative offsets. Exact boundary equality is
        # inherently ambiguous after float subtraction, so only differences
        # beyond the clock-scale ULP allowance are rejected.
        if (
            run.stop_reason is SamplingStopReason.COUNT_REACHED
            and run.samples[-1].completed_offset_seconds
            - duration_deadline_offset
            > clock_roundoff_tolerance
        ):
            raise ResultArchiveCorruptionError(
                "count stop reason conflicts with the duration deadline"
            )
        if run.stop_reason is SamplingStopReason.DURATION_REACHED:
            count_was_reached = (
                run.plan.measurements_count is not None
                and run.sample_count == run.plan.measurements_count
            )
            if (
                count_was_reached
                and duration_deadline_offset
                - run.samples[-1].completed_offset_seconds
                > clock_roundoff_tolerance
            ):
                raise ResultArchiveCorruptionError(
                    "duration stop reason conflicts with the count deadline"
                )
            if (
                not count_was_reached
                and run.sample_count < run.plan.maximum_scheduled_samples
                and duration_deadline_offset - run.elapsed_seconds
                > clock_roundoff_tolerance
            ):
                raise ResultArchiveCorruptionError(
                    "duration stop reason precedes the duration deadline"
                )


def validate_analyzed_result_semantics(
    result: AnalyzedSamplingResult,
) -> None:
    """Apply identical evidence and statistics checks on save and load."""

    validate_sampling_semantics(result.sampling_result)
    recalculated = ResultAnalyzer().analyze(result.sampling_result)
    if not _strict_json_equal(
        recalculated.to_dict(),
        result.statistics.to_dict(),
    ):
        raise ResultArchiveCorruptionError(
            "Archived statistics do not match the raw sampling evidence"
        )


def _strict_json_equal(left: object, right: object) -> bool:
    """Compare JSON values without treating booleans as numeric values."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        assert isinstance(right, dict)
        return set(left) == set(right) and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(
            _strict_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if isinstance(left, float):
        assert isinstance(right, float)
        if left != right:
            return False
        if left == 0.0:
            return math.copysign(1.0, left) == math.copysign(1.0, right)
        return True
    return left == right
