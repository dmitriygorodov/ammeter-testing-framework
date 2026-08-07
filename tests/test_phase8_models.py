"""Immutable and self-consistent Phase 8 model tests."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace

from src.testing.consistency import HistoricalConsistencyAnalyzer

from tests.test_phase8_support import representative_history


class HistoricalConsistencyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assessment = HistoricalConsistencyAnalyzer().assess(
            representative_history()
        )

    def test_complete_tree_is_frozen_slotted_and_json_ready(self) -> None:
        records = (
            self.assessment,
            self.assessment.metrics,
            *self.assessment.runs,
        )
        for record in records:
            with self.subTest(record_type=type(record).__name__):
                self.assertFalse(hasattr(record, "__dict__"))
        json.dumps(self.assessment.to_dict(), allow_nan=False)
        with self.assertRaises(FrozenInstanceError):
            self.assessment.sample_count = 99  # type: ignore[misc]

    def test_projection_properties_are_explicit(self) -> None:
        self.assertEqual(self.assessment.run_count, 3)
        self.assertEqual(self.assessment.time_span_seconds, 7200.0)
        encoded = self.assessment.to_dict()
        self.assertEqual(encoded["run_count"], 3)
        self.assertIn("trend_slope_a_per_hour", encoded["metrics"])
        self.assertEqual(len(encoded["runs"]), 3)

    def test_metrics_cannot_be_forged(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                self.assessment,
                metrics=replace(
                    self.assessment.metrics,
                    trend_slope_a_per_hour=2.0,
                ),
            )
        with self.assertRaises(ValueError):
            replace(
                self.assessment.metrics,
                peak_to_peak_run_mean_a=3.0,
            )

    def test_run_order_elapsed_time_and_cohort_fields_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                self.assessment,
                runs=tuple(reversed(self.assessment.runs)),
            )
        changed_elapsed = replace(
            self.assessment.runs[1],
            elapsed_since_first_seconds=1.0,
        )
        with self.assertRaises(ValueError):
            replace(
                self.assessment,
                runs=(
                    self.assessment.runs[0],
                    changed_elapsed,
                    self.assessment.runs[2],
                ),
            )
        with self.assertRaises(ValueError):
            replace(self.assessment, sample_count=3)


if __name__ == "__main__":
    unittest.main()
