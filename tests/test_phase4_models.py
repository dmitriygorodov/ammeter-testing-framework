"""Model-contract tests for Phase 4 statistical analysis evidence."""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from src.devices.models import CurrentMeasurement
from src.testing.models import (
    AnalyzedSamplingResult,
    CurrentStatistics,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


BASE_UTC = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _sampling_run(
    values: tuple[float, ...] = (1.0, 2.0),
    *,
    ammeter_name: str = "greenlee",
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

    samples = tuple(
        SampledMeasurement(
            sample_index=index,
            scheduled_offset_seconds=index * 0.1,
            started_offset_seconds=index * 0.1,
            completed_offset_seconds=index * 0.1 + 0.01,
            measurement=CurrentMeasurement(
                ammeter_name=ammeter_name,
                current_a=value,
                measured_at_utc=BASE_UTC + timedelta(seconds=index * 0.1 + 0.01),
                monotonic_time_s=100.0 + index * 0.1 + 0.01,
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
        started_monotonic_s=100.0,
        completed_monotonic_s=100.0 + elapsed_seconds,
        stop_reason=stop_reason,
    )


def _statistics(
    *,
    ammeter_name: str = "greenlee",
    sample_count: int = 2,
) -> CurrentStatistics:
    return CurrentStatistics(
        ammeter_name=ammeter_name,
        sample_count=sample_count,
        mean_current_a=1.5,
        median_current_a=1.5,
        standard_deviation_current_a=0.5,
        minimum_current_a=1.0,
        maximum_current_a=2.0,
    )


class CurrentStatisticsTests(unittest.TestCase):
    def test_record_is_unit_explicit_immutable_slotted_and_json_ready(self) -> None:
        statistics = _statistics()

        self.assertEqual(statistics.ammeter_name, "greenlee")
        self.assertEqual(statistics.sample_count, 2)
        self.assertEqual(statistics.unit, "A")
        self.assertFalse(hasattr(statistics, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            statistics.mean_current_a = 99.0  # type: ignore[misc]

        serialized = statistics.to_dict()
        self.assertEqual(
            serialized,
            {
                "ammeter_name": "greenlee",
                "sample_count": 2,
                "unit": "A",
                "mean_current_a": 1.5,
                "median_current_a": 1.5,
                "standard_deviation_current_a": 0.5,
                "minimum_current_a": 1.0,
                "maximum_current_a": 2.0,
            },
        )
        json.dumps(serialized)

    def test_rejects_invalid_identity_and_sample_count(self) -> None:
        valid = {
            "ammeter_name": "greenlee",
            "sample_count": 2,
            "mean_current_a": 1.5,
            "median_current_a": 1.5,
            "standard_deviation_current_a": 0.5,
            "minimum_current_a": 1.0,
            "maximum_current_a": 2.0,
        }
        for invalid_name in ("", "   ", " greenlee ", 3):
            with self.subTest(ammeter_name=invalid_name):
                values = dict(valid)
                values["ammeter_name"] = invalid_name
                with self.assertRaises((TypeError, ValueError)):
                    CurrentStatistics(**values)  # type: ignore[arg-type]

        for invalid_count in (True, 0, -1, 1.5, "2"):
            with self.subTest(sample_count=invalid_count):
                values = dict(valid)
                values["sample_count"] = invalid_count
                with self.assertRaises((TypeError, ValueError)):
                    CurrentStatistics(**values)  # type: ignore[arg-type]

    def test_rejects_non_finite_metrics_and_negative_deviation(self) -> None:
        valid = {
            "ammeter_name": "greenlee",
            "sample_count": 2,
            "mean_current_a": 1.5,
            "median_current_a": 1.5,
            "standard_deviation_current_a": 0.5,
            "minimum_current_a": 1.0,
            "maximum_current_a": 2.0,
        }
        metric_names = (
            "mean_current_a",
            "median_current_a",
            "standard_deviation_current_a",
            "minimum_current_a",
            "maximum_current_a",
        )
        for metric_name in metric_names:
            for invalid in (True, math.nan, math.inf, -math.inf, "1.0"):
                with self.subTest(metric=metric_name, value=invalid):
                    values = dict(valid)
                    values[metric_name] = invalid
                    with self.assertRaises((TypeError, ValueError)):
                        CurrentStatistics(**values)  # type: ignore[arg-type]

        valid["standard_deviation_current_a"] = -0.001
        with self.assertRaises(ValueError):
            CurrentStatistics(**valid)  # type: ignore[arg-type]

    def test_rejects_inconsistent_metric_bounds(self) -> None:
        with self.assertRaises(ValueError):
            CurrentStatistics(
                ammeter_name="greenlee",
                sample_count=2,
                mean_current_a=1.5,
                median_current_a=1.5,
                standard_deviation_current_a=0.5,
                minimum_current_a=2.0,
                maximum_current_a=1.0,
            )


class AnalyzedSamplingResultTests(unittest.TestCase):
    def test_combines_original_run_and_statistics_without_changing_evidence(self) -> None:
        sampling_result = _sampling_run()
        statistics = _statistics()

        analyzed = AnalyzedSamplingResult(
            sampling_result=sampling_result,
            statistics=statistics,
        )

        self.assertIs(analyzed.sampling_result, sampling_result)
        self.assertIs(analyzed.statistics, statistics)
        self.assertFalse(hasattr(analyzed, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            analyzed.statistics = statistics  # type: ignore[misc]

        serialized = analyzed.to_dict()
        self.assertEqual(serialized["sampling_result"], sampling_result.to_dict())
        self.assertEqual(serialized["statistics"], statistics.to_dict())
        json.dumps(serialized)

    def test_requires_typed_matching_sampling_and_statistics_evidence(self) -> None:
        sampling_result = _sampling_run()
        statistics = _statistics()

        with self.assertRaises(TypeError):
            AnalyzedSamplingResult(  # type: ignore[arg-type]
                sampling_result=object(),
                statistics=statistics,
            )
        with self.assertRaises(TypeError):
            AnalyzedSamplingResult(  # type: ignore[arg-type]
                sampling_result=sampling_result,
                statistics=object(),
            )
        with self.assertRaises(ValueError):
            AnalyzedSamplingResult(
                sampling_result=sampling_result,
                statistics=_statistics(ammeter_name="entes"),
            )
        with self.assertRaises(ValueError):
            AnalyzedSamplingResult(
                sampling_result=sampling_result,
                statistics=_statistics(sample_count=1),
            )


if __name__ == "__main__":
    unittest.main()
