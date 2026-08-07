"""Immutable Phase 7 policy, check, and verdict contracts."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace

from src.testing.acceptance import ResultEvaluator
from src.testing.acceptance_models import (
    AcceptanceCheck,
    AcceptanceLimits,
    AcceptanceMetric,
    AcceptancePolicy,
    AcceptanceVerdict,
    EvaluatedSamplingResult,
    VerdictStatus,
)
from src.testing.accuracy_models import ReferenceCurrent

from tests.test_phase6_support import analyzed_result


def _policy() -> AcceptancePolicy:
    return AcceptancePolicy(
        name="bench-current",
        version="1.0",
        reference=ReferenceCurrent(current_a=10.0, source="calibrator"),
        limits=AcceptanceLimits(
            minimum_current_a=9.0,
            maximum_current_a=11.0,
            maximum_absolute_bias_a=0.5,
            maximum_relative_error_percent=5.0,
            maximum_standard_deviation_a=1.0,
            maximum_start_lateness_seconds=0.1,
            maximum_acquisition_duration_seconds=0.1,
        ),
    )


class AcceptanceModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.analyzed = analyzed_result(
            (9.5, 10.5),
            ammeter_name="greenlee",
        )
        cls.verdict = ResultEvaluator().evaluate(
            cls.analyzed,
            policy=_policy(),
        )

    def test_complete_tree_is_frozen_slotted_and_json_ready(self) -> None:
        records = (
            self.verdict,
            self.verdict.policy,
            self.verdict.policy.limits,
            *self.verdict.checks,
        )
        for record in records:
            with self.subTest(record_type=type(record).__name__):
                self.assertFalse(hasattr(record, "__dict__"))
        json.dumps(self.verdict.to_dict(), allow_nan=False)
        with self.assertRaises(FrozenInstanceError):
            self.verdict.sample_count = 99  # type: ignore[misc]

    def test_status_and_counts_are_derived_from_checks(self) -> None:
        self.assertIs(self.verdict.status, VerdictStatus.PASS)
        self.assertEqual(self.verdict.passed_check_count, 7)
        self.assertEqual(self.verdict.failed_check_count, 0)
        failed_check = replace(
            self.verdict.checks[0],
            observed_value=8.0,
            passed=False,
        )
        failed = replace(
            self.verdict,
            checks=(failed_check, *self.verdict.checks[1:]),
        )
        self.assertIs(failed.status, VerdictStatus.FAIL)

    def test_limits_require_a_coherent_nonempty_set(self) -> None:
        with self.assertRaises(ValueError):
            AcceptanceLimits()
        with self.assertRaises(ValueError):
            AcceptanceLimits(minimum_current_a=2.0, maximum_current_a=1.0)
        with self.assertRaises(ValueError):
            AcceptanceLimits(maximum_standard_deviation_a=-0.1)

    def test_accuracy_limits_require_a_usable_reference(self) -> None:
        with self.assertRaises(ValueError):
            AcceptancePolicy(
                name="policy",
                version="1",
                limits=AcceptanceLimits(maximum_absolute_bias_a=1.0),
            )
        with self.assertRaises(ValueError):
            AcceptancePolicy(
                name="policy",
                version="1",
                reference=ReferenceCurrent(current_a=0.0, source="zero"),
                limits=AcceptanceLimits(
                    maximum_relative_error_percent=1.0,
                ),
            )

    def test_check_and_verdict_reject_forged_projection_fields(self) -> None:
        check = self.verdict.checks[0]
        with self.assertRaises(ValueError):
            replace(check, passed=not check.passed)
        with self.assertRaises(ValueError):
            replace(self.verdict, checks=self.verdict.checks[:-1])
        forged_limit = replace(
            check,
            limit_value=check.limit_value - 1.0,
            passed=True,
        )
        with self.assertRaises(ValueError):
            replace(
                self.verdict,
                checks=(forged_limit, *self.verdict.checks[1:]),
            )
        with self.assertRaises(ValueError):
            replace(self.verdict, source_run_id="not-a-uuid")

    def test_live_evaluated_result_preserves_evidence(self) -> None:
        combined = EvaluatedSamplingResult(
            analyzed_result=self.analyzed,
            verdict=self.verdict,
        )
        self.assertIs(combined.analyzed_result, self.analyzed)
        self.assertEqual(combined.to_dict()["verdict"]["status"], "pass")

    def test_metric_order_is_stable(self) -> None:
        self.assertEqual(
            tuple(check.metric for check in self.verdict.checks),
            (
                AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A,
                AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A,
                AcceptanceMetric.ABSOLUTE_BIAS_A,
                AcceptanceMetric.RELATIVE_ERROR_PERCENT,
                AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A,
                AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS,
                AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS,
            ),
        )


if __name__ == "__main__":
    unittest.main()
