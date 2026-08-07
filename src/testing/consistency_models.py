"""Immutable historical consistency records for Phase 8."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import StatisticsError, mean, pstdev
from typing import Any

from .archive_models import require_canonical_run_id
from .models import CurrentStatistics, SamplingPlan, SamplingStopReason


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsistencyRunPoint:
    """One archived run projected onto a chronological consistency series."""

    run_id: str
    archived_at_utc: datetime
    completed_at_utc: datetime
    elapsed_since_first_seconds: float
    sampling_plan: SamplingPlan
    stop_reason: SamplingStopReason
    statistics: CurrentStatistics

    def __post_init__(self) -> None:
        require_canonical_run_id(self.run_id)
        _require_utc_datetime(self.archived_at_utc, "archived_at_utc")
        _require_utc_datetime(self.completed_at_utc, "completed_at_utc")
        elapsed = _nonnegative_finite_number(
            self.elapsed_since_first_seconds,
            "elapsed_since_first_seconds",
        )
        object.__setattr__(self, "elapsed_since_first_seconds", elapsed)
        if not isinstance(self.sampling_plan, SamplingPlan):
            raise TypeError("sampling_plan must be SamplingPlan")
        if not isinstance(self.stop_reason, SamplingStopReason):
            raise TypeError("stop_reason must be SamplingStopReason")
        if not isinstance(self.statistics, CurrentStatistics):
            raise TypeError("statistics must be CurrentStatistics")

    @property
    def ammeter_name(self) -> str:
        return self.statistics.ammeter_name

    @property
    def sample_count(self) -> int:
        return self.statistics.sample_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "archived_at_utc": _datetime_to_json(self.archived_at_utc),
            "completed_at_utc": _datetime_to_json(self.completed_at_utc),
            "elapsed_since_first_seconds": self.elapsed_since_first_seconds,
            "sampling_plan": self.sampling_plan.to_dict(),
            "stop_reason": self.stop_reason.value,
            "statistics": self.statistics.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalConsistencyMetrics:
    """Full-precision within-run and between-run stability metrics."""

    mean_of_run_means_a: float
    run_to_run_standard_deviation_a: float
    minimum_run_mean_a: float
    maximum_run_mean_a: float
    peak_to_peak_run_mean_a: float
    maximum_absolute_step_change_a: float
    mean_within_run_standard_deviation_a: float
    pooled_within_run_standard_deviation_a: float
    coefficient_of_variation_percent: float | None
    trend_slope_a_per_hour: float
    fitted_trend_change_a: float

    def __post_init__(self) -> None:
        for field_name in (
            "mean_of_run_means_a",
            "run_to_run_standard_deviation_a",
            "minimum_run_mean_a",
            "maximum_run_mean_a",
            "peak_to_peak_run_mean_a",
            "maximum_absolute_step_change_a",
            "mean_within_run_standard_deviation_a",
            "pooled_within_run_standard_deviation_a",
            "trend_slope_a_per_hour",
            "fitted_trend_change_a",
        ):
            normalized = _finite_number(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, normalized)
        for field_name in (
            "run_to_run_standard_deviation_a",
            "peak_to_peak_run_mean_a",
            "maximum_absolute_step_change_a",
            "mean_within_run_standard_deviation_a",
            "pooled_within_run_standard_deviation_a",
        ):
            if getattr(self, field_name) < 0.0:
                raise ValueError(f"{field_name} must be nonnegative")
        if self.coefficient_of_variation_percent is not None:
            coefficient = _nonnegative_finite_number(
                self.coefficient_of_variation_percent,
                "coefficient_of_variation_percent",
            )
            object.__setattr__(
                self,
                "coefficient_of_variation_percent",
                coefficient,
            )
        if self.minimum_run_mean_a > self.maximum_run_mean_a:
            raise ValueError(
                "minimum_run_mean_a must not exceed maximum_run_mean_a"
            )
        expected_peak_to_peak = _finite_difference(
            self.maximum_run_mean_a,
            self.minimum_run_mean_a,
            "peak-to-peak run mean",
        )
        if self.peak_to_peak_run_mean_a != expected_peak_to_peak:
            raise ValueError(
                "peak_to_peak_run_mean_a must equal maximum minus minimum"
            )

    def to_dict(self) -> dict[str, float | None]:
        return {
            "mean_of_run_means_a": self.mean_of_run_means_a,
            "run_to_run_standard_deviation_a": (
                self.run_to_run_standard_deviation_a
            ),
            "minimum_run_mean_a": self.minimum_run_mean_a,
            "maximum_run_mean_a": self.maximum_run_mean_a,
            "peak_to_peak_run_mean_a": self.peak_to_peak_run_mean_a,
            "maximum_absolute_step_change_a": (
                self.maximum_absolute_step_change_a
            ),
            "mean_within_run_standard_deviation_a": (
                self.mean_within_run_standard_deviation_a
            ),
            "pooled_within_run_standard_deviation_a": (
                self.pooled_within_run_standard_deviation_a
            ),
            "coefficient_of_variation_percent": (
                self.coefficient_of_variation_percent
            ),
            "trend_slope_a_per_hour": self.trend_slope_a_per_hour,
            "fitted_trend_change_a": self.fitted_trend_change_a,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalConsistencyAssessment:
    """Like-for-like historical stability assessment for one ammeter."""

    consistency_group: str
    test_name: str
    dut_id: str | None
    station_id: str | None
    ammeter_name: str
    sampling_plan: SamplingPlan
    stop_reason: SamplingStopReason
    sample_count: int
    runs: tuple[ConsistencyRunPoint, ...]
    metrics: HistoricalConsistencyMetrics

    def __post_init__(self) -> None:
        _clean_text(self.consistency_group, "consistency_group")
        _clean_text(self.test_name, "test_name")
        _clean_text(self.ammeter_name, "ammeter_name")
        for field_name in ("dut_id", "station_id"):
            value = getattr(self, field_name)
            if value is not None:
                _clean_text(value, field_name)
        if not isinstance(self.sampling_plan, SamplingPlan):
            raise TypeError("sampling_plan must be SamplingPlan")
        if not isinstance(self.stop_reason, SamplingStopReason):
            raise TypeError("stop_reason must be SamplingStopReason")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 2
        ):
            raise ValueError("sample_count must be an integer of at least two")
        if not isinstance(self.runs, tuple) or len(self.runs) < 3:
            raise ValueError("Historical consistency requires at least three runs")
        if not all(isinstance(run, ConsistencyRunPoint) for run in self.runs):
            raise TypeError("runs must contain ConsistencyRunPoint records")
        run_ids = tuple(run.run_id for run in self.runs)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Historical consistency run IDs must be unique")
        completion_times = tuple(run.completed_at_utc for run in self.runs)
        if len(set(completion_times)) != len(completion_times):
            raise ValueError(
                "Historical consistency completion timestamps must be unique"
            )
        expected_order = tuple(
            sorted(self.runs, key=lambda run: (run.completed_at_utc, run.run_id))
        )
        if self.runs != expected_order:
            raise ValueError("runs must be in chronological canonical order")
        first_completion = self.runs[0].completed_at_utc
        for run in self.runs:
            if run.ammeter_name != self.ammeter_name:
                raise ValueError("Every run must identify the assessment ammeter")
            if run.sample_count != self.sample_count:
                raise ValueError("Every run must have the assessment sample count")
            if run.sampling_plan != self.sampling_plan:
                raise ValueError("Every run must have the assessment sampling plan")
            if run.stop_reason is not self.stop_reason:
                raise ValueError("Every run must have the assessment stop reason")
            expected_elapsed = (
                run.completed_at_utc - first_completion
            ).total_seconds()
            if run.elapsed_since_first_seconds != expected_elapsed:
                raise ValueError(
                    "Run elapsed time must match its completion timestamp"
                )
        if self.runs[-1].elapsed_since_first_seconds <= 0.0:
            raise ValueError("Historical consistency requires a positive time span")
        if not isinstance(self.metrics, HistoricalConsistencyMetrics):
            raise TypeError("metrics must be HistoricalConsistencyMetrics")
        expected_metrics = calculate_consistency_metrics(self.runs)
        if self.metrics != expected_metrics:
            raise ValueError("metrics do not match the historical run series")

    @property
    def run_count(self) -> int:
        return len(self.runs)

    @property
    def time_span_seconds(self) -> float:
        return self.runs[-1].elapsed_since_first_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "consistency_group": self.consistency_group,
            "test_name": self.test_name,
            "dut_id": self.dut_id,
            "station_id": self.station_id,
            "ammeter_name": self.ammeter_name,
            "sampling_plan": self.sampling_plan.to_dict(),
            "stop_reason": self.stop_reason.value,
            "sample_count": self.sample_count,
            "run_count": self.run_count,
            "time_span_seconds": self.time_span_seconds,
            "metrics": self.metrics.to_dict(),
            "runs": [run.to_dict() for run in self.runs],
        }


def calculate_consistency_metrics(
    runs: tuple[ConsistencyRunPoint, ...],
) -> HistoricalConsistencyMetrics:
    """Calculate the canonical Phase 8 metric projection."""

    if len(runs) < 3:
        raise ValueError("At least three runs are required")
    span_seconds = runs[-1].elapsed_since_first_seconds
    if span_seconds <= 0.0:
        raise ValueError("A positive historical time span is required")
    run_means = tuple(run.statistics.mean_current_a for run in runs)
    within_deviations = tuple(
        run.statistics.standard_deviation_current_a for run in runs
    )
    mean_of_means = _safe_mean(run_means, "mean of run means")
    run_to_run_deviation = _population_standard_deviation(run_means)
    minimum_mean = min(run_means)
    maximum_mean = max(run_means)
    peak_to_peak = _finite_difference(
        maximum_mean,
        minimum_mean,
        "peak-to-peak run mean",
    )
    step_changes = tuple(
        abs(_finite_difference(current, previous, "adjacent run mean change"))
        for previous, current in zip(run_means, run_means[1:])
    )
    maximum_step = max(step_changes)
    mean_within = _safe_mean(
        within_deviations,
        "mean within-run standard deviation",
    )
    pooled_within = _root_mean_square(within_deviations)
    coefficient = None
    if mean_of_means != 0.0:
        coefficient = (run_to_run_deviation / abs(mean_of_means)) * 100.0
        if not math.isfinite(coefficient):
            raise ValueError("coefficient of variation is outside finite range")
        coefficient = _normalize_zero(coefficient)
    span_hours = span_seconds / 3600.0
    trend_slope = _linear_slope_per_hour(runs, run_means, span_hours)
    fitted_change = trend_slope * span_hours
    if not math.isfinite(fitted_change):
        raise ValueError("fitted trend change is outside finite range")
    return HistoricalConsistencyMetrics(
        mean_of_run_means_a=mean_of_means,
        run_to_run_standard_deviation_a=run_to_run_deviation,
        minimum_run_mean_a=_normalize_zero(minimum_mean),
        maximum_run_mean_a=_normalize_zero(maximum_mean),
        peak_to_peak_run_mean_a=peak_to_peak,
        maximum_absolute_step_change_a=_normalize_zero(maximum_step),
        mean_within_run_standard_deviation_a=mean_within,
        pooled_within_run_standard_deviation_a=pooled_within,
        coefficient_of_variation_percent=coefficient,
        trend_slope_a_per_hour=trend_slope,
        fitted_trend_change_a=_normalize_zero(fitted_change),
    )


def _linear_slope_per_hour(
    runs: tuple[ConsistencyRunPoint, ...],
    values: tuple[float, ...],
    span_hours: float,
) -> float:
    if not math.isfinite(span_hours) or span_hours <= 0.0:
        raise ValueError("trend time span must be positive and finite")
    normalized_times = tuple(
        (run.elapsed_since_first_seconds / 3600.0) / span_hours
        for run in runs
    )
    value_scale = max(abs(value) for value in values)
    normalized_values = (
        values
        if value_scale == 0.0
        else tuple(value / value_scale for value in values)
    )
    x_mean = _safe_mean(normalized_times, "normalized trend time mean")
    y_mean = _safe_mean(normalized_values, "normalized trend value mean")
    denominator = math.fsum((value - x_mean) ** 2 for value in normalized_times)
    if denominator <= 0.0 or not math.isfinite(denominator):
        raise ValueError("trend timestamps do not define a usable time axis")
    numerator = math.fsum(
        (time_value - x_mean) * (current_value - y_mean)
        for time_value, current_value in zip(
            normalized_times,
            normalized_values,
        )
    )
    normalized_slope = numerator / denominator
    slope = normalized_slope / span_hours
    if value_scale != 0.0:
        slope *= value_scale
    if not math.isfinite(slope):
        raise ValueError("trend slope is outside finite range")
    return _normalize_zero(slope)


def _population_standard_deviation(values: tuple[float, ...]) -> float:
    scale = max(abs(value) for value in values)
    if scale == 0.0:
        return 0.0
    exponent = math.frexp(scale)[1]
    normalized = tuple(math.ldexp(value, -exponent) for value in values)
    try:
        result = math.ldexp(pstdev(normalized), exponent)
    except (OverflowError, StatisticsError) as exc:
        raise ValueError("run-to-run deviation is outside finite range") from exc
    if not math.isfinite(result):
        raise ValueError("run-to-run deviation is outside finite range")
    return _normalize_zero(result)


def _root_mean_square(values: tuple[float, ...]) -> float:
    scale = max(values)
    if scale == 0.0:
        return 0.0
    normalized_square_mean = math.fsum((value / scale) ** 2 for value in values)
    normalized_square_mean /= len(values)
    result = scale * math.sqrt(normalized_square_mean)
    if not math.isfinite(result):
        raise ValueError("pooled within-run deviation is outside finite range")
    return _normalize_zero(result)


def _safe_mean(values: tuple[float, ...], label: str) -> float:
    try:
        result = mean(values)
    except (OverflowError, StatisticsError) as exc:
        raise ValueError(f"{label} is outside finite range") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} is outside finite range")
    return _normalize_zero(result)


def _finite_difference(left: float, right: float, label: str) -> float:
    result = left - right
    if not math.isfinite(result):
        raise ValueError(f"{label} is outside finite range")
    return _normalize_zero(result)


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be a finite number")
    return _normalize_zero(normalized)


def _nonnegative_finite_number(value: object, field_name: str) -> float:
    normalized = _finite_number(value, field_name)
    if normalized < 0.0:
        raise ValueError(f"{field_name} must be nonnegative")
    return normalized


def _clean_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have surrounding whitespace")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{field_name} must not contain control delimiters")
    return value


def _require_utc_datetime(value: object, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _datetime_to_json(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value
