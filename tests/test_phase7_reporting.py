"""Deterministic Phase 7 human-readable reporting tests."""

from __future__ import annotations

import unittest

from src.testing.acceptance import ResultEvaluator
from src.testing.acceptance_models import AcceptanceLimits, AcceptancePolicy
from src.testing.accuracy_models import ReferenceCurrent
from src.testing.reporting import format_acceptance_verdict

from tests.test_phase6_support import analyzed_result, archived_result


class AcceptanceReportingTests(unittest.TestCase):
    def test_report_contains_policy_reference_checks_and_failure_summary(self) -> None:
        archived = archived_result(
            (9.0, 11.0),
            ammeter_name="greenlee",
            run_number=99,
        )
        policy = AcceptancePolicy(
            name="bench-current",
            version="3",
            reference=ReferenceCurrent(
                current_a=10.5,
                source="Fluke setpoint",
                expanded_uncertainty_a=0.01,
                calibration_id="CAL-99",
            ),
            limits=AcceptanceLimits(
                maximum_absolute_bias_a=0.1,
                maximum_standard_deviation_a=1.0,
            ),
        )
        verdict = ResultEvaluator().evaluate_archived(
            archived,
            policy=policy,
        )

        report = format_acceptance_verdict(verdict)

        self.assertTrue(report.startswith("FAIL - ammeter acceptance verdict"))
        self.assertIn("Policy: bench-current@3", report)
        self.assertIn(f"Archived run: {archived.run_id}", report)
        self.assertIn("Fluke setpoint", report)
        self.assertIn("calibration CAL-99", report)
        self.assertIn("FAIL | Absolute mean bias", report)
        self.assertIn("Summary: 1 passed, 1 failed", report)
        self.assertIn("Execution and configuration errors do not produce", report)

    def test_report_rejects_other_objects(self) -> None:
        with self.assertRaises(TypeError):
            format_acceptance_verdict(object())  # type: ignore[arg-type]

    def test_live_report_omits_archive_line(self) -> None:
        result = analyzed_result((1.0,), ammeter_name="greenlee")
        verdict = ResultEvaluator().evaluate(
            result,
            policy=AcceptancePolicy(
                name="range",
                version="1",
                limits=AcceptanceLimits(maximum_current_a=1.0),
            ),
        )

        report = format_acceptance_verdict(verdict)

        self.assertTrue(report.startswith("PASS"))
        self.assertNotIn("Archived run:", report)


if __name__ == "__main__":
    unittest.main()
