"""Reference metrics, deterministic ranking, and cohort safety tests."""

from __future__ import annotations

import itertools
import math
import sys
import unittest
from dataclasses import replace

from src.testing.accuracy import (
    AccuracyAssessor,
    UNGROUPED_EXPLICIT_SELECTION,
)
from src.testing.accuracy_models import ReferenceCurrent
from src.testing.errors import (
    AccuracyAssessmentError,
    IncomparableAmmeterEvidenceError,
)
from src.testing.models import SamplingPlan, SamplingStopReason

from tests.test_phase6_support import (
    analyzed_result,
    archived_result,
    representative_cohort,
)


REFERENCE = ReferenceCurrent(current_a=10.0, source="traceable setpoint")


class AccuracyMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assessor = AccuracyAssessor()

    def test_bias_precision_rmse_ranks_winners_and_pairs(self) -> None:
        assessment = self.assessor.assess(
            representative_cohort(),
            reference=REFERENCE,
        )
        metrics = {item.ammeter_name: item for item in assessment.ammeters}

        alpha = metrics["alpha"]
        self.assertEqual(alpha.mean_current_a, 10.0)
        self.assertEqual(alpha.signed_bias_a, 0.0)
        self.assertEqual(alpha.absolute_error_a, 0.0)
        self.assertEqual(alpha.relative_error_percent, 0.0)
        self.assertEqual(alpha.standard_deviation_current_a, 1.0)
        self.assertEqual(alpha.root_mean_square_error_a, 1.0)
        self.assertEqual(
            (alpha.accuracy_rank, alpha.precision_rank, alpha.reliability_rank),
            (1, 3, 2),
        )

        bravo = metrics["bravo"]
        self.assertEqual(bravo.signed_bias_a, 0.5)
        self.assertEqual(bravo.absolute_error_a, 0.5)
        self.assertEqual(bravo.relative_error_percent, 5.0)
        self.assertEqual(bravo.standard_deviation_current_a, 0.0)
        self.assertEqual(bravo.root_mean_square_error_a, 0.5)
        self.assertEqual(
            (bravo.accuracy_rank, bravo.precision_rank, bravo.reliability_rank),
            (2, 1, 1),
        )

        charlie = metrics["charlie"]
        self.assertEqual(charlie.signed_bias_a, -1.0)
        self.assertEqual(charlie.absolute_error_a, 1.0)
        self.assertEqual(charlie.standard_deviation_current_a, 0.0)
        self.assertEqual(charlie.root_mean_square_error_a, 1.0)
        self.assertEqual(
            (
                charlie.accuracy_rank,
                charlie.precision_rank,
                charlie.reliability_rank,
            ),
            (3, 1, 2),
        )

        self.assertEqual(assessment.most_accurate_ammeters, ("alpha",))
        self.assertEqual(
            assessment.most_precise_ammeters,
            ("bravo", "charlie"),
        )
        self.assertEqual(assessment.most_reliable_ammeters, ("bravo",))
        self.assertEqual(
            tuple(
                (
                    pair.first_ammeter_name,
                    pair.second_ammeter_name,
                    pair.signed_mean_difference_a,
                    pair.absolute_mean_difference_a,
                    pair.relative_difference_percent,
                )
                for pair in assessment.pairwise_agreements
            ),
            (
                ("alpha", "bravo", 0.5, 0.5, 5.0),
                ("alpha", "charlie", -1.0, 1.0, 10.0),
                ("bravo", "charlie", -1.5, 1.5, 15.0),
            ),
        )

    def test_exact_ties_use_competition_ranks_and_retain_every_winner(self) -> None:
        cohort = (
            archived_result((9.0, 11.0), ammeter_name="alpha", run_number=10),
            archived_result((9.0, 11.0), ammeter_name="bravo", run_number=11),
            archived_result(
                (10.5, 10.5),
                ammeter_name="charlie",
                run_number=12,
            ),
        )

        assessment = self.assessor.assess(cohort, reference=REFERENCE)
        ranks = {
            item.ammeter_name: (
                item.accuracy_rank,
                item.precision_rank,
                item.reliability_rank,
            )
            for item in assessment.ammeters
        }

        self.assertEqual(ranks["alpha"], (1, 2, 2))
        self.assertEqual(ranks["bravo"], (1, 2, 2))
        self.assertEqual(ranks["charlie"], (3, 1, 1))
        self.assertEqual(
            assessment.most_accurate_ammeters,
            ("alpha", "bravo"),
        )
        self.assertEqual(assessment.most_precise_ammeters, ("charlie",))
        self.assertEqual(assessment.most_reliable_ammeters, ("charlie",))

    def test_every_input_permutation_produces_identical_output(self) -> None:
        cohort = representative_cohort()
        expected = self.assessor.assess(cohort, reference=REFERENCE).to_dict()

        for permutation in itertools.permutations(cohort):
            with self.subTest(order=[item.ammeter_name for item in permutation]):
                actual = self.assessor.assess(
                    permutation,
                    reference=REFERENCE,
                )
                self.assertEqual(actual.to_dict(), expected)

    def test_zero_reference_uses_undefined_relative_percentages(self) -> None:
        assessment = self.assessor.assess(
            representative_cohort()[:2],
            reference=ReferenceCurrent(current_a=-0.0, source="zero check"),
        )

        self.assertEqual(assessment.reference.current_a, 0.0)
        self.assertTrue(
            all(
                item.relative_error_percent is None
                for item in assessment.ammeters
            )
        )
        self.assertTrue(
            all(
                pair.relative_difference_percent is None
                for pair in assessment.pairwise_agreements
            )
        )

    def test_negative_reference_uses_absolute_reference_as_denominator(self) -> None:
        cohort = (
            archived_result((-9.0, -9.0), ammeter_name="alpha", run_number=20),
            archived_result(
                (-11.0, -11.0),
                ammeter_name="bravo",
                run_number=21,
            ),
        )

        assessment = self.assessor.assess(
            cohort,
            reference=ReferenceCurrent(current_a=-10.0, source="negative rail"),
        )

        self.assertEqual(
            tuple(item.signed_bias_a for item in assessment.ammeters),
            (1.0, -1.0),
        )
        self.assertEqual(
            tuple(item.relative_error_percent for item in assessment.ammeters),
            (10.0, 10.0),
        )
        self.assertEqual(
            assessment.pairwise_agreements[0].relative_difference_percent,
            20.0,
        )

    def test_finite_input_overflow_is_reported_as_typed_assessment_error(self) -> None:
        maximum = sys.float_info.max
        overflow_cases = (
            (
                (
                    archived_result(
                        (maximum, maximum),
                        ammeter_name="alpha",
                        run_number=30,
                    ),
                    archived_result(
                        (maximum, maximum),
                        ammeter_name="bravo",
                        run_number=31,
                    ),
                ),
                ReferenceCurrent(current_a=-maximum, source="opposite rail"),
            ),
            (
                (
                    archived_result(
                        (-maximum, -maximum),
                        ammeter_name="alpha",
                        run_number=32,
                    ),
                    archived_result(
                        (maximum, maximum),
                        ammeter_name="bravo",
                        run_number=33,
                    ),
                ),
                ReferenceCurrent(current_a=0.0, source="zero"),
            ),
            (
                (
                    archived_result(
                        (maximum, maximum),
                        ammeter_name="alpha",
                        run_number=34,
                    ),
                    archived_result(
                        (maximum / 2.0, maximum / 2.0),
                        ammeter_name="bravo",
                        run_number=35,
                    ),
                ),
                ReferenceCurrent(current_a=5e-324, source="minimum subnormal"),
            ),
        )
        for cohort, reference in overflow_cases:
            with self.subTest(reference=reference.current_a):
                with self.assertRaises(AccuracyAssessmentError):
                    self.assessor.assess(cohort, reference=reference)


class AccuracyCohortValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assessor = AccuracyAssessor()
        self.alpha = archived_result(
            (9.0, 11.0),
            ammeter_name="alpha",
            run_number=101,
        )
        self.bravo = archived_result(
            (10.0, 10.0),
            ammeter_name="bravo",
            run_number=102,
        )

    def assert_incomparable(self, *results: object) -> None:
        with self.assertRaises(IncomparableAmmeterEvidenceError):
            self.assessor.assess(results, reference=REFERENCE)  # type: ignore[arg-type]

    def test_requires_two_distinct_typed_runs(self) -> None:
        self.assert_incomparable(self.alpha)
        self.assert_incomparable(self.alpha, replace(self.alpha))
        with self.assertRaises(TypeError):
            self.assessor.assess(
                (self.alpha, object()),  # type: ignore[arg-type]
                reference=REFERENCE,
            )
        with self.assertRaises(TypeError):
            self.assessor.assess("not evidence", reference=REFERENCE)  # type: ignore[arg-type]

    def test_requires_one_case_insensitively_distinct_ammeter_per_run(self) -> None:
        duplicate_name = archived_result(
            (10.0, 10.0),
            ammeter_name="ALPHA",
            run_number=103,
        )
        self.assert_incomparable(self.alpha, duplicate_name)

    def test_requires_clean_matching_comparison_group(self) -> None:
        variants = (
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=104,
                comparison_group=None,
            ),
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=105,
                comparison_group="",
            ),
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=106,
                comparison_group="another-bench",
            ),
        )
        for variant in variants:
            with self.subTest(run_id=variant.run_id):
                self.assert_incomparable(self.alpha, variant)

    def test_explicit_selection_supports_legacy_runs_when_all_are_ungrouped(self) -> None:
        cohort = (
            archived_result(
                (9.0, 11.0),
                ammeter_name="alpha",
                run_number=204,
                comparison_group=None,
            ),
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=205,
                comparison_group=None,
            ),
        )

        assessment = self.assessor.assess(cohort, reference=REFERENCE)

        self.assertEqual(
            assessment.comparison_group,
            UNGROUPED_EXPLICIT_SELECTION,
        )
        self.assertEqual(
            tuple(item.ammeter_name for item in assessment.ammeters),
            ("alpha", "bravo"),
        )

    def test_requires_matching_test_dut_and_station_identity(self) -> None:
        variants = (
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=107,
                test_name="other-test",
            ),
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=108,
                dut_id="other-dut",
            ),
            archived_result(
                (10.0, 10.0),
                ammeter_name="bravo",
                run_number=109,
                station_id="other-station",
            ),
        )
        for variant in variants:
            with self.subTest(run_id=variant.run_id):
                self.assert_incomparable(self.alpha, variant)

    def test_requires_matching_sampling_plan(self) -> None:
        different_plan = archived_result(
            (10.0, 10.0),
            ammeter_name="bravo",
            run_number=110,
            sampling_frequency_hz=20.0,
        )
        self.assert_incomparable(self.alpha, different_plan)

    def test_requires_matching_sample_count_even_under_same_plan(self) -> None:
        shared_plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            measurements_count=3,
            total_duration_seconds=math.nextafter(0.2, math.inf),
        )
        three_sample_analysis = analyzed_result(
            (9.0, 10.0, 11.0),
            ammeter_name="alpha",
            plan_override=shared_plan,
            stop_reason=SamplingStopReason.COUNT_REACHED,
            completion_offsets=(0.0, 0.1, 0.2),
        )
        two_sample_analysis = analyzed_result(
            (10.0, 10.0),
            ammeter_name="bravo",
            plan_override=shared_plan,
            stop_reason=SamplingStopReason.DURATION_REACHED,
            completion_offsets=(0.0, 0.2),
        )
        alpha = archived_result(
            (),
            ammeter_name="alpha",
            run_number=111,
            analyzed_override=three_sample_analysis,
        )
        bravo = archived_result(
            (),
            ammeter_name="bravo",
            run_number=112,
            analyzed_override=two_sample_analysis,
        )

        with self.assertRaisesRegex(
            IncomparableAmmeterEvidenceError,
            "same number of samples",
        ):
            self.assessor.assess((alpha, bravo), reference=REFERENCE)

    def test_requires_matching_stop_reason(self) -> None:
        shared_plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            measurements_count=3,
            total_duration_seconds=math.nextafter(0.2, math.inf),
        )
        alpha_analysis = analyzed_result(
            (9.0, 10.0, 11.0),
            ammeter_name="alpha",
            plan_override=shared_plan,
            stop_reason=SamplingStopReason.COUNT_REACHED,
            completion_offsets=(0.0, 0.1, 0.2),
        )
        bravo_analysis = analyzed_result(
            (10.0, 10.0, 10.0),
            ammeter_name="bravo",
            plan_override=shared_plan,
            stop_reason=SamplingStopReason.DURATION_REACHED,
            completion_offsets=(0.0, 0.1, 0.2),
        )
        alpha = archived_result(
            (),
            ammeter_name="alpha",
            run_number=113,
            analyzed_override=alpha_analysis,
        )
        bravo = archived_result(
            (),
            ammeter_name="bravo",
            run_number=114,
            analyzed_override=bravo_analysis,
        )

        with self.assertRaisesRegex(
            IncomparableAmmeterEvidenceError,
            "same sampling stop reason",
        ):
            self.assessor.assess((alpha, bravo), reference=REFERENCE)

    def test_rejects_typed_but_internally_inconsistent_evidence(self) -> None:
        valid_analysis = self.bravo.analyzed_result
        bad_statistics = replace(
            valid_analysis.statistics,
            standard_deviation_current_a=(
                valid_analysis.statistics.standard_deviation_current_a + 1.0
            ),
        )
        bad_analysis = replace(valid_analysis, statistics=bad_statistics)
        corrupted = replace(self.bravo, analyzed_result=bad_analysis)

        with self.assertRaisesRegex(
            IncomparableAmmeterEvidenceError,
            "inconsistent evidence",
        ):
            self.assessor.assess((self.alpha, corrupted), reference=REFERENCE)

    def test_reference_must_be_typed_before_calculation(self) -> None:
        with self.assertRaises(TypeError):
            self.assessor.assess(
                (self.alpha, self.bravo),
                reference=10.0,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
