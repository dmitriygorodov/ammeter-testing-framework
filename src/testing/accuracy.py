"""Reference-based accuracy, precision, and reliability assessment."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from .archive_codec import validate_analyzed_result_semantics
from .archive_models import ArchivedTestResult
from .accuracy_models import (
    AmmeterAccuracyMetrics,
    PairwiseAmmeterAgreement,
    ReferenceAccuracyAssessment,
    ReferenceCurrent,
)
from .errors import (
    AccuracyAssessmentError,
    IncomparableAmmeterEvidenceError,
    ResultArchiveCorruptionError,
)


COMPARISON_GROUP_ATTRIBUTE = "comparison_group"
UNGROUPED_EXPLICIT_SELECTION = "explicit-ungrouped-run-selection"


@dataclass(frozen=True, slots=True)
class _UnrankedAccuracyMetrics:
    archived: ArchivedTestResult
    mean_current_a: float
    signed_bias_a: float
    absolute_error_a: float
    relative_error_percent: float | None
    standard_deviation_current_a: float
    root_mean_square_error_a: float


class AccuracyAssessor:
    """Assess compatible completed runs against an external current reference.

    Accuracy rank uses absolute mean bias, precision rank uses the Phase 4
    population standard deviation, and reliability rank uses reference RMSE.
    RMSE is calculated as ``hypot(bias, population_stddev)`` from the standard
    bias/variance decomposition. Lower values are better for every rank.
    """

    def assess(
        self,
        results: Iterable[ArchivedTestResult],
        *,
        reference: ReferenceCurrent,
    ) -> ReferenceAccuracyAssessment:
        """Return a deterministic assessment without reading any hardware."""

        if not isinstance(reference, ReferenceCurrent):
            raise TypeError("reference must be ReferenceCurrent")
        if isinstance(results, (str, bytes)):
            raise TypeError("results must be an iterable of ArchivedTestResult")
        try:
            cohort = tuple(results)
        except TypeError as exc:
            raise TypeError(
                "results must be an iterable of ArchivedTestResult"
            ) from exc
        if len(cohort) < 2:
            raise IncomparableAmmeterEvidenceError(
                "Accuracy assessment requires at least two ammeter runs"
            )
        if not all(isinstance(item, ArchivedTestResult) for item in cohort):
            raise TypeError("results must contain ArchivedTestResult records")

        ordered = tuple(
            sorted(
                cohort,
                key=lambda item: (
                    item.ammeter_name.casefold(),
                    item.ammeter_name,
                    item.run_id,
                ),
            )
        )
        comparison_group = self._validate_cohort(ordered)
        unranked = tuple(
            self._calculate_metrics(item, reference) for item in ordered
        )
        accuracy_ranks = _competition_ranks(
            (item.archived.ammeter_name, item.absolute_error_a)
            for item in unranked
        )
        precision_ranks = _competition_ranks(
            (
                item.archived.ammeter_name,
                item.standard_deviation_current_a,
            )
            for item in unranked
        )
        reliability_ranks = _competition_ranks(
            (
                item.archived.ammeter_name,
                item.root_mean_square_error_a,
            )
            for item in unranked
        )

        metrics = tuple(
            AmmeterAccuracyMetrics(
                run_id=item.archived.run_id,
                ammeter_name=item.archived.ammeter_name,
                sample_count=(
                    item.archived.analyzed_result.sampling_result.sample_count
                ),
                mean_current_a=item.mean_current_a,
                signed_bias_a=item.signed_bias_a,
                absolute_error_a=item.absolute_error_a,
                relative_error_percent=item.relative_error_percent,
                standard_deviation_current_a=(
                    item.standard_deviation_current_a
                ),
                root_mean_square_error_a=item.root_mean_square_error_a,
                accuracy_rank=accuracy_ranks[item.archived.ammeter_name],
                precision_rank=precision_ranks[item.archived.ammeter_name],
                reliability_rank=reliability_ranks[item.archived.ammeter_name],
            )
            for item in unranked
        )
        pairwise = tuple(
            self._compare_pair(first, second, reference)
            for first, second in combinations(metrics, 2)
        )
        anchor = ordered[0]
        sampling_run = anchor.analyzed_result.sampling_result
        return ReferenceAccuracyAssessment(
            reference=reference,
            comparison_group=comparison_group,
            test_name=anchor.metadata.test_name,
            dut_id=anchor.metadata.dut_id,
            station_id=anchor.metadata.station_id,
            sampling_plan=sampling_run.plan,
            stop_reason=sampling_run.stop_reason,
            sample_count=sampling_run.sample_count,
            ammeters=metrics,
            pairwise_agreements=pairwise,
            most_accurate_ammeters=_rank_one_names(metrics, "accuracy_rank"),
            most_precise_ammeters=_rank_one_names(metrics, "precision_rank"),
            most_reliable_ammeters=_rank_one_names(
                metrics,
                "reliability_rank",
            ),
        )

    def _validate_cohort(
        self,
        cohort: tuple[ArchivedTestResult, ...],
    ) -> str:
        run_ids = [item.run_id for item in cohort]
        if len(set(run_ids)) != len(run_ids):
            raise IncomparableAmmeterEvidenceError(
                "Each source run ID may appear only once"
            )
        normalized_names = [item.ammeter_name.casefold() for item in cohort]
        if len(set(normalized_names)) != len(normalized_names):
            raise IncomparableAmmeterEvidenceError(
                "Accuracy assessment requires one run per distinct ammeter"
            )

        anchor = cohort[0]
        anchor_run = anchor.analyzed_result.sampling_result
        groups = tuple(_optional_comparison_group(item) for item in cohort)
        if all(group is None for group in groups):
            effective_group = UNGROUPED_EXPLICIT_SELECTION
        elif any(group is None for group in groups):
            raise IncomparableAmmeterEvidenceError(
                "comparison_group metadata must be present on every selected "
                "run or absent from every selected run"
            )
        else:
            effective_group = groups[0]
            assert effective_group is not None
        for archived, group in zip(cohort, groups, strict=True):
            try:
                validate_analyzed_result_semantics(archived.analyzed_result)
            except ResultArchiveCorruptionError as exc:
                raise IncomparableAmmeterEvidenceError(
                    f"Run {archived.run_id} contains inconsistent evidence"
                ) from exc
            run = archived.analyzed_result.sampling_result
            if run.sample_count < 2:
                raise IncomparableAmmeterEvidenceError(
                    "At least two samples per ammeter are required to assess "
                    "precision"
                )
            if archived.metadata.test_name != anchor.metadata.test_name:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must use the same metadata test_name"
                )
            if group is not None and group != effective_group:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must use the same comparison_group metadata"
                )
            if archived.metadata.dut_id != anchor.metadata.dut_id:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must identify the same DUT"
                )
            if archived.metadata.station_id != anchor.metadata.station_id:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must identify the same station"
                )
            if run.plan != anchor_run.plan:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must use the same sampling plan"
                )
            if run.sample_count != anchor_run.sample_count:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must contain the same number of samples"
                )
            if run.stop_reason is not anchor_run.stop_reason:
                raise IncomparableAmmeterEvidenceError(
                    "Every run must have the same sampling stop reason"
                )
        return effective_group

    def _calculate_metrics(
        self,
        archived: ArchivedTestResult,
        reference: ReferenceCurrent,
    ) -> _UnrankedAccuracyMetrics:
        # Cohort validation has just recomputed and strictly matched these
        # canonical Phase 4 statistics against the raw sampling evidence.
        statistics = archived.analyzed_result.statistics
        mean_current_a = _normalize_zero(statistics.mean_current_a)
        signed_bias_a = _finite_difference(
            mean_current_a,
            reference.current_a,
            "reference bias",
        )
        absolute_error_a = abs(signed_bias_a)
        relative_error_percent = _relative_percent(
            absolute_error_a,
            reference.current_a,
            "relative reference error",
        )
        standard_deviation = _normalize_zero(
            statistics.standard_deviation_current_a
        )
        rmse = math.hypot(signed_bias_a, standard_deviation)
        if not math.isfinite(rmse):
            raise AccuracyAssessmentError(
                f"Reference RMSE is outside the finite range for "
                f"{archived.ammeter_name}"
            )
        return _UnrankedAccuracyMetrics(
            archived=archived,
            mean_current_a=mean_current_a,
            signed_bias_a=signed_bias_a,
            absolute_error_a=absolute_error_a,
            relative_error_percent=relative_error_percent,
            standard_deviation_current_a=standard_deviation,
            root_mean_square_error_a=_normalize_zero(rmse),
        )

    def _compare_pair(
        self,
        first: AmmeterAccuracyMetrics,
        second: AmmeterAccuracyMetrics,
        reference: ReferenceCurrent,
    ) -> PairwiseAmmeterAgreement:
        signed_difference = _finite_difference(
            second.mean_current_a,
            first.mean_current_a,
            "pairwise mean difference",
        )
        absolute_difference = abs(signed_difference)
        return PairwiseAmmeterAgreement(
            first_run_id=first.run_id,
            second_run_id=second.run_id,
            first_ammeter_name=first.ammeter_name,
            second_ammeter_name=second.ammeter_name,
            signed_mean_difference_a=signed_difference,
            absolute_mean_difference_a=absolute_difference,
            relative_difference_percent=_relative_percent(
                absolute_difference,
                reference.current_a,
                "relative pairwise difference",
            ),
        )


def _optional_comparison_group(
    archived: ArchivedTestResult,
) -> str | None:
    for key, value in archived.metadata.attributes:
        if key.casefold() == COMPARISON_GROUP_ATTRIBUTE:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or any(character in value for character in ("\x00", "\r", "\n"))
            ):
                raise IncomparableAmmeterEvidenceError(
                    "comparison_group metadata must be a clean non-empty string"
                )
            return value
    return None


def _competition_ranks(
    values: Iterable[tuple[str, float]],
) -> dict[str, int]:
    ordered = sorted(
        values,
        key=lambda item: (item[1], item[0].casefold(), item[0]),
    )
    ranks: dict[str, int] = {}
    previous_value: float | None = None
    previous_rank = 0
    for position, (name, value) in enumerate(ordered, start=1):
        if previous_value is None or value != previous_value:
            previous_rank = position
            previous_value = value
        ranks[name] = previous_rank
    return ranks


def _rank_one_names(
    metrics: tuple[AmmeterAccuracyMetrics, ...],
    rank_field: str,
) -> tuple[str, ...]:
    return tuple(
        item.ammeter_name
        for item in metrics
        if getattr(item, rank_field) == 1
    )


def _finite_difference(left: float, right: float, label: str) -> float:
    difference = left - right
    if not math.isfinite(difference):
        raise AccuracyAssessmentError(
            f"{label} is outside the finite float range"
        )
    return _normalize_zero(difference)


def _relative_percent(
    numerator: float,
    reference_current_a: float,
    label: str,
) -> float | None:
    denominator = abs(reference_current_a)
    if denominator == 0.0:
        return None
    percentage = (numerator / denominator) * 100.0
    if not math.isfinite(percentage):
        raise AccuracyAssessmentError(
            f"{label} is outside the finite float range"
        )
    return _normalize_zero(percentage)


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value
