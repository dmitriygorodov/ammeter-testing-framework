"""Human-readable reporting for immutable testing results."""

from __future__ import annotations

from .acceptance_models import AcceptanceMetric, AcceptanceVerdict, LimitComparison
from .accuracy_models import ReferenceAccuracyAssessment
from .consistency_models import HistoricalConsistencyAssessment


_ACCEPTANCE_METRIC_LABELS = {
    AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A: "Observed minimum current",
    AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A: "Observed maximum current",
    AcceptanceMetric.ABSOLUTE_BIAS_A: "Absolute mean bias",
    AcceptanceMetric.RELATIVE_ERROR_PERCENT: "Relative mean error",
    AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A: "Population standard deviation",
    AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS: "Maximum start lateness",
    AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS: (
        "Maximum acquisition duration"
    ),
}


def format_acceptance_verdict(verdict: AcceptanceVerdict) -> str:
    """Render a deterministic, audit-friendly Phase 7 verdict report."""

    if not isinstance(verdict, AcceptanceVerdict):
        raise TypeError("verdict must be AcceptanceVerdict")
    lines = [
        f"{verdict.status.value.upper()} - ammeter acceptance verdict",
        f"Ammeter: {verdict.ammeter_name}",
        f"Samples: {verdict.sample_count}",
        f"Policy: {verdict.policy.identifier}",
    ]
    if verdict.source_run_id is not None:
        lines.append(f"Archived run: {verdict.source_run_id}")
    reference = verdict.policy.reference
    if reference is not None:
        reference_line = (
            f"Reference: {_number(reference.current_a)} A "
            f"({reference.source})"
        )
        if reference.expanded_uncertainty_a is not None:
            reference_line += (
                ", expanded uncertainty +/- "
                f"{_number(reference.expanded_uncertainty_a)} A"
            )
        if reference.calibration_id is not None:
            reference_line += f", calibration {reference.calibration_id}"
        lines.append(reference_line)
    lines.extend(("", "Result | Check | Observed | Requirement"))
    for check in verdict.checks:
        operator = (
            ">="
            if check.comparison is LimitComparison.AT_LEAST
            else "<="
        )
        unit_suffix = "%" if check.unit == "%" else f" {check.unit}"
        observed = f"{_number(check.observed_value)}{unit_suffix}"
        requirement = f"{operator} {_number(check.limit_value)}{unit_suffix}"
        lines.append(
            " | ".join(
                (
                    "PASS" if check.passed else "FAIL",
                    _ACCEPTANCE_METRIC_LABELS[check.metric],
                    observed,
                    requirement,
                )
            )
        )
    lines.extend(
        (
            "",
            (
                f"Summary: {verdict.passed_check_count} passed, "
                f"{verdict.failed_check_count} failed"
            ),
            (
                "Scope: PASS/FAIL represents valid evidence compared at full "
                "precision with inclusive limits. Execution and configuration "
                "errors do not produce a verdict."
            ),
        )
    )
    return "\n".join(lines)


def format_historical_consistency_report(
    assessment: HistoricalConsistencyAssessment,
) -> str:
    """Render a deterministic Phase 8 stability and drift report."""

    if not isinstance(assessment, HistoricalConsistencyAssessment):
        raise TypeError("assessment must be HistoricalConsistencyAssessment")
    metrics = assessment.metrics
    lines = [
        "Historical ammeter performance consistency",
        f"Ammeter: {assessment.ammeter_name}",
        f"Consistency group: {assessment.consistency_group}",
        f"Test: {assessment.test_name}",
        f"DUT: {assessment.dut_id or 'n/a'}",
        f"Station: {assessment.station_id or 'n/a'}",
        (
            f"Series: {assessment.run_count} runs, "
            f"{assessment.sample_count} samples/run, "
            f"span={_number(assessment.time_span_seconds / 3600.0)} hours"
        ),
        "",
        "Completed UTC | Run ID | Mean (A) | Std dev (A) | Mean step (A)",
    ]
    previous_mean: float | None = None
    for run in assessment.runs:
        current_mean = run.statistics.mean_current_a
        step = (
            "n/a"
            if previous_mean is None
            else _number(current_mean - previous_mean)
        )
        lines.append(
            " | ".join(
                (
                    run.completed_at_utc.isoformat().replace("+00:00", "Z"),
                    run.run_id,
                    _number(current_mean),
                    _number(run.statistics.standard_deviation_current_a),
                    step,
                )
            )
        )
        previous_mean = current_mean
    lines.extend(
        (
            "",
            "Consistency metrics",
            f"  Mean of run means: {_number(metrics.mean_of_run_means_a)} A",
            (
                "  Run-to-run standard deviation: "
                f"{_number(metrics.run_to_run_standard_deviation_a)} A"
            ),
            (
                "  Run-mean range: "
                f"{_number(metrics.minimum_run_mean_a)} to "
                f"{_number(metrics.maximum_run_mean_a)} A"
            ),
            (
                "  Peak-to-peak run mean: "
                f"{_number(metrics.peak_to_peak_run_mean_a)} A"
            ),
            (
                "  Maximum absolute adjacent change: "
                f"{_number(metrics.maximum_absolute_step_change_a)} A"
            ),
            (
                "  Mean within-run standard deviation: "
                f"{_number(metrics.mean_within_run_standard_deviation_a)} A"
            ),
            (
                "  Pooled within-run standard deviation: "
                f"{_number(metrics.pooled_within_run_standard_deviation_a)} A"
            ),
            (
                "  Run-to-run coefficient of variation: "
                f"{_relative_percent(metrics.coefficient_of_variation_percent)}"
            ),
            (
                "  Least-squares trend: "
                f"{_number(metrics.trend_slope_a_per_hour)} A/hour"
            ),
            (
                "  Fitted change across series: "
                f"{_number(metrics.fitted_trend_change_a)} A"
            ),
            "",
            (
                "Scope: consistency describes repeatability and time trend for "
                "like-for-like successful runs. It does not establish accuracy, "
                "calibration validity, or operational failure rate. Trend timing "
                "assumes trustworthy station UTC timestamps."
            ),
        )
    )
    return "\n".join(lines)


