"""Unit tests for Phase 2's typed measurement record."""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from src.devices.models import CurrentMeasurement


class CurrentMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timestamp = datetime(2026, 8, 6, 12, 30, 45, 123456, tzinfo=timezone.utc)

    def test_record_is_immutable_and_serializes_with_explicit_units(self) -> None:
        measurement = CurrentMeasurement(
            ammeter_name="greenlee",
            current_a=1.25,
            measured_at_utc=self.timestamp,
            monotonic_time_s=42.5,
            latency_seconds=0.125,
        )

        self.assertEqual(measurement.ammeter_name, "greenlee")
        self.assertEqual(
            measurement.to_dict(),
            {
                "ammeter_name": "greenlee",
                "current_a": 1.25,
                "unit": "A",
                "measured_at_utc": "2026-08-06T12:30:45.123456Z",
                "monotonic_time_s": 42.5,
                "latency_seconds": 0.125,
            },
        )
        with self.assertRaises(FrozenInstanceError):
            measurement.current_a = 9.0  # type: ignore[misc]

    def test_naive_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "UTC|timezone|aware"):
            CurrentMeasurement(
                ammeter_name="greenlee",
                current_a=1.0,
                measured_at_utc=datetime(2026, 8, 6, 12, 30, 45),
                monotonic_time_s=1.0,
                latency_seconds=0.1,
            )

    def test_non_finite_numeric_fields_are_rejected(self) -> None:
        valid = {
            "ammeter_name": "greenlee",
            "current_a": 1.0,
            "measured_at_utc": self.timestamp,
            "monotonic_time_s": 2.0,
            "latency_seconds": 0.1,
        }
        for field_name in ("current_a", "monotonic_time_s", "latency_seconds"):
            for invalid in (math.nan, math.inf, -math.inf):
                with self.subTest(field=field_name, value=invalid):
                    values = dict(valid)
                    values[field_name] = invalid
                    with self.assertRaises(ValueError):
                        CurrentMeasurement(**values)  # type: ignore[arg-type]

    def test_negative_latency_is_rejected_but_signed_current_is_valid(self) -> None:
        with self.assertRaisesRegex(ValueError, "latency"):
            CurrentMeasurement(
                ammeter_name="greenlee",
                current_a=1.0,
                measured_at_utc=self.timestamp,
                monotonic_time_s=2.0,
                latency_seconds=-0.001,
            )

        measurement = CurrentMeasurement(
            ammeter_name="greenlee",
            current_a=-0.25,
            measured_at_utc=self.timestamp,
            monotonic_time_s=2.0,
            latency_seconds=0.0,
        )
        self.assertEqual(measurement.current_a, -0.25)

    def test_negative_monotonic_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "monotonic"):
            CurrentMeasurement(
                ammeter_name="greenlee",
                current_a=1.0,
                measured_at_utc=self.timestamp,
                monotonic_time_s=-0.001,
                latency_seconds=0.1,
            )

    def test_blank_ammeter_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            CurrentMeasurement(
                ammeter_name="   ",
                current_a=1.0,
                measured_at_utc=self.timestamp,
                monotonic_time_s=2.0,
                latency_seconds=0.1,
            )


if __name__ == "__main__":
    unittest.main()
