"""Unit tests for Phase 3 sampling plans and immutable run evidence."""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from src.devices.models import CurrentMeasurement
from src.testing.models import (
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)


def _measurement(current_a: float = 1.25) -> CurrentMeasurement:
    return CurrentMeasurement(
        ammeter_name="greenlee",
        current_a=current_a,
        measured_at_utc=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
        monotonic_time_s=10.1,
        latency_seconds=0.1,
    )


class SamplingPlanTests(unittest.TestCase):
    def test_accepts_count_duration_and_combined_stop_caps(self) -> None:
        count_plan = SamplingPlan(
            sampling_frequency_hz=2.0,
            measurements_count=3,
        )
        duration_plan = SamplingPlan(
            sampling_frequency_hz=4.0,
            total_duration_seconds=1.5,
        )
        combined_plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            measurements_count=20,
            total_duration_seconds=1.0,
        )

        self.assertEqual(count_plan.measurements_count, 3)
        self.assertIsNone(count_plan.total_duration_seconds)
        self.assertEqual(duration_plan.total_duration_seconds, 1.5)
        self.assertIsNone(duration_plan.measurements_count)
        self.assertEqual(combined_plan.measurements_count, 20)
        self.assertEqual(combined_plan.total_duration_seconds, 1.0)

    def test_is_keyword_only_frozen_and_slotted(self) -> None:
        with self.assertRaises(TypeError):
            SamplingPlan(2.0, 3)  # type: ignore[misc]

        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=3)
        self.assertFalse(hasattr(plan, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            plan.measurements_count = 4  # type: ignore[misc]

    def test_requires_at_least_one_stop_cap(self) -> None:
        with self.assertRaises(ValueError):
            SamplingPlan(sampling_frequency_hz=1.0)

    def test_rejects_invalid_sampling_frequency(self) -> None:
        invalid_values = (
            True,
            0,
            -0.1,
            5e-324,
            10**400,
            math.nan,
            math.inf,
            -math.inf,
            "2",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SamplingPlan(
                        sampling_frequency_hz=value,  # type: ignore[arg-type]
                        measurements_count=1,
                    )

    def test_duration_grid_does_not_round_down_a_legal_sample(self) -> None:
        plan = SamplingPlan(
            sampling_frequency_hz=1.0,
            total_duration_seconds=10.000000000005,
        )

        self.assertEqual(plan.maximum_scheduled_samples, 11)

    def test_rejects_invalid_measurement_count(self) -> None:
        invalid_values = (True, 0, -1, 1.5, "2")
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SamplingPlan(
                        sampling_frequency_hz=1.0,
                        measurements_count=value,  # type: ignore[arg-type]
                    )

    def test_rejects_invalid_duration(self) -> None:
        invalid_values = (
            True,
            0,
            -0.1,
            math.nan,
            math.inf,
            -math.inf,
            "1",
            10**400,
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SamplingPlan(
                        sampling_frequency_hz=1.0,
                        total_duration_seconds=value,  # type: ignore[arg-type]
                    )

class SamplingEvidenceTests(unittest.TestCase):
    def test_monotonic_order_remains_authoritative_if_wall_clock_steps_back(
        self,
    ) -> None:
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        sample = SampledMeasurement(
            sample_index=0,
            scheduled_offset_seconds=0.0,
            started_offset_seconds=0.0,
            completed_offset_seconds=0.1,
            measurement=_measurement(),
        )

        result = SamplingRunResult(
            ammeter_name="greenlee",
            plan=plan,
            samples=(sample,),
            started_at_utc=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
            completed_at_utc=datetime(2026, 8, 6, 11, 59, tzinfo=timezone.utc),
            started_monotonic_s=10.0,
            completed_monotonic_s=10.1,
            stop_reason=SamplingStopReason.COUNT_REACHED,
        )

        self.assertAlmostEqual(result.elapsed_seconds, 0.1)

    def test_sample_reports_start_lateness_and_is_immutable(self) -> None:
        sample = SampledMeasurement(
            sample_index=0,
            scheduled_offset_seconds=0.5,
            started_offset_seconds=0.65,
            completed_offset_seconds=0.75,
            measurement=_measurement(),
        )

        self.assertAlmostEqual(sample.start_lateness_seconds, 0.15)
        self.assertFalse(hasattr(sample, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            sample.sample_index = 1  # type: ignore[misc]

    def test_run_result_exposes_ordered_measurements_elapsed_time_and_json_data(
        self,
    ) -> None:
        first_measurement = _measurement(1.25)
        second_measurement = _measurement(1.5)
        samples = (
            SampledMeasurement(
                sample_index=0,
                scheduled_offset_seconds=0.0,
                started_offset_seconds=0.0,
                completed_offset_seconds=0.1,
                measurement=first_measurement,
            ),
            SampledMeasurement(
                sample_index=1,
                scheduled_offset_seconds=0.5,
                started_offset_seconds=0.5,
                completed_offset_seconds=0.6,
                measurement=second_measurement,
            ),
        )
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=2)
        result = SamplingRunResult(
            ammeter_name="greenlee",
            plan=plan,
            samples=samples,
            started_at_utc=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
            completed_at_utc=datetime(
                2026, 8, 6, 12, 0, 0, 600_000, tzinfo=timezone.utc
            ),
            started_monotonic_s=10.0,
            completed_monotonic_s=10.6,
            stop_reason=SamplingStopReason.COUNT_REACHED,
        )

        self.assertEqual(result.sample_count, 2)
        self.assertEqual(result.measurements, (first_measurement, second_measurement))
        self.assertAlmostEqual(result.elapsed_seconds, 0.6)
        self.assertIsInstance(result.samples, tuple)
        with self.assertRaises(FrozenInstanceError):
            result.samples = ()  # type: ignore[misc]

        serialized = result.to_dict()
        self.assertEqual(serialized["ammeter_name"], "greenlee")
        self.assertEqual(serialized["sample_count"], 2)
        self.assertEqual(
            serialized["stop_reason"], SamplingStopReason.COUNT_REACHED.value
        )
        self.assertEqual(len(serialized["samples"]), 2)
        self.assertEqual(
            [sample["measurement"]["current_a"] for sample in serialized["samples"]],
            [1.25, 1.5],
        )
        json.dumps(serialized)


if __name__ == "__main__":
    unittest.main()
