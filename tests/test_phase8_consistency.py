"""Pure Phase 8 historical consistency analysis tests."""

from __future__ import annotations

import math
import sys
import unittest
from dataclasses import replace

from src.testing.consistency import HistoricalConsistencyAnalyzer
from src.testing.errors import ConsistencyAnalysisError, IncomparableHistoryError
from tests.test_phase8_support import historical_run, representative_history


class HistoricalConsistencyAnalyzerTests(unittest.TestCase):
    def test_known_linear_history_produces_expected_metrics(self) -> None:
        assessment = HistoricalConsistencyAnalyzer().assess(
            representative_history()
        )
        metrics = assessment.metrics

        self.assertEqual(metrics.mean_of_run_means_a, 11.0)
        self.assertAlmostEqual(
            metrics.run_to_run_standard_deviation_a,
            math.sqrt(2.0 / 3.0),
        )
        self.assertEqual(metrics.minimum_run_mean_a, 10.0)
        self.assertEqual(metrics.maximum_run_mean_a, 12.0)
        self.assertEqual(metrics.peak_to_peak_run_mean_a, 2.0)
        self.assertEqual(metrics.maximum_absolute_step_change_a, 1.0)
        self.assertEqual(metrics.mean_within_run_standard_deviation_a, 1.0)
        self.assertEqual(metrics.pooled_within_run_standard_deviation_a, 1.0)
        self.assertAlmostEqual(
            metrics.coefficient_of_variation_percent,
            math.sqrt(2.0 / 3.0) / 11.0 * 100.0,
        )
        self.assertAlmostEqual(metrics.trend_slope_a_per_hour, 1.0)
        self.assertAlmostEqual(metrics.fitted_trend_change_a, 2.0)

    def test_pooled_within_run_precision_is_rms_not_arithmetic_mean(self) -> None:
        history = (
            historical_run((10.0, 10.0), run_number=11, elapsed_hours=0),
            historical_run((9.0, 11.0), run_number=12, elapsed_hours=1),
            historical_run((8.0, 12.0), run_number=13, elapsed_hours=2),
        )

        metrics = HistoricalConsistencyAnalyzer().assess(history).metrics

        self.assertEqual(metrics.mean_within_run_standard_deviation_a, 1.0)
        self.assertAlmostEqual(
            metrics.pooled_within_run_standard_deviation_a,
            math.sqrt(5.0 / 3.0),
        )
        self.assertEqual(metrics.run_to_run_standard_deviation_a, 0.0)
        self.assertEqual(metrics.trend_slope_a_per_hour, 0.0)

    def test_input_permutation_is_chronologically_deterministic(self) -> None:
        history = representative_history()
        forward = HistoricalConsistencyAnalyzer().assess(history)
        shuffled = HistoricalConsistencyAnalyzer().assess(
            (history[2], history[0], history[1])
        )

        self.assertEqual(forward, shuffled)
        self.assertEqual(
            tuple(run.run_id for run in shuffled.runs),
            tuple(run.run_id for run in history),
        )

    def test_irregular_timestamps_use_least_squares_elapsed_time(self) -> None:
        history = (
            historical_run((0.0, 0.0), run_number=1, elapsed_hours=0.0),
            historical_run((1.0, 1.0), run_number=2, elapsed_hours=1.0),
            historical_run((3.0, 3.0), run_number=3, elapsed_hours=3.0),
        )

        assessment = HistoricalConsistencyAnalyzer().assess(history)

        self.assertAlmostEqual(assessment.metrics.trend_slope_a_per_hour, 1.0)
        self.assertAlmostEqual(assessment.metrics.fitted_trend_change_a, 3.0)

    def test_zero_grand_mean_omits_relative_variation(self) -> None:
        history = (
            historical_run((-1.0, -1.0), run_number=1, elapsed_hours=0.0),
            historical_run((0.0, 0.0), run_number=2, elapsed_hours=1.0),
            historical_run((1.0, 1.0), run_number=3, elapsed_hours=2.0),
        )

        assessment = HistoricalConsistencyAnalyzer().assess(history)

        self.assertEqual(assessment.metrics.mean_of_run_means_a, 0.0)
        self.assertIsNone(
            assessment.metrics.coefficient_of_variation_percent
        )

    def test_metric_overflow_is_typed(self) -> None:
        maximum = sys.float_info.max
        history = (
            historical_run((-maximum, -maximum), run_number=1, elapsed_hours=0),
            historical_run((0.0, 0.0), run_number=2, elapsed_hours=1),
            historical_run((maximum, maximum), run_number=3, elapsed_hours=2),
        )

        with self.assertRaises(ConsistencyAnalysisError):
            HistoricalConsistencyAnalyzer().assess(history)

    def test_requires_three_typed_distinct_runs(self) -> None:
        history = representative_history()
        with self.assertRaises(IncomparableHistoryError):
            HistoricalConsistencyAnalyzer().assess(history[:2])
        with self.assertRaises(IncomparableHistoryError):
            HistoricalConsistencyAnalyzer().assess(
                (history[0], history[0], history[2])
            )
        with self.assertRaises(TypeError):
            HistoricalConsistencyAnalyzer().assess(
                (history[0], history[1], object())  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            HistoricalConsistencyAnalyzer().assess("not runs")  # type: ignore[arg-type]

    def test_requires_unique_completion_timestamps(self) -> None:
        history = representative_history()
        duplicate_time_result = historical_run(
            (12.0, 14.0),
            run_number=104,
            elapsed_hours=1.0,
        )

        with self.assertRaises(IncomparableHistoryError):
            HistoricalConsistencyAnalyzer().assess(
                (history[0], history[1], duplicate_time_result)
            )

    def test_rejects_every_like_for_like_mismatch(self) -> None:
        base = representative_history()
        anchor, middle, _ = base
        mismatches = {
            "ammeter": historical_run(
                (11.0, 13.0),
                run_number=201,
                elapsed_hours=2,
                ammeter_name="entes",
            ),
            "group": historical_run(
                (11.0, 13.0),
                run_number=202,
                elapsed_hours=2,
                consistency_group="different",
            ),
            "test": historical_run(
                (11.0, 13.0),
                run_number=203,
                elapsed_hours=2,
                test_name="different",
            ),
            "dut": historical_run(
                (11.0, 13.0),
                run_number=204,
                elapsed_hours=2,
                dut_id="different",
            ),
            "station": historical_run(
                (11.0, 13.0),
                run_number=205,
                elapsed_hours=2,
                station_id="different",
            ),
            "sample_count": historical_run(
                (11.0, 12.0, 13.0),
                run_number=206,
                elapsed_hours=2,
            ),
        }
        for label, candidate in mismatches.items():
            with self.subTest(label=label):
                with self.assertRaises(IncomparableHistoryError):
                    HistoricalConsistencyAnalyzer().assess(
                        (anchor, middle, candidate)
                    )

        different_plan_result = historical_run(
            (11.0, 13.0),
            run_number=207,
            elapsed_hours=2,
            sampling_frequency_hz=20.0,
        )
        with self.assertRaises(IncomparableHistoryError):
            HistoricalConsistencyAnalyzer().assess(
                (anchor, middle, different_plan_result)
            )

    def test_missing_or_invalid_consistency_group_is_rejected(self) -> None:
        base = representative_history()
        missing = historical_run(
            (11.0, 13.0),
            run_number=301,
            elapsed_hours=2,
            consistency_group=None,
        )
        invalid = replace(
            historical_run(
                (11.0, 13.0),
                run_number=302,
                elapsed_hours=2,
            ),
            metadata=replace(
                base[0].metadata,
                attributes=(("consistency_group", " bad "),),
            ),
        )
        for candidate in (missing, invalid):
            with self.subTest(candidate=candidate.run_id):
                with self.assertRaises(IncomparableHistoryError):
                    HistoricalConsistencyAnalyzer().assess(
                        (base[0], base[1], candidate)
                    )

    def test_one_sample_runs_do_not_claim_within_run_precision(self) -> None:
        history = tuple(
            historical_run(
                (float(index),),
                run_number=400 + index,
                elapsed_hours=float(index),
            )
            for index in range(3)
        )

        with self.assertRaises(IncomparableHistoryError):
            HistoricalConsistencyAnalyzer().assess(history)

    def test_forged_statistics_are_rejected(self) -> None:
        history = representative_history()
        candidate = history[2]
        forged_analyzed = replace(
            candidate.analyzed_result,
            statistics=replace(
                candidate.analyzed_result.statistics,
                mean_current_a=12.1,
            ),
        )
        forged = replace(candidate, analyzed_result=forged_analyzed)

        with self.assertRaises(IncomparableHistoryError):
            HistoricalConsistencyAnalyzer().assess(
                (history[0], history[1], forged)
            )


if __name__ == "__main__":
    unittest.main()
