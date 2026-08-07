"""Immutable configuration and verdict records for Phase 7."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .accuracy_models import ReferenceCurrent
from .archive_models import require_canonical_run_id
from .models import AnalyzedSamplingResult


class LimitComparison(str, Enum):
    """Inclusive comparison applied by an acceptance check."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


class AcceptanceMetric(str, Enum):
    """Stable identifiers for supported Phase 7 acceptance checks."""

    OBSERVED_MINIMUM_CURRENT_A = "observed_minimum_current_a"
    OBSERVED_MAXIMUM_CURRENT_A = "observed_maximum_current_a"
    ABSOLUTE_BIAS_A = "absolute_bias_a"
    RELATIVE_ERROR_PERCENT = "relative_error_percent"
    STANDARD_DEVIATION_CURRENT_A = "standard_deviation_current_a"
    MAXIMUM_START_LATENESS_SECONDS = "maximum_start_lateness_seconds"
    MAXIMUM_ACQUISITION_DURATION_SECONDS = (
        "maximum_acquisition_duration_seconds"
    )


_METRIC_COMPARISONS = {
    AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A: LimitComparison.AT_LEAST,
    AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A: LimitComparison.AT_MOST,
    AcceptanceMetric.ABSOLUTE_BIAS_A: LimitComparison.AT_MOST,
    AcceptanceMetric.RELATIVE_ERROR_PERCENT: LimitComparison.AT_MOST,
    AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A: LimitComparison.AT_MOST,
    AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS: LimitComparison.AT_MOST,
    AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS: (
        LimitComparison.AT_MOST
    ),
}

