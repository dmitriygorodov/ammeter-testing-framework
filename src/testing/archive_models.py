"""Immutable records used by the Phase 5 result archive."""

from __future__ import annotations

import json
import math
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, ClassVar, TypeAlias
from uuid import UUID

from .models import AnalyzedSamplingResult, CurrentStatistics, SamplingPlan


JsonScalar: TypeAlias = str | int | float | bool | None


class RunStatus(str, Enum):
    """Persistence state represented by the current successful-run model."""

    COMPLETED = "completed"


@dataclass(frozen=True, slots=True, kw_only=True)
class RunMetadata:
    """Operator and DUT context stored alongside immutable run evidence."""

    test_name: str = "ammeter_sampling_analysis"
    operator: str | None = None
    dut_id: str | None = None
    station_id: str | None = None
    notes: str | None = None
    tags: tuple[str, ...] = ()
    attributes: tuple[tuple[str, JsonScalar], ...] = ()

    def __post_init__(self) -> None:
        _require_clean_text(self.test_name, "test_name")
        for field_name in ("operator", "dut_id", "station_id", "notes"):
            value = getattr(self, field_name)
            if value is not None:
                _require_clean_text(value, field_name)

        if not isinstance(self.tags, tuple):
            raise TypeError("tags must be a tuple")
        normalized_tags: set[str] = set()
        for tag in self.tags:
            _require_clean_text(tag, "tag")
            normalized_tag = tag.casefold()
            if normalized_tag in normalized_tags:
                raise ValueError(f"Duplicate metadata tag: {tag}")
            normalized_tags.add(normalized_tag)

        if not isinstance(self.attributes, tuple):
            raise TypeError("attributes must be a tuple")
        normalized_keys: set[str] = set()
        for attribute in self.attributes:
            if (
                not isinstance(attribute, tuple)
                or len(attribute) != 2
            ):
                raise TypeError(
                    "attributes must contain (key, JSON scalar) tuples"
                )
            key, value = attribute
            _require_clean_text(key, "attribute key")
            normalized_key = key.casefold()
            if normalized_key in normalized_keys:
                raise ValueError(f"Duplicate metadata attribute: {key}")
            normalized_keys.add(normalized_key)
            _require_json_scalar(value, f"attribute {key!r}")
        object.__setattr__(
            self,
            "attributes",
            tuple(sorted(self.attributes, key=lambda item: item[0].casefold())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "operator": self.operator,
            "dut_id": self.dut_id,
            "station_id": self.station_id,
            "notes": self.notes,
            "tags": list(self.tags),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchivedTestResult:
    """One complete analyzed test run plus persistent archive identity."""

    run_id: str
    archived_at_utc: datetime
    metadata: RunMetadata
    analyzed_result: AnalyzedSamplingResult
    content_sha256: str
    status: RunStatus = RunStatus.COMPLETED

    schema_version: ClassVar[int] = 1
    integrity_algorithm: ClassVar[str] = "sha256"

    def __post_init__(self) -> None:
        require_canonical_run_id(self.run_id)
        _require_utc_datetime(self.archived_at_utc, "archived_at_utc")
        if not isinstance(self.metadata, RunMetadata):
            raise TypeError("metadata must be RunMetadata")
        if not isinstance(self.analyzed_result, AnalyzedSamplingResult):
            raise TypeError(
                "analyzed_result must be an AnalyzedSamplingResult"
            )
        if self.status is not RunStatus.COMPLETED:
            raise ValueError(
                "AnalyzedSamplingResult archives must have completed status"
            )
        if (
            not isinstance(self.content_sha256, str)
            or len(self.content_sha256) != 64
            or any(
                character not in string.hexdigits.lower()
                for character in self.content_sha256
            )
            or self.content_sha256 != self.content_sha256.lower()
        ):
            raise ValueError(
                "content_sha256 must be 64 lowercase hexadecimal characters"
            )

    @property
    def ammeter_name(self) -> str:
        return self.analyzed_result.ammeter_name

    def content_dict(self) -> dict[str, Any]:
        """Return the canonical checksum payload, excluding integrity data."""

        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status.value,
            "archived_at_utc": _datetime_to_json(self.archived_at_utc),
            "metadata": self.metadata.to_dict(),
            "analyzed_result": self.analyzed_result.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        document = self.content_dict()
        document["integrity"] = {
            "algorithm": self.integrity_algorithm,
            "content_sha256": self.content_sha256,
        }
        return document

    def to_summary(self) -> ArchivedResultSummary:
        run = self.analyzed_result.sampling_result
        return ArchivedResultSummary(
            run_id=self.run_id,
            archived_at_utc=self.archived_at_utc,
            status=self.status,
            metadata=self.metadata,
            ammeter_name=self.ammeter_name,
            sample_count=run.sample_count,
            sampling_plan=run.plan,
            statistics=self.analyzed_result.statistics,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchivedResultSummary:
    """Compact index-free projection returned while browsing the archive."""

    run_id: str
    archived_at_utc: datetime
    status: RunStatus
    metadata: RunMetadata
    ammeter_name: str
    sample_count: int
    sampling_plan: SamplingPlan
    statistics: CurrentStatistics

    def __post_init__(self) -> None:
        require_canonical_run_id(self.run_id)
        _require_utc_datetime(self.archived_at_utc, "archived_at_utc")
        if self.status is not RunStatus.COMPLETED:
            raise ValueError("Archived summaries must have completed status")
        if not isinstance(self.metadata, RunMetadata):
            raise TypeError("metadata must be RunMetadata")
        _require_clean_text(self.ammeter_name, "ammeter_name")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count <= 0
        ):
            raise ValueError("sample_count must be a positive integer")
        if not isinstance(self.sampling_plan, SamplingPlan):
            raise TypeError("sampling_plan must be a SamplingPlan")
        if not isinstance(self.statistics, CurrentStatistics):
            raise TypeError("statistics must be CurrentStatistics")
        if self.statistics.ammeter_name != self.ammeter_name:
            raise ValueError("statistics must identify the summary ammeter")
        if self.statistics.sample_count != self.sample_count:
            raise ValueError("statistics sample_count must match the summary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "archived_at_utc": _datetime_to_json(self.archived_at_utc),
            "status": self.status.value,
            "metadata": self.metadata.to_dict(),
            "ammeter_name": self.ammeter_name,
            "sample_count": self.sample_count,
            "sampling_plan": self.sampling_plan.to_dict(),
            "statistics": self.statistics.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalResultComparison:
    """Full-precision candidate-minus-baseline statistical differences."""

    baseline_run_id: str
    candidate_run_id: str
    baseline_archived_at_utc: datetime
    candidate_archived_at_utc: datetime
    ammeter_name: str
    test_name: str
    baseline_statistics: CurrentStatistics
    candidate_statistics: CurrentStatistics
    sample_count_delta: int
    mean_current_delta_a: float
    median_current_delta_a: float
    standard_deviation_current_delta_a: float
    minimum_current_delta_a: float
    maximum_current_delta_a: float
    sampling_plans_match: bool

    def __post_init__(self) -> None:
        require_canonical_run_id(self.baseline_run_id)
        require_canonical_run_id(self.candidate_run_id)
        _require_utc_datetime(
            self.baseline_archived_at_utc,
            "baseline_archived_at_utc",
        )
        _require_utc_datetime(
            self.candidate_archived_at_utc,
            "candidate_archived_at_utc",
        )
        _require_clean_text(self.ammeter_name, "ammeter_name")
        _require_clean_text(self.test_name, "test_name")
        for field_name in ("baseline_statistics", "candidate_statistics"):
            statistics = getattr(self, field_name)
            if not isinstance(statistics, CurrentStatistics):
                raise TypeError(f"{field_name} must be CurrentStatistics")
            if statistics.ammeter_name != self.ammeter_name:
                raise ValueError(
                    f"{field_name} must identify the comparison ammeter"
                )
        if (
            isinstance(self.sample_count_delta, bool)
            or not isinstance(self.sample_count_delta, int)
        ):
            raise TypeError("sample_count_delta must be an integer")
        for field_name in (
            "mean_current_delta_a",
            "median_current_delta_a",
            "standard_deviation_current_delta_a",
            "minimum_current_delta_a",
            "maximum_current_delta_a",
        ):
            _require_finite_number(getattr(self, field_name), field_name)
        if not isinstance(self.sampling_plans_match, bool):
            raise TypeError("sampling_plans_match must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "candidate_run_id": self.candidate_run_id,
            "baseline_archived_at_utc": _datetime_to_json(
                self.baseline_archived_at_utc
            ),
            "candidate_archived_at_utc": _datetime_to_json(
                self.candidate_archived_at_utc
            ),
            "ammeter_name": self.ammeter_name,
            "test_name": self.test_name,
            "sampling_plans_match": self.sampling_plans_match,
            "baseline_statistics": self.baseline_statistics.to_dict(),
            "candidate_statistics": self.candidate_statistics.to_dict(),
            "deltas": {
                "sample_count": self.sample_count_delta,
                "mean_current_a": self.mean_current_delta_a,
                "median_current_a": self.median_current_delta_a,
                "standard_deviation_current_a": (
                    self.standard_deviation_current_delta_a
                ),
                "minimum_current_a": self.minimum_current_delta_a,
                "maximum_current_a": self.maximum_current_delta_a,
            },
        }


def require_canonical_run_id(value: object) -> str:
    """Validate an opaque run ID before it can influence a filesystem path."""

    if not isinstance(value, str) or not value:
        raise ValueError("run_id must be a canonical UUID string")
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("run_id must be a canonical UUID string") from exc
    if str(parsed) != value:
        raise ValueError("run_id must be a canonical lowercase UUID string")
    return value


def _require_clean_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have surrounding whitespace")
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL characters")
    return value


def _require_json_scalar(value: object, field_name: str) -> None:
    is_scalar = (
        value is None
        or isinstance(value, (str, bool, int))
        or (isinstance(value, float) and math.isfinite(value))
    )
    if not is_scalar:
        raise ValueError(f"{field_name} must be a finite JSON scalar")
    try:
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise ValueError(
            f"{field_name} must be a UTF-8 JSON-encodable finite scalar"
        ) from exc


def _require_finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be a finite number")
    return normalized


def _require_utc_datetime(value: object, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _datetime_to_json(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
