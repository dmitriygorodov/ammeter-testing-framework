"""Phase 9 headless visualization contracts and output safety."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.testing.acceptance import ResultEvaluator
from src.testing.acceptance_models import AcceptanceLimits, AcceptancePolicy
from src.testing.accuracy import AccuracyAssessor
from src.testing.accuracy_models import ReferenceCurrent
from src.testing.consistency import HistoricalConsistencyAnalyzer
from src.testing.errors import VisualizationError, VisualizationOutputError
from src.testing.visualization import ResultVisualizer

from tests.test_phase6_support import analyzed_result, representative_cohort
from tests.test_phase8_support import representative_history


class ResultVisualizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.visualizer = ResultVisualizer()
        self.result = analyzed_result(
            (9.95, 10.02, 10.00, 10.03),
            ammeter_name="greenlee",
        )

    def test_run_overview_contains_series_distribution_and_timing(self) -> None:
        policy = AcceptancePolicy(
            name="bench-current",
            version="1",
            reference=ReferenceCurrent(current_a=10.0, source="calibrator"),
            limits=AcceptanceLimits(
                minimum_current_a=9.9,
                maximum_current_a=10.1,
                maximum_absolute_bias_a=0.05,
                maximum_start_lateness_seconds=0.02,
                maximum_acquisition_duration_seconds=0.2,
            ),
        )
        verdict = ResultEvaluator().evaluate(self.result, policy=policy)

        figure = self.visualizer.plot_run_overview(
            self.result,
            verdict=verdict,
        )

        self.assertEqual(len(figure.axes), 3)
        self.assertEqual(
            [axis.get_title() for axis in figure.axes],
            [
                "Current over time - greenlee",
                "Current distribution",
                "Sampling timing",
            ],
        )
        self.assertGreaterEqual(len(figure.axes[0].patches), 2)
        self.assertEqual(self.result.statistics.mean_current_a, 10.0)

    def test_accuracy_and_consistency_figures_show_two_distinct_views(self) -> None:
        accuracy = AccuracyAssessor().assess(
            representative_cohort(),
            reference=ReferenceCurrent(
                current_a=10.0,
                source="calibrator",
                expanded_uncertainty_a=0.25,
            ),
        )
        consistency = HistoricalConsistencyAnalyzer().assess(
            representative_history()
        )

        accuracy_figure = self.visualizer.plot_accuracy_assessment(accuracy)
        consistency_figure = self.visualizer.plot_consistency_assessment(
            consistency
        )

        self.assertEqual(len(accuracy_figure.axes), 2)
        self.assertEqual(len(consistency_figure.axes), 2)
        self.assertIn("Cross-ammeter accuracy", accuracy_figure._suptitle.get_text())
        self.assertIn(
            "Historical consistency",
            consistency_figure._suptitle.get_text(),
        )
        self.assertTrue(
            any(
                line.get_label().startswith("OLS trend")
                for line in consistency_figure.axes[0].lines
            )
        )

    def test_mismatched_verdict_is_rejected_before_plotting(self) -> None:
        policy = AcceptancePolicy(
            name="bench",
            version="1",
            limits=AcceptanceLimits(maximum_standard_deviation_a=1.0),
        )
        verdict = ResultEvaluator().evaluate(self.result, policy=policy)
        mismatched = replace(verdict, ammeter_name="entes")

        with self.assertRaisesRegex(VisualizationError, "does not match"):
            self.visualizer.plot_run_overview(
                self.result,
                verdict=mismatched,
            )

    def test_save_supports_engineering_formats_and_refuses_overwrite(self) -> None:
        figure = self.visualizer.plot_run_overview(self.result)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for suffix, signature in (
                ("png", b"\x89PNG"),
                ("svg", b"<?xml"),
                ("pdf", b"%PDF"),
            ):
                with self.subTest(suffix=suffix):
                    output = root / "nested" / f"overview.{suffix}"
                    actual = self.visualizer.save(figure, output)
                    self.assertEqual(actual, output.resolve())
                    self.assertTrue(output.read_bytes().startswith(signature))

            existing = root / "overview.png"
            existing.write_bytes(b"original")
            with self.assertRaisesRegex(
                VisualizationOutputError,
                "already exists",
            ):
                self.visualizer.save(figure, existing)
            self.assertEqual(existing.read_bytes(), b"original")

    def test_invalid_output_contracts_fail_without_creating_artifacts(self) -> None:
        figure = self.visualizer.plot_run_overview(self.result)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            unsupported = root / "plots" / "overview.jpg"
            with self.assertRaises(VisualizationOutputError):
                self.visualizer.save(figure, unsupported)
            self.assertFalse(unsupported.parent.exists())
            for dpi in (True, 71, 601, 160.0):
                with self.subTest(dpi=dpi):
                    with self.assertRaises(VisualizationOutputError):
                        self.visualizer.save(
                            figure,
                            root / f"bad-{dpi}.png",
                            dpi=dpi,  # type: ignore[arg-type]
                        )

    def test_public_methods_validate_model_types(self) -> None:
        with self.assertRaises(TypeError):
            self.visualizer.plot_run_overview(object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.visualizer.plot_accuracy_assessment(object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.visualizer.plot_consistency_assessment(object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.visualizer.save(object(), "plot.png")


if __name__ == "__main__":
    unittest.main()
