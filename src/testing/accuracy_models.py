"""Immutable records for reference-based cross-ammeter assessment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, ClassVar

from .archive_models import require_canonical_run_id
from .models import SamplingPlan, SamplingStopReason


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceCurrent:
    """Known current used as the external basis for an accuracy assessment."""

    current_a: float
    source: str
    expanded_uncertainty_a: float | None = None
    calibration_id: str | None = None

    unit: ClassVar[str] = "A"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "current_a",
            _finite_number(self.current_a, "current_a"),
        )
        _clean_text(self.source, "source")
        if self.expanded_uncertainty_a is not None:
            object.__setattr__(
                self,
                "expanded_uncertainty_a",
                _nonnegative_finite_number(
                    self.expanded_uncertainty_a,
                    "expanded_uncertainty_a",
                ),
            )
        if self.calibration_id is not None:
            _clean_text(self.calibration_id, "calibration_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_a": self.current_a,
            "unit": self.unit,
            "source": self.source,
            "expanded_uncertainty_a": self.expanded_uncertainty_a,
            "calibration_id": self.calibration_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AmmeterAccuracyMetrics:
    """Accuracy, precision, and reference-fidelity metrics for one run."""

    run_id: str
    ammeter_name: str
    sample_count: int
    mean_current_a: float
    signed_bias_a: float
    absolute_error_a: float
    relative_error_percent: float | None
    standard_deviation_current_a: float
    root_mean_square_error_a: float
    accuracy_rank: int
    precision_rank: int
    reliability_rank: int

    unit: ClassVar[str] = "A"

    def __post_init__(self) -> None:
        require_canonical_run_id(self.run_id)
        _clean_text(self.ammeter_name, "ammeter_name")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 2
        ):
            raise ValueError("sample_count must be an integer of at least two")
        for field_name in ("mean_current_a", "signed_bias_a"):
            object.__setattr__(
                self,
                field_name,
                _finite_number(getattr(self, field_name), field_name),
            )
        for field_name in (
            "absolute_error_a",
            "standard_deviation_current_a",
            "root_mean_square_error_a",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_finite_number(
                    getattr(self, field_name),
                    field_name,
                ),
            )
        if self.relative_error_percent is not None:
            object.__setattr__(
                self,
                "relative_error_percent",
                _nonnegative_finite_number(
                    self.relative_error_percent,
                    "relative_error_percent",
                ),
            )
        for field_name in (
            "accuracy_rank",
            "precision_rank",
            "reliability_rank",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.absolute_error_a != abs(self.signed_bias_a):
            raise ValueError("absolute_error_a must equal abs(signed_bias_a)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "ammeter_name": self.ammeter_name,
            "sample_count": self.sample_count,
            "unit": self.unit,
            "mean_current_a": self.mean_current_a,
            "signed_bias_a": self.signed_bias_a,
            "absolute_error_a": self.absolute_error_a,
            "relative_error_percent": self.relative_error_percent,
            "standard_deviation_current_a": (
                self.standard_deviation_current_a
            ),
            "root_mean_square_error_a": self.root_mean_square_error_a,
            "ranks": {
                "accuracy": self.accuracy_rank,
                "precision": self.precision_rank,
                "reliability": self.reliability_rank,
            },
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PairwiseAmmeterAgreement:
    """Deterministic second-minus-first comparison between ammeter means."""

    first_run_id: str
    second_run_id: str
    first_ammeter_name: str
    second_ammeter_name: str
    signed_mean_difference_a: float
    absolute_mean_difference_a: float
    relative_difference_percent: float | None

    unit: ClassVar[str] = "A"

    def __post_init__(self) -> None:
        require_canonical_run_id(self.first_run_id)
        require_canonical_run_id(self.second_run_id)
        _clean_text(self.first_ammeter_name, "first_ammeter_name")
        _clean_text(self.second_ammeter_name, "second_ammeter_name")
        if _name_key(self.first_ammeter_name) >= _name_key(
            self.second_ammeter_name
        ):
            raise ValueError("Pairwise ammeter names must be in canonical order")
        object.__setattr__(
            self,
            "signed_mean_difference_a",
            _finite_number(
                self.signed_mean_difference_a,
                "signed_mean_difference_a",
            ),
        )
        object.__setattr__(
            self,
            "absolute_mean_difference_a",
            _nonnegative_finite_number(
                self.absolute_mean_difference_a,
                "absolute_mean_difference_a",
            ),
        )
        if self.relative_difference_percent is not None:
            object.__setattr__(
                self,
                "relative_difference_percent",
                _nonnegative_finite_number(
                    self.relative_difference_percent,
                    "relative_difference_percent",
                ),
            )
        if self.absolute_mean_difference_a != abs(
            self.signed_mean_difference_a
        ):
            raise ValueError(
                "absolute_mean_difference_a must equal the absolute signed value"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_run_id": self.first_run_id,
            "second_run_id": self.second_run_id,
            "first_ammeter_name": self.first_ammeter_name,
            "second_ammeter_name": self.second_ammeter_name,
            "unit": self.unit,
            "signed_mean_difference_a": self.signed_mean_difference_a,
            "absolute_mean_difference_a": self.absolute_mean_difference_a,
            "relative_difference_percent": self.relative_difference_percent,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAccuracyAssessment:
    """Like-for-like cross-ammeter assessment against one supplied reference."""

    reference: ReferenceCurrent
    comparison_group: str
    test_name: str
    dut_id: str | None
    station_id: str | None
    sampling_plan: SamplingPlan
    stop_reason: SamplingStopReason
    sample_count: int
    ammeters: tuple[AmmeterAccuracyMetrics, ...]
    pairwise_agreements: tuple[PairwiseAmmeterAgreement, ...]
    most_accurate_ammeters: tuple[str, ...]
    most_precise_ammeters: tuple[str, ...]
    most_reliable_ammeters: tuple[str, ...]

    unit: ClassVar[str] = "A"
    methodology: ClassVar[str] = (
        "external-reference bias, population standard deviation, and RMSE"
    )
    operational_failure_reliability_assessed: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not isinstance(self.reference, ReferenceCurrent):
            raise TypeError("reference must be ReferenceCurrent")
        _clean_text(self.comparison_group, "comparison_group")
        _clean_text(self.test_name, "test_name")
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
        if self.sample_count > self.sampling_plan.maximum_scheduled_samples:
            raise ValueError("sample_count exceeds the sampling plan limit")
        if (
            self.stop_reason is SamplingStopReason.COUNT_REACHED
            and self.sampling_plan.measurements_count != self.sample_count
        ):
            raise ValueError(
                "COUNT_REACHED requires sample_count to match the plan count"
            )
        if (
            self.stop_reason is SamplingStopReason.DURATION_REACHED
            and self.sampling_plan.total_duration_seconds is None
        ):
            raise ValueError(
                "DURATION_REACHED requires a configured duration limit"
            )
        if not isinstance(self.ammeters, tuple) or len(self.ammeters) < 2:
            raise ValueError("ammeters must contain at least two assessments")
        if not all(
            isinstance(item, AmmeterAccuracyMetrics) for item in self.ammeters
        ):
            raise TypeError("ammeters must contain AmmeterAccuracyMetrics")
        names = tuple(item.ammeter_name for item in self.ammeters)
        if names != tuple(sorted(names, key=_name_key)):
            raise ValueError("ammeters must be in deterministic name order")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("ammeter names must be unique")
        run_ids = tuple(item.run_id for item in self.ammeters)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("ammeter source run IDs must be unique")
        if any(item.sample_count != self.sample_count for item in self.ammeters):
            raise ValueError("every ammeter must use the assessment sample_count")
        self._validate_metric_derivations()
        self._validate_ranks()
        if not isinstance(self.pairwise_agreements, tuple):
            raise TypeError("pairwise_agreements must be a tuple")
        if any(
            not isinstance(pair, PairwiseAmmeterAgreement)
            for pair in self.pairwise_agreements
        ):
            raise TypeError(
                "pairwise_agreements must contain PairwiseAmmeterAgreement"
            )
        expected_pairs = tuple(combinations(names, 2))
        actual_pairs = tuple(
            (pair.first_ammeter_name, pair.second_ammeter_name)
            for pair in self.pairwise_agreements
        )
        if actual_pairs != expected_pairs:
            raise ValueError(
                "pairwise_agreements must cover every pair in deterministic order"
            )
        run_id_by_name = {
            item.ammeter_name: item.run_id for item in self.ammeters
        }
        if any(
            pair.first_run_id != run_id_by_name[pair.first_ammeter_name]
            or pair.second_run_id != run_id_by_name[pair.second_ammeter_name]
            for pair in self.pairwise_agreements
        ):
            raise ValueError("pairwise run IDs must match their ammeter records")
        metrics_by_name = {
            item.ammeter_name: item for item in self.ammeters
        }
        for pair in self.pairwise_agreements:
            first = metrics_by_name[pair.first_ammeter_name]
            second = metrics_by_name[pair.second_ammeter_name]
            expected_difference = _finite_difference(
                second.mean_current_a,
                first.mean_current_a,
                "pairwise mean difference",
            )
            expected_relative = _relative_percent(
                abs(expected_difference),
                self.reference.current_a,
                "pairwise relative difference",
            )
            if (
                pair.signed_mean_difference_a != expected_difference
                or pair.absolute_mean_difference_a != abs(expected_difference)
                or pair.relative_difference_percent != expected_relative
            ):
                raise ValueError(
                    "pairwise metrics must match their source ammeter means"
                )
        if any(
            rank > len(self.ammeters)
            for item in self.ammeters
            for rank in (
                item.accuracy_rank,
                item.precision_rank,
                item.reliability_rank,
            )
        ):
            raise ValueError("ammeter ranks must not exceed the cohort size")
        self._validate_winners(
            self.most_accurate_ammeters,
            "accuracy_rank",
            "most_accurate_ammeters",
        )
        self._validate_winners(
            self.most_precise_ammeters,
            "precision_rank",
            "most_precise_ammeters",
        )
        self._validate_winners(
            self.most_reliable_ammeters,
            "reliability_rank",
            "most_reliable_ammeters",
        )

    def _validate_metric_derivations(self) -> None:
        for item in self.ammeters:
            expected_bias = _finite_difference(
                item.mean_current_a,
                self.reference.current_a,
                "reference bias",
            )
            expected_relative = _relative_percent(
                abs(expected_bias),
                self.reference.current_a,
                "relative reference error",
            )
            expected_rmse = math.hypot(
                expected_bias,
                item.standard_deviation_current_a,
            )
            if not math.isfinite(expected_rmse):
                raise ValueError("root mean square error must be finite")
            expected_rmse = _normalize_zero(expected_rmse)
            if (
                item.signed_bias_a != expected_bias
                or item.absolute_error_a != abs(expected_bias)
                or item.relative_error_percent != expected_relative
                or item.root_mean_square_error_a != expected_rmse
            ):
                raise ValueError(
                    "ammeter metrics must match the supplied reference"
                )

    def _validate_ranks(self) -> None:
        for rank_field, score_field in (
            ("accuracy_rank", "absolute_error_a"),
            ("precision_rank", "standard_deviation_current_a"),
            ("reliability_rank", "root_mean_square_error_a"),
        ):
            expected = _competition_ranks(self.ammeters, score_field)
            if any(
                getattr(item, rank_field) != expected[item.ammeter_name]
                for item in self.ammeters
            ):
                raise ValueError(
                    f"{rank_field} values must match the assessment metrics"
                )

    def _validate_winners(
        self,
        winners: tuple[str, ...],
        rank_field: str,
        field_name: str,
    ) -> None:
        if not isinstance(winners, tuple):
            raise TypeError(f"{field_name} must be a tuple")
        expected = tuple(
            item.ammeter_name
            for item in self.ammeters
            if getattr(item, rank_field) == 1
        )
        if winners != expected or not winners:
            raise ValueError(f"{field_name} must contain every rank-one ammeter")

    def to_dict(self) -> dict[str, Any]:
        return {
            "methodology": self.methodology,
            "operational_failure_reliability_assessed": (
                self.operational_failure_reliability_assessed
            ),
            "reference": self.reference.to_dict(),
            "comparison_group": self.comparison_group,
            "test_name": self.test_name,
            "dut_id": self.dut_id,
            "station_id": self.station_id,
            "sampling_plan": self.sampling_plan.to_dict(),
            "stop_reason": self.stop_reason.value,
            "sample_count": self.sample_count,
            "unit": self.unit,
            "ammeters": [item.to_dict() for item in self.ammeters],
            "pairwise_agreements": [
                pair.to_dict() for pair in self.pairwise_agreements
            ],
            "winners": {
                "most_accurate": list(self.most_accurate_ammeters),
                "most_precise": list(self.most_precise_ammeters),
                "most_reliable": list(self.most_reliable_ammeters),
            },
        }


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be a finite number")
    return 0.0 if normalized == 0.0 else normalized


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


def _name_key(value: str) -> tuple[str, str]:
    return value.casefold(), value


def _finite_difference(left: float, right: float, field_name: str) -> float:
    difference = left - right
    if not math.isfinite(difference):
        raise ValueError(f"{field_name} must be finite")
    return _normalize_zero(difference)


def _relative_percent(
    numerator: float,
    reference_current_a: float,
    field_name: str,
) -> float | None:
    denominator = abs(reference_current_a)
    if denominator == 0.0:
        return None
    percentage = (numerator / denominator) * 100.0
    if not math.isfinite(percentage):
        raise ValueError(f"{field_name} must be finite")
    return _normalize_zero(percentage)


def _competition_ranks(
    metrics: tuple[AmmeterAccuracyMetrics, ...],
    score_field: str,
) -> dict[str, int]:
    ordered = sorted(
        metrics,
        key=lambda item: (
            getattr(item, score_field),
            item.ammeter_name.casefold(),
            item.ammeter_name,
        ),
    )
    ranks: dict[str, int] = {}
    previous_score: float | None = None
    previous_rank = 0
    for position, item in enumerate(ordered, start=1):
        score = getattr(item, score_field)
        if previous_score is None or score != previous_score:
            previous_score = score
            previous_rank = position
        ranks[item.ammeter_name] = previous_rank
    return ranks


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value
