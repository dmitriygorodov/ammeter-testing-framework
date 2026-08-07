"""Pure, configuration-driven PASS/FAIL evaluation for Phase 7."""

from __future__ import annotations

import math

from src.utils.config import AcceptancePolicyConfig

from .acceptance_models import (
    AcceptanceCheck,
    AcceptanceLimits,
    AcceptanceMetric,
    AcceptancePolicy,
    AcceptanceVerdict,
    LimitComparison,
)
from .accuracy_models import ReferenceCurrent
from .archive_codec import validate_analyzed_result_semantics
from .archive_models import ArchivedTestResult
from .errors import AcceptanceEvaluationError, ResultArchiveCorruptionError
from .models import AnalyzedSamplingResult


class ResultEvaluator:
    """Evaluate trustworthy analyzed evidence against one explicit policy."""

    def evaluate(
        self,
        result: AnalyzedSamplingResult,
        *,
        policy: AcceptancePolicy,
        source_run_id: str | None = None,
    ) -> AcceptanceVerdict:
        if not isinstance(result, AnalyzedSamplingResult):
            raise TypeError("result must be AnalyzedSamplingResult")
        if not isinstance(policy, AcceptancePolicy):
            raise TypeError("policy must be AcceptancePolicy")
        try:
            validate_analyzed_result_semantics(result)
        except ResultArchiveCorruptionError as exc:
            raise AcceptanceEvaluationError(
                "Analyzed statistics do not match the sampling evidence"
            ) from exc

        observed = _observed_values(result, policy)
        checks = tuple(
            _build_check(metric, observed[metric], limit)
            for metric, limit in policy.limits.configured_values
        )
        return AcceptanceVerdict(
            ammeter_name=result.ammeter_name,
            sample_count=result.statistics.sample_count,
            policy=policy,
            checks=checks,
            source_run_id=source_run_id,
        )

    def evaluate_archived(
        self,
        archived: ArchivedTestResult,
        *,
        policy: AcceptancePolicy,
    ) -> AcceptanceVerdict:
        if not isinstance(archived, ArchivedTestResult):
            raise TypeError("archived must be ArchivedTestResult")
        return self.evaluate(
            archived.analyzed_result,
            policy=policy,
            source_run_id=archived.run_id,
        )


def acceptance_policy_from_config(
    config: AcceptancePolicyConfig,
) -> AcceptancePolicy:
    """Convert the validated configuration projection into a domain policy."""

    if not isinstance(config, AcceptancePolicyConfig):
        raise TypeError("config must be AcceptancePolicyConfig")
    reference = None
    if config.reference is not None:
        reference = ReferenceCurrent(
            current_a=config.reference.current_a,
            source=config.reference.source,
            expanded_uncertainty_a=(
                config.reference.expanded_uncertainty_a
            ),
            calibration_id=config.reference.calibration_id,
        )
    limits = config.limits
    return AcceptancePolicy(
        name=config.policy_name,
        version=config.policy_version,
        reference=reference,
        limits=AcceptanceLimits(
            minimum_current_a=limits.minimum_current_a,
            maximum_current_a=limits.maximum_current_a,
            maximum_absolute_bias_a=limits.maximum_absolute_bias_a,
            maximum_relative_error_percent=(
                limits.maximum_relative_error_percent
            ),
            maximum_standard_deviation_a=(
                limits.maximum_standard_deviation_a
            ),
            maximum_start_lateness_seconds=(
                limits.maximum_start_lateness_seconds
            ),
            maximum_acquisition_duration_seconds=(
                limits.maximum_acquisition_duration_seconds
            ),
        ),
    )


def _observed_values(
    result: AnalyzedSamplingResult,
    policy: AcceptancePolicy,
) -> dict[AcceptanceMetric, float]:
    statistics = result.statistics
    samples = result.sampling_result.samples
    requested = {
        metric for metric, _ in policy.limits.configured_values
    }
    observed: dict[AcceptanceMetric, float] = {}
    if AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A in requested:
        observed[AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A] = (
            statistics.minimum_current_a
        )
    if AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A in requested:
        observed[AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A] = (
            statistics.maximum_current_a
        )
    if AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A in requested:
        observed[AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A] = (
            statistics.standard_deviation_current_a
        )
    if AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS in requested:
        observed[AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS] = max(
            sample.start_lateness_seconds for sample in samples
        )
    if AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS in requested:
        observed[AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS] = max(
            sample.acquisition_duration_seconds for sample in samples
        )
    accuracy_requested = bool(
        requested
        & {
            AcceptanceMetric.ABSOLUTE_BIAS_A,
            AcceptanceMetric.RELATIVE_ERROR_PERCENT,
        }
    )
    if accuracy_requested and policy.reference is not None:
        bias = statistics.mean_current_a - policy.reference.current_a
        if not math.isfinite(bias):
            raise AcceptanceEvaluationError(
                "Reference bias is outside the finite float range"
            )
        absolute_bias = abs(bias)
        observed[AcceptanceMetric.ABSOLUTE_BIAS_A] = _normalize_zero(
            absolute_bias
        )
        if AcceptanceMetric.RELATIVE_ERROR_PERCENT in requested:
            relative_error = (
                absolute_bias / abs(policy.reference.current_a)
            ) * 100.0
            if not math.isfinite(relative_error):
                raise AcceptanceEvaluationError(
                    "Relative reference error is outside the finite float range"
                )
            observed[AcceptanceMetric.RELATIVE_ERROR_PERCENT] = (
                _normalize_zero(relative_error)
            )
        if AcceptanceMetric.ABSOLUTE_BIAS_A not in requested:
            observed.pop(AcceptanceMetric.ABSOLUTE_BIAS_A)
    return {metric: _normalize_zero(value) for metric, value in observed.items()}


def _build_check(
    metric: AcceptanceMetric,
    observed_value: float,
    limit_value: float,
) -> AcceptanceCheck:
    comparison = (
        LimitComparison.AT_LEAST
        if metric is AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A
        else LimitComparison.AT_MOST
    )
    passed = (
        observed_value >= limit_value
        if comparison is LimitComparison.AT_LEAST
        else observed_value <= limit_value
    )
    return AcceptanceCheck(
        metric=metric,
        observed_value=observed_value,
        limit_value=limit_value,
        passed=passed,
    )


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value