_METRIC_UNITS = {
    AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A: "A",
    AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A: "A",
    AcceptanceMetric.ABSOLUTE_BIAS_A: "A",
    AcceptanceMetric.RELATIVE_ERROR_PERCENT: "%",
    AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A: "A",
    AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS: "s",
    AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS: "s",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptanceLimits:
    """Optional inclusive limits enabled by one acceptance policy."""

    minimum_current_a: float | None = None
    maximum_current_a: float | None = None
    maximum_absolute_bias_a: float | None = None
    maximum_relative_error_percent: float | None = None
    maximum_standard_deviation_a: float | None = None
    maximum_start_lateness_seconds: float | None = None
    maximum_acquisition_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("minimum_current_a", "maximum_current_a"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _finite_number(value, field_name),
                )
        for field_name in (
            "maximum_absolute_bias_a",
            "maximum_relative_error_percent",
            "maximum_standard_deviation_a",
            "maximum_start_lateness_seconds",
            "maximum_acquisition_duration_seconds",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _nonnegative_finite_number(value, field_name),
                )
        if (
            self.minimum_current_a is not None
            and self.maximum_current_a is not None
            and self.minimum_current_a > self.maximum_current_a
        ):
            raise ValueError(
                "minimum_current_a must not exceed maximum_current_a"
            )
        if not self.configured_values:
            raise ValueError("An acceptance policy requires at least one limit")

    @property
    def configured_values(self) -> tuple[tuple[AcceptanceMetric, float], ...]:
        configured: list[tuple[AcceptanceMetric, float]] = []
        fields = (
            (
                AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A,
                self.minimum_current_a,
            ),
            (
                AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A,
                self.maximum_current_a,
            ),
            (AcceptanceMetric.ABSOLUTE_BIAS_A, self.maximum_absolute_bias_a),
            (
                AcceptanceMetric.RELATIVE_ERROR_PERCENT,
                self.maximum_relative_error_percent,
            ),
            (
                AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A,
                self.maximum_standard_deviation_a,
            ),
            (
                AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS,
                self.maximum_start_lateness_seconds,
            ),
            (
                AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS,
                self.maximum_acquisition_duration_seconds,
            ),
        )
        for metric, value in fields:
            if value is not None:
                configured.append((metric, value))
        return tuple(configured)

    def to_dict(self) -> dict[str, float | None]:
        return {
            "minimum_current_a": self.minimum_current_a,
            "maximum_current_a": self.maximum_current_a,
            "maximum_absolute_bias_a": self.maximum_absolute_bias_a,
            "maximum_relative_error_percent": (
                self.maximum_relative_error_percent
            ),
            "maximum_standard_deviation_a": (
                self.maximum_standard_deviation_a
            ),
            "maximum_start_lateness_seconds": (
                self.maximum_start_lateness_seconds
            ),
            "maximum_acquisition_duration_seconds": (
                self.maximum_acquisition_duration_seconds
            ),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptancePolicy:
    """Named, versioned limits and optional traceable current reference."""

    name: str
    version: str
    limits: AcceptanceLimits
    reference: ReferenceCurrent | None = None

    def __post_init__(self) -> None:
        _clean_text(self.name, "name")
        _clean_text(self.version, "version")
        if not isinstance(self.limits, AcceptanceLimits):
            raise TypeError("limits must be AcceptanceLimits")
        if self.reference is not None and not isinstance(
            self.reference,
            ReferenceCurrent,
        ):
            raise TypeError("reference must be ReferenceCurrent or None")
        accuracy_limits_enabled = (
            self.limits.maximum_absolute_bias_a is not None
            or self.limits.maximum_relative_error_percent is not None
        )
        if accuracy_limits_enabled and self.reference is None:
            raise ValueError(
                "Bias and relative-error limits require an explicit reference"
            )
        if (
            self.limits.maximum_relative_error_percent is not None
            and self.reference is not None
            and self.reference.current_a == 0.0
        ):
            raise ValueError(
                "A relative-error limit requires a nonzero reference current"
            )

    @property
    def identifier(self) -> str:
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "identifier": self.identifier,
            "reference": (
                None if self.reference is None else self.reference.to_dict()
            ),
            "limits": self.limits.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptanceCheck:
    """One full-precision observed value compared with one policy limit."""

    metric: AcceptanceMetric
    observed_value: float
    limit_value: float
    passed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.metric, AcceptanceMetric):
            raise TypeError("metric must be AcceptanceMetric")
        observed = _finite_number(self.observed_value, "observed_value")
        limit = _finite_number(self.limit_value, "limit_value")
        object.__setattr__(self, "observed_value", observed)
        object.__setattr__(self, "limit_value", limit)
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a bool")
        expected = (
            observed >= limit
            if self.comparison is LimitComparison.AT_LEAST
            else observed <= limit
        )
        if self.passed is not expected:
            raise ValueError("passed does not match the inclusive comparison")

    @property
    def comparison(self) -> LimitComparison:
        return _METRIC_COMPARISONS[self.metric]

    @property
    def unit(self) -> str:
        return _METRIC_UNITS[self.metric]

    def to_dict(self) -> dict[str, str | float | bool]:
        return {
            "metric": self.metric.value,
            "observed_value": self.observed_value,
            "limit_value": self.limit_value,
            "comparison": self.comparison.value,
            "unit": self.unit,
            "passed": self.passed,
        }


class VerdictStatus(str, Enum):
    """Possible outcomes for valid, fully evaluated evidence."""

    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptanceVerdict:
    """Aggregate PASS/FAIL result for one valid analyzed sampling run."""

    ammeter_name: str
    sample_count: int
    policy: AcceptancePolicy
    checks: tuple[AcceptanceCheck, ...]
    source_run_id: str | None = None

    def __post_init__(self) -> None:
        _clean_text(self.ammeter_name, "ammeter_name")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count <= 0
        ):
            raise ValueError("sample_count must be a positive integer")
        if not isinstance(self.policy, AcceptancePolicy):
            raise TypeError("policy must be AcceptancePolicy")
        if not isinstance(self.checks, tuple) or not self.checks:
            raise ValueError("checks must be a non-empty tuple")
        if not all(isinstance(check, AcceptanceCheck) for check in self.checks):
            raise TypeError("checks must contain AcceptanceCheck records")
        expected_items = self.policy.limits.configured_values
        expected_metrics = tuple(metric for metric, _ in expected_items)
        actual_metrics = tuple(check.metric for check in self.checks)
        if actual_metrics != expected_metrics:
            raise ValueError(
                "checks must match the policy limits in canonical order"
            )
        if any(
            check.limit_value != expected_limit
            for check, (_, expected_limit) in zip(self.checks, expected_items)
        ):
            raise ValueError("check limits must exactly match the policy")
        if self.source_run_id is not None:
            require_canonical_run_id(self.source_run_id)

    @property
    def status(self) -> VerdictStatus:
        return (
            VerdictStatus.PASS
            if all(check.passed for check in self.checks)
            else VerdictStatus.FAIL
        )

    @property
    def passed_check_count(self) -> int:
        return sum(check.passed for check in self.checks)

    @property
    def failed_check_count(self) -> int:
        return len(self.checks) - self.passed_check_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "ammeter_name": self.ammeter_name,
            "sample_count": self.sample_count,
            "source_run_id": self.source_run_id,
            "policy": self.policy.to_dict(),
            "passed_check_count": self.passed_check_count,
            "failed_check_count": self.failed_check_count,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluatedSamplingResult:
    """Complete analyzed evidence paired with its Phase 7 verdict."""

    analyzed_result: AnalyzedSamplingResult
    verdict: AcceptanceVerdict

    def __post_init__(self) -> None:
        if not isinstance(self.analyzed_result, AnalyzedSamplingResult):
            raise TypeError("analyzed_result must be AnalyzedSamplingResult")
        if not isinstance(self.verdict, AcceptanceVerdict):
            raise TypeError("verdict must be AcceptanceVerdict")
        if self.verdict.source_run_id is not None:
            raise ValueError("A live evaluated result must not claim an archive ID")
        if self.verdict.ammeter_name != self.analyzed_result.ammeter_name:
            raise ValueError("verdict and evidence must identify the same ammeter")
        if (
            self.verdict.sample_count
            != self.analyzed_result.statistics.sample_count
        ):
            raise ValueError("verdict sample_count must match the evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzed_result": self.analyzed_result.to_dict(),
            "verdict": self.verdict.to_dict(),
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
