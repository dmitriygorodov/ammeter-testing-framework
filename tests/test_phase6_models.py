"""Immutable and JSON-ready model contracts for Phase 6."""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError, replace

from src.testing.accuracy import AccuracyAssessor
from src.testing.accuracy_models import (
    AmmeterAccuracyMetrics,
    PairwiseAmmeterAgreement,
    ReferenceAccuracyAssessment,
    ReferenceCurrent,
)
from src.testing.models import SamplingPlan, SamplingStopReason

from tests.test_phase6_support import representative_cohort


class ReferenceCurrentModelTests(unittest.TestCase):
    def test_reference_is_frozen_slotted_normalized_and_json_ready(self) -> None:
        reference = ReferenceCurrent(
            current_a=10,
            source="Fluke 5522A setpoint",
            expanded_uncertainty_a=0,
            calibration_id="CAL-2026-0042",
        )

        self.assertEqual(reference.current_a, 10.0)
        self.assertEqual(reference.expanded_uncertainty_a, 0.0)
        self.assertEqual(reference.unit, "A")
        self.assertFalse(hasattr(reference, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            reference.current_a = 11.0  # type: ignore[misc]
        json.dumps(reference.to_dict(), allow_nan=False)

    def test_reference_rejects_nonfinite_or_ambiguous_values(self) -> None:
        invalid_constructors = (
            lambda: ReferenceCurrent(current_a=True, source="source"),
            lambda: ReferenceCurrent(current_a=math.inf, source="source"),
            lambda: ReferenceCurrent(current_a=1.0, source=" source"),
            lambda: ReferenceCurrent(
                current_a=1.0,
                source="source",
                expanded_uncertainty_a=-0.01,
            ),
            lambda: ReferenceCurrent(
                current_a=1.0,
                source="source",
                calibration_id="",
            ),
        )
        for constructor in invalid_constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(ValueError):
                    constructor()


class AccuracyResultModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assessment = AccuracyAssessor().assess(
            representative_cohort(),
            reference=ReferenceCurrent(current_a=10.0, source="setpoint"),
        )

    def test_complete_assessment_tree_is_frozen_slotted_and_json_ready(self) -> None:
        assessment = self.assessment
        records = (
            assessment,
            *assessment.ammeters,
            *assessment.pairwise_agreements,
        )
        for record in records:
            with self.subTest(record_type=type(record).__name__):
                self.assertFalse(hasattr(record, "__dict__"))
                json.dumps(record.to_dict(), allow_nan=False)

        with self.assertRaises(FrozenInstanceError):
            assessment.sample_count = 99  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            assessment.ammeters[0].accuracy_rank = 9  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            assessment.pairwise_agreements[0].signed_mean_difference_a = 0.0  # type: ignore[misc]

        encoded = assessment.to_dict()
        self.assertFalse(encoded["operational_failure_reliability_assessed"])
        self.assertEqual(encoded["unit"], "A")
        self.assertIn("winners", encoded)
        self.assertEqual(len(encoded["pairwise_agreements"]), 3)

    def test_metric_model_rejects_inconsistent_absolute_error(self) -> None:
        metric = self.assessment.ammeters[0]
        with self.assertRaises(ValueError):
            replace(metric, absolute_error_a=metric.absolute_error_a + 1.0)

    def test_pair_model_requires_canonical_names_and_absolute_difference(self) -> None:
        pair = self.assessment.pairwise_agreements[0]
        with self.assertRaises(ValueError):
            PairwiseAmmeterAgreement(
                first_run_id=pair.second_run_id,
                second_run_id=pair.first_run_id,
                first_ammeter_name=pair.second_ammeter_name,
                second_ammeter_name=pair.first_ammeter_name,
                signed_mean_difference_a=-pair.signed_mean_difference_a,
                absolute_mean_difference_a=pair.absolute_mean_difference_a,
                relative_difference_percent=pair.relative_difference_percent,
            )
        with self.assertRaises(ValueError):
            replace(
                pair,
                absolute_mean_difference_a=(
                    pair.absolute_mean_difference_a + 1.0
                ),
            )

    def test_assessment_model_requires_every_pair_and_all_rank_one_winners(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                self.assessment,
                pairwise_agreements=self.assessment.pairwise_agreements[:-1],
            )
        with self.assertRaises(ValueError):
            replace(self.assessment, most_accurate_ammeters=("bravo",))

    def test_assessment_model_rejects_incoherent_plan_stop_projection(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                self.assessment,
                sampling_plan=SamplingPlan(
                    sampling_frequency_hz=10.0,
                    measurements_count=self.assessment.sample_count + 1,
                ),
            )
        with self.assertRaises(ValueError):
            replace(
                self.assessment,
                stop_reason=SamplingStopReason.DURATION_REACHED,
            )

    def test_public_result_types_are_the_expected_types(self) -> None:
        self.assertIsInstance(self.assessment, ReferenceAccuracyAssessment)
        self.assertTrue(
            all(
                isinstance(item, AmmeterAccuracyMetrics)
                for item in self.assessment.ammeters
            )
        )
        self.assertTrue(
            all(
                isinstance(item, PairwiseAmmeterAgreement)
                for item in self.assessment.pairwise_agreements
            )
        )


if __name__ == "__main__":
    unittest.main()