def format_reference_accuracy_report(
    assessment: ReferenceAccuracyAssessment,
) -> str:
    """Render a deterministic plain-text Phase 6 assessment report."""

    if not isinstance(assessment, ReferenceAccuracyAssessment):
        raise TypeError("assessment must be ReferenceAccuracyAssessment")

    reference = assessment.reference
    reference_line = (
        f"Reference: {_number(reference.current_a)} A "
        f"({reference.source})"
    )
    if reference.expanded_uncertainty_a is not None:
        reference_line += (
            f", expanded uncertainty +/- "
            f"{_number(reference.expanded_uncertainty_a)} A"
        )
    if reference.calibration_id is not None:
        reference_line += f", calibration {reference.calibration_id}"

    lines = [
        "Reference-based ammeter accuracy assessment",
        f"Comparison group: {assessment.comparison_group}",
        f"Test: {assessment.test_name}",
        reference_line,
        (
            f"Sampling: {assessment.sample_count} samples at "
            f"{_number(assessment.sampling_plan.sampling_frequency_hz)} Hz; "
            f"stop={assessment.stop_reason.value}"
        ),
        "",
        (
            "Ammeter | Mean (A) | Bias (A) | Abs error (A) | Error (%) | "
            "Std dev (A) | RMSE (A) | Ranks A/P/R"
        ),
    ]
    for item in assessment.ammeters:
        lines.append(
            " | ".join(
                (
                    item.ammeter_name,
                    _number(item.mean_current_a),
                    _number(item.signed_bias_a),
                    _number(item.absolute_error_a),
                    _optional_number(item.relative_error_percent),
                    _number(item.standard_deviation_current_a),
                    _number(item.root_mean_square_error_a),
                    (
                        f"{item.accuracy_rank}/"
                        f"{item.precision_rank}/"
                        f"{item.reliability_rank}"
                    ),
                )
            )
        )

    lines.extend(
        (
            "",
            "Winners (all exact ties retained)",
            "  Most accurate: "
            + ", ".join(assessment.most_accurate_ammeters),
            "  Most precise: "
            + ", ".join(assessment.most_precise_ammeters),
            "  Lowest reference RMSE: "
            + ", ".join(assessment.most_reliable_ammeters),
            "",
            "Pairwise mean disagreement (second - first)",
        )
    )
    for pair in assessment.pairwise_agreements:
        lines.append(
            f"  {pair.second_ammeter_name} - {pair.first_ammeter_name}: "
            f"{_number(pair.signed_mean_difference_a)} A "
            f"(absolute {_number(pair.absolute_mean_difference_a)} A, "
            f"{_relative_percent(pair.relative_difference_percent)})"
        )
    lines.extend(
        (
            "",
            (
                "Scope: accuracy is relative to the supplied reference. "
                "Reliability here means within-run reference fidelity "
                "(RMSE), not failure rate or long-term reliability."
            ),
        )
    )
    return "\n".join(lines)


def _number(value: float) -> str:
    return f"{value:.12g}"


def _relative_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{_number(value)}%"


def _optional_number(value: float | None) -> str:
    return "n/a" if value is None else _number(value)
