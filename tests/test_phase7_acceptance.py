"""Pure Phase 7 full-precision acceptance evaluation tests."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace

from src.testing.acceptance import ResultEvaluator
from src.testing.acceptance_models import (
    AcceptanceLimits,
    AcceptanceMetric,
    AcceptancePolicy,
    VerdictStatus,
)
from src.testing.accuracy_models import ReferenceCurrent
from src.testing.errors import AcceptanceEvaluationError

from tests.test_phase6_support import analyzed_result, archived_result


class ResultEvaluatorTests(unittest.TestCase):
    def test_inclusive_boundaries_pass_without_rounding(self) -> None:
        result = analyzed_result((9.0, 11.0), ammeter_name="greenlee")
        policy = AcceptancePolicy(
            name="boundary",
            version="1",
            reference=ReferenceCurrent(current_a=10.0, source="setpoint"),
            limits=AcceptanceLimits(
                minimum_current_a=9.0,
                maximum_current_a=11.0,
                maximum_absolute_bias_a=0.0,
                maximum_relative_error_percent=0.0,
                maximum_standard_deviation_a=1.0,
            ),
        )

        verdict = ResultEvaluator().evaluate(result, policy=policy)

        self.assertIs(verdict.status, VerdictStatus.PASS)
        self.assertTrue(all(check.passed for check in verdict.checks))

    def test_each_failed_check_is_retained_and_aggregates_to_fail(self) -> None:
        result = analyzed_result((8.0, 12.0), ammeter_name="greenlee")
        policy = AcceptancePolicy(
            name="strict",
            version="2",
            reference=ReferenceCurrent(current_a=10.5, source="setpoint"),
            limits=AcceptanceLimits(
                minimum_current_a=9.0,
                maximum_current_a=11.0,
                maximum_absolute_bias_a=0.1,
                maximum_relative_error_percent=0.5,
                maximum_standard_deviation_a=1.0,
                maximum_start_lateness_seconds=0.0,
                maximum_acquisition_duration_seconds=0.001,
            ),
        )

        verdict = ResultEvaluator().evaluate(result, policy=policy)

        self.assertIs(verdict.status, VerdictStatus.FAIL)
        failed = {check.metric for check in verdict.checks if not check.passed}
        self.assertEqual(
            failed,
            {
                AcceptanceMetric.OBSERVED_MINIMUM_CURRENT_A,
                AcceptanceMetric.OBSERVED_MAXIMUM_CURRENT_A,
                AcceptanceMetric.ABSOLUTE_BIAS_A,
                AcceptanceMetric.RELATIVE_ERROR_PERCENT,
                AcceptanceMetric.STANDARD_DEVIATION_CURRENT_A,
                AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS,
            },
        )

    def test_sub_display_precision_violation_still_fails(self) -> None:
        result = analyzed_result((10.0000000001,), ammeter_name="greenlee")
        policy = AcceptancePolicy(
            name="precision",
            version="1",
            reference=ReferenceCurrent(current_a=10.0, source="setpoint"),
            limits=AcceptanceLimits(maximum_absolute_bias_a=0.00000000005),
        )

        verdict = ResultEvaluator().evaluate(result, policy=policy)

        self.assertIs(verdict.status, VerdictStatus.FAIL)
        self.assertGreater(
            verdict.checks[0].observed_value,
            verdict.checks[0].limit_value,
        )

    def test_timing_checks_use_worst_observed_sample(self) -> None:
        result = analyzed_result(
            (10.0, 10.0),
            ammeter_name="greenlee",
            completion_offsets=(0.02, 0.25),
        )
        policy = AcceptancePolicy(
            name="timing",
            version="1",
            limits=AcceptanceLimits(
                maximum_start_lateness_seconds=0.0,
                maximum_acquisition_duration_seconds=0.1,
            ),
        )

        verdict = ResultEvaluator().evaluate(result, policy=policy)

        observed = {check.metric: check.observed_value for check in verdict.checks}
        self.assertEqual(
            observed[AcceptanceMetric.MAXIMUM_START_LATENESS_SECONDS],
            0.0,
        )
        self.assertAlmostEqual(
            observed[
                AcceptanceMetric.MAXIMUM_ACQUISITION_DURATION_SECONDS
            ],
            0.15,
        )

    def test_forged_statistics_are_rejected_before_decision(self) -> None:
        result = analyzed_result((10.0, 11.0), ammeter_name="greenlee")
        forged = replace(
            result,
            statistics=replace(result.statistics, mean_current_a=10.6),
        )
        policy = AcceptancePolicy(
            name="policy",
            version="1",
            limits=AcceptanceLimits(maximum_current_a=20.0),
        )

        with self.assertRaises(AcceptanceEvaluationError):
            ResultEvaluator().evaluate(forged, policy=policy)

    def test_reference_arithmetic_overflow_is_typed(self) -> None:
        result = analyzed_result(
            (sys.float_info.max,),
            ammeter_name="greenlee",
        )
        policy = AcceptancePolicy(
            name="overflow",
            version="1",
            reference=ReferenceCurrent(
                current_a=-sys.float_info.max,
                source="setpoint",
            ),
            limits=AcceptanceLimits(maximum_absolute_bias_a=1.0),
        )

        with self.assertRaises(AcceptanceEvaluationError):
            ResultEvaluator().evaluate(result, policy=policy)

    def test_unused_reference_math_cannot_break_a_range_only_policy(self) -> None:
        result = analyzed_result(
            (sys.float_info.max,),
            ammeter_name="greenlee",
        )
        policy = AcceptancePolicy(
            name="range-only",
            version="1",
            reference=ReferenceCurrent(
                current_a=-sys.float_info.max,
                source="unused by this policy",
            ),
            limits=AcceptanceLimits(maximum_current_a=sys.float_info.max),
        )

        verdict = ResultEvaluator().evaluate(result, policy=policy)

        self.assertIs(verdict.status, VerdictStatus.PASS)

    def test_archived_evaluation_links_the_source_run(self) -> None:
        archived = archived_result(
            (10.0,),
            ammeter_name="greenlee",
            run_number=77,
        )
        policy = AcceptancePolicy(
            name="archive",
            version="1",
            limits=AcceptanceLimits(maximum_current_a=10.0),
        )

        verdict = ResultEvaluator().evaluate_archived(
            archived,
            policy=policy,
        )

        self.assertEqual(verdict.source_run_id, archived.run_id)


if __name__ == "__main__":
    unittest.main()
