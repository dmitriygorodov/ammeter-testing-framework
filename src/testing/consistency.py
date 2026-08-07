"""Read-only historical performance-consistency analysis for Phase 8."""

from __future__ import annotations

from collections.abc import Iterable

from .archive_codec import validate_analyzed_result_semantics
from .archive_models import ArchivedTestResult
from .consistency_models import (
    ConsistencyRunPoint,
    HistoricalConsistencyAssessment,
    calculate_consistency_metrics,
)
from .errors import (
    ConsistencyAnalysisError,
    IncomparableHistoryError,
    ResultArchiveCorruptionError,
)


CONSISTENCY_GROUP_ATTRIBUTE = "consistency_group"


class HistoricalConsistencyAnalyzer:
    """Quantify repeatability and drift across comparable archived runs."""

    def assess(
        self,
        results: Iterable[ArchivedTestResult],
    ) -> HistoricalConsistencyAssessment:
        if isinstance(results, (str, bytes)):
            raise TypeError("results must be an iterable of ArchivedTestResult")
        try:
            cohort = tuple(results)
        except TypeError as exc:
            raise TypeError(
                "results must be an iterable of ArchivedTestResult"
            ) from exc
        if len(cohort) < 3:
            raise IncomparableHistoryError(
                "Historical consistency requires at least three archived runs"
            )
        if not all(isinstance(item, ArchivedTestResult) for item in cohort):
            raise TypeError("results must contain ArchivedTestResult records")
        ordered = tuple(
            sorted(
                cohort,
                key=lambda item: (
                    item.analyzed_result.sampling_result.completed_at_utc,
                    item.run_id,
                ),
            )
        )
        self._validate_cohort(ordered)
        first_completion = (
            ordered[0].analyzed_result.sampling_result.completed_at_utc
        )
        points = tuple(
            ConsistencyRunPoint(
                run_id=archived.run_id,
                archived_at_utc=archived.archived_at_utc,
                completed_at_utc=(
                    archived.analyzed_result.sampling_result.completed_at_utc
                ),
                elapsed_since_first_seconds=(
                    archived.analyzed_result.sampling_result.completed_at_utc
                    - first_completion
                ).total_seconds(),
                sampling_plan=archived.analyzed_result.sampling_result.plan,
                stop_reason=(
                    archived.analyzed_result.sampling_result.stop_reason
                ),
                statistics=archived.analyzed_result.statistics,
            )
            for archived in ordered
        )
        try:
            metrics = calculate_consistency_metrics(points)
        except (ArithmeticError, ValueError) as exc:
            raise ConsistencyAnalysisError(
                "Historical consistency metrics could not be calculated safely"
            ) from exc
        anchor = ordered[0]
        anchor_run = anchor.analyzed_result.sampling_result
        return HistoricalConsistencyAssessment(
            consistency_group=_consistency_group(anchor),
            test_name=anchor.metadata.test_name,
            dut_id=anchor.metadata.dut_id,
            station_id=anchor.metadata.station_id,
            ammeter_name=anchor.ammeter_name,
            sampling_plan=anchor_run.plan,
            stop_reason=anchor_run.stop_reason,
            sample_count=anchor_run.sample_count,
            runs=points,
            metrics=metrics,
        )

    def _validate_cohort(
        self,
        cohort: tuple[ArchivedTestResult, ...],
    ) -> None:
        run_ids = tuple(item.run_id for item in cohort)
        if len(set(run_ids)) != len(run_ids):
            raise IncomparableHistoryError(
                "Each historical source run ID may appear only once"
            )
        completion_times = tuple(
            item.analyzed_result.sampling_result.completed_at_utc
            for item in cohort
        )
        if len(set(completion_times)) != len(completion_times):
            raise IncomparableHistoryError(
                "Historical runs require unique completion timestamps"
            )

        anchor = cohort[0]
        anchor_run = anchor.analyzed_result.sampling_result
        anchor_group = _consistency_group(anchor)
        for archived in cohort:
            try:
                validate_analyzed_result_semantics(archived.analyzed_result)
            except ResultArchiveCorruptionError as exc:
                raise IncomparableHistoryError(
                    f"Run {archived.run_id} contains inconsistent evidence"
                ) from exc
            run = archived.analyzed_result.sampling_result
            if run.sample_count < 2:
                raise IncomparableHistoryError(
                    "At least two samples per run are required to assess "
                    "within-run precision"
                )
            if archived.ammeter_name != anchor.ammeter_name:
                raise IncomparableHistoryError(
                    "Every historical run must use the same ammeter"
                )
            if archived.metadata.test_name != anchor.metadata.test_name:
                raise IncomparableHistoryError(
                    "Every historical run must use the same metadata test_name"
                )
            if _consistency_group(archived) != anchor_group:
                raise IncomparableHistoryError(
                    "Every historical run must use the same consistency_group"
                )
            if archived.metadata.dut_id != anchor.metadata.dut_id:
                raise IncomparableHistoryError(
                    "Every historical run must identify the same DUT"
                )
            if archived.metadata.station_id != anchor.metadata.station_id:
                raise IncomparableHistoryError(
                    "Every historical run must identify the same station"
                )
            if run.plan != anchor_run.plan:
                raise IncomparableHistoryError(
                    "Every historical run must use the same sampling plan"
                )
            if run.sample_count != anchor_run.sample_count:
                raise IncomparableHistoryError(
                    "Every historical run must contain the same sample count"
                )
            if run.stop_reason is not anchor_run.stop_reason:
                raise IncomparableHistoryError(
                    "Every historical run must have the same stop reason"
                )


def _consistency_group(archived: ArchivedTestResult) -> str:
    for key, value in archived.metadata.attributes:
        if key.casefold() == CONSISTENCY_GROUP_ATTRIBUTE:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or any(character in value for character in ("\x00", "\r", "\n"))
            ):
                raise IncomparableHistoryError(
                    "consistency_group metadata must be a clean non-empty string"
                )
            return value
    raise IncomparableHistoryError(
        "Every historical run requires a consistency_group metadata attribute"
    )
