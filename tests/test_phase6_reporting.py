"""Deterministic human-readable Phase 6 reporting tests."""

from __future__ import annotations

import unittest

from src.testing.accuracy import AccuracyAssessor
from src.testing.accuracy_models import ReferenceCurrent
from src.testing.reporting import format_reference_accuracy_report

from tests.test_phase6_support import representative_cohort


class AccuracyReportTests(unittest.TestCase):
    def test_report_contains_reference_metrics_ties_pairs_and_scope(self) -> None:
        assessment = AccuracyAssessor().assess(
            representative_cohort(),
            reference=ReferenceCurrent(
                current_a=10.0,
                source="calibrator",
                expanded_uncertainty_a=0.02,
                calibration_id="CAL-42",
            ),
        )

        report = format_reference_accuracy_report(assessment)

        self.assertEqual(
            report,
            "\n".join(
                (
                    "Reference-based ammeter accuracy assessment",
                    "Comparison group: bench-2026-08-06",
                    "Test: reference_accuracy",
                    (
                        "Reference: 10 A (calibrator), expanded uncertainty "
                        "+/- 0.02 A, calibration CAL-42"
                    ),
                    "Sampling: 2 samples at 10 Hz; stop=count_reached",
                    "",
                    (
                        "Ammeter | Mean (A) | Bias (A) | Abs error (A) | "
                        "Error (%) | Std dev (A) | RMSE (A) | Ranks A/P/R"
                    ),
                    "alpha | 10 | 0 | 0 | 0 | 1 | 1 | 1/3/2",
                    "bravo | 10.5 | 0.5 | 0.5 | 5 | 0 | 0.5 | 2/1/1",
                    "charlie | 9 | -1 | 1 | 10 | 0 | 1 | 3/1/2",
                    "",
                    "Winners (all exact ties retained)",
                    "  Most accurate: alpha",
                    "  Most precise: bravo, charlie",
                    "  Lowest reference RMSE: bravo",
                    "",
                    "Pairwise mean disagreement (second - first)",
                    "  bravo - alpha: 0.5 A (absolute 0.5 A, 5%)",
                    "  charlie - alpha: -1 A (absolute 1 A, 10%)",
                    "  charlie - bravo: -1.5 A (absolute 1.5 A, 15%)",
                    "",
                    (
                        "Scope: accuracy is relative to the supplied reference. "
                        "Reliability here means within-run reference fidelity "
                        "(RMSE), not failure rate or long-term reliability."
                    ),
                )
            ),
        )

    def test_zero_reference_is_reported_without_division_artifacts(self) -> None:
        assessment = AccuracyAssessor().assess(
            representative_cohort()[:2],
            reference=ReferenceCurrent(current_a=0.0, source="zero"),
        )

        report = format_reference_accuracy_report(assessment)

        self.assertIn("Reference: 0 A (zero)", report)
        self.assertIn("| n/a |", report)
        self.assertIn("n/a)", report)
        self.assertNotIn("n/a%", report)
        self.assertNotIn("nan", report.casefold())
        self.assertNotIn("inf", report.casefold())

    def test_report_requires_a_typed_assessment(self) -> None:
        with self.assertRaises(TypeError):
            format_reference_accuracy_report(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
