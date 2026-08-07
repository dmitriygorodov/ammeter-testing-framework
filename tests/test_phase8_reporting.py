"""Deterministic Phase 8 historical consistency reporting."""

from __future__ import annotations

import unittest

from src.testing.consistency import HistoricalConsistencyAnalyzer
from src.testing.reporting import format_historical_consistency_report

from tests.test_phase8_support import historical_run, representative_history


class HistoricalConsistencyReportingTests(unittest.TestCase):
    def test_report_contains_chronology_metrics_and_scope(self) -> None:
        assessment = HistoricalConsistencyAnalyzer().assess(
            representative_history()
        )

        report = format_historical_consistency_report(assessment)

        self.assertTrue(
            report.startswith("Historical ammeter performance consistency")
        )
        self.assertIn("Consistency group: bench-stability-2026", report)
        self.assertIn("Series: 3 runs, 2 samples/run, span=2 hours", report)
        self.assertIn("Run-to-run standard deviation:", report)
        self.assertIn("Least-squares trend: 1 A/hour", report)
        self.assertIn("Fitted change across series: 2 A", report)
        self.assertIn("does not establish accuracy", report)
        positions = [report.index(run.run_id) for run in assessment.runs]
        self.assertEqual(positions, sorted(positions))

    def test_zero_mean_relative_metric_renders_na_without_percent_suffix(self) -> None:
        assessment = HistoricalConsistencyAnalyzer().assess(
            (
                historical_run((-1.0, -1.0), run_number=1, elapsed_hours=0),
                historical_run((0.0, 0.0), run_number=2, elapsed_hours=1),
                historical_run((1.0, 1.0), run_number=3, elapsed_hours=2),
            )
        )

        report = format_historical_consistency_report(assessment)

        self.assertIn("Run-to-run coefficient of variation: n/a", report)
        self.assertNotIn("n/a%", report)

    def test_report_rejects_other_objects(self) -> None:
        with self.assertRaises(TypeError):
            format_historical_consistency_report(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
