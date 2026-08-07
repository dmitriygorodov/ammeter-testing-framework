"""Behavior tests for Phase 4 current-statistics analysis."""

from __future__ import annotations

import math
import sys
import unittest
from datetime import datetime, timedelta, timezone

from src.devices.models import CurrentMeasurement
from src.testing.analysis import ResultAnalyzer
from src.testing.errors import ResultAnalysisError
from src.testing.models import (
    CurrentStatistics,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


BASE_UTC = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _sampling_run(
    values: tuple[float, ...],
    *,
    ammeter_name: str = "greenlee",
    measurement_name: str | None = None,
) -> SamplingRunResult:
    if values:
        plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            measurements_count=len(values),
        )
        stop_reason = SamplingStopReason.COUNT_REACHED
    else:
        plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            total_duration_seconds=0.1,
        )
        stop_reason = SamplingStopReason.DURATION_REACHED

    effective_measurement_name = (
        measurement_name if measurement_name is not None else ammeter_name
    )
    samples = tuple(
        SampledMeasurement(
            sample_index=index,
            scheduled_offset_seconds=index * 0.1,
            started_offset_seconds=index * 0.1,
            completed_offset_seconds=index * 0.1 + 0.01,
            measurement=CurrentMeasurement(
                ammeter_name=effective_measurement_name,
                current_a=value,
                measured_at_utc=BASE_UTC + timedelta(seconds=index * 0.1 + 0.01),
                monotonic_time_s=50.0 + index * 0.1 + 0.01,
                latency_seconds=0.01,
            ),
        )
        for index, value in enumerate(values)
    )
    elapsed_seconds = samples[-1].completed_offset_seconds if samples else 0.1
    return SamplingRunResult(
        ammeter_name=ammeter_name,
        plan=plan,
        samples=samples,
        started_at_utc=BASE_UTC,
        completed_at_utc=BASE_UTC + timedelta(seconds=elapsed_seconds),
        started_monotonic_s=50.0,
        completed_monotonic_s=50.0 + elapsed_seconds,
        stop_reason=stop_reason,
    )


class ResultAnalyzerTests(unittest.TestCase):
    def test_calculates_all_required_metrics_for_unsorted_signed_even_data(self) -> None:
        run = _sampling_run((3.0, -1.0, 2.0, 6.0))

        statistics = ResultAnalyzer().analyze(run)

        self.assertIsInstance(statistics, CurrentStatistics)
        self.assertEqual(statistics.ammeter_name, "greenlee")
        self.assertEqual(statistics.sample_count, 4)
        self.assertAlmostEqual(statistics.mean_current_a, 2.5)
        self.assertAlmostEqual(statistics.median_current_a, 2.5)
        self.assertAlmostEqual(statistics.standard_deviation_current_a, 2.5)
        self.assertEqual(statistics.minimum_current_a, -1.0)
        self.assertEqual(statistics.maximum_current_a, 6.0)

    def test_uses_the_middle_value_for_an_unsorted_odd_dataset(self) -> None:
        statistics = ResultAnalyzer().analyze(
            _sampling_run((9.0, 1.0, 5.0))
        )

        self.assertEqual(statistics.median_current_a, 5.0)

    def test_single_sample_has_zero_population_standard_deviation(self) -> None:
        statistics = ResultAnalyzer().analyze(_sampling_run((-0.25,)))

        self.assertEqual(statistics.mean_current_a, -0.25)
        self.assertEqual(statistics.median_current_a, -0.25)
        self.assertEqual(statistics.standard_deviation_current_a, 0.0)
        self.assertEqual(statistics.minimum_current_a, -0.25)
        self.assertEqual(statistics.maximum_current_a, -0.25)

    def test_repeated_values_have_zero_population_standard_deviation(self) -> None:
        statistics = ResultAnalyzer().analyze(
            _sampling_run((1.25, 1.25, 1.25, 1.25))
        )

        self.assertEqual(statistics.mean_current_a, 1.25)
        self.assertEqual(statistics.standard_deviation_current_a, 0.0)

    def test_mean_is_stable_under_large_cancellation(self) -> None:
        run = _sampling_run((1e16, 1.0, -1e16))

        statistics = ResultAnalyzer().analyze(run)

        self.assertAlmostEqual(statistics.mean_current_a, 1.0 / 3.0)
        self.assertTrue(
            math.isfinite(statistics.standard_deviation_current_a)
        )

    def test_large_equal_finite_values_do_not_overflow_metrics(self) -> None:
        statistics = ResultAnalyzer().analyze(_sampling_run((1e308, 1e308)))

        self.assertEqual(statistics.mean_current_a, 1e308)
        self.assertEqual(statistics.median_current_a, 1e308)
        self.assertEqual(statistics.standard_deviation_current_a, 0.0)

    def test_opposite_maximum_floats_have_finite_population_deviation(self) -> None:
        maximum = sys.float_info.max

        statistics = ResultAnalyzer().analyze(
            _sampling_run((-maximum, maximum))
        )

        self.assertEqual(statistics.mean_current_a, 0.0)
        self.assertEqual(statistics.median_current_a, 0.0)
        self.assertEqual(statistics.standard_deviation_current_a, maximum)

    def test_opposite_subnormal_floats_do_not_underflow_deviation(self) -> None:
        minimum_subnormal = float.fromhex("0x0.0000000000001p-1022")

        statistics = ResultAnalyzer().analyze(
            _sampling_run((-minimum_subnormal, minimum_subnormal))
        )

        self.assertEqual(
            statistics.standard_deviation_current_a,
            minimum_subnormal,
        )

    def test_power_of_two_scaling_preserves_adjacent_large_values(self) -> None:
        larger = 1e308
        smaller = math.nextafter(larger, 0.0)

        statistics = ResultAnalyzer().analyze(
            _sampling_run((larger, smaller))
        )

        self.assertEqual(
            statistics.standard_deviation_current_a,
            (larger - smaller) / 2.0,
        )

    def test_analysis_does_not_mutate_or_reorder_source_evidence(self) -> None:
        run = _sampling_run((5.0, 1.0, 4.0, 2.0))
        original_samples = run.samples
        original_measurements = run.measurements
        original_serialized = run.to_dict()

        ResultAnalyzer().analyze(run)

        self.assertIs(run.samples, original_samples)
        self.assertEqual(run.measurements, original_measurements)
        self.assertEqual(run.to_dict(), original_serialized)

    def test_empty_run_raises_typed_analysis_error(self) -> None:
        with self.assertRaises(ResultAnalysisError):
            ResultAnalyzer().analyze(_sampling_run(()))

    def test_mixed_ammeter_evidence_raises_typed_analysis_error(self) -> None:
        run = _sampling_run(
            (1.0, 2.0),
            ammeter_name="greenlee",
            measurement_name="entes",
        )

        with self.assertRaises(ResultAnalysisError):
            ResultAnalyzer().analyze(run)

    def test_wrong_input_type_is_rejected_before_calculation(self) -> None:
        with self.assertRaises(TypeError):
            ResultAnalyzer().analyze(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
