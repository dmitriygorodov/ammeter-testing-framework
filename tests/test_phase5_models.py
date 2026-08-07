"""Model contracts for immutable Phase 5 archive evidence."""

from __future__ import annotations

import json
import string
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.testing.archive import JsonResultArchive
from src.testing.archive_models import (
    ArchivedResultSummary,
    ArchivedTestResult,
    HistoricalResultComparison,
    RunMetadata,
)

from tests.test_phase5_support import analyzed_result


FIRST_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
ARCHIVED_AT = datetime(2026, 8, 6, 13, 0, tzinfo=timezone.utc)


class RunMetadataTests(unittest.TestCase):
    def test_metadata_is_immutable_slotted_unicode_and_json_ready(self) -> None:
        metadata = RunMetadata(
            test_name="ammeter_sampling_analysis",
            operator="Dima",
            dut_id="DUT-α",
            station_id="ATE-01",
            notes="Phase 5 ✓",
            tags=("nightly", "interview"),
            attributes=(("build", "2026.08"), ("fixture", "loopback")),
        )

        self.assertFalse(hasattr(metadata, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            metadata.test_name = "changed"  # type: ignore[misc]
        serialized = metadata.to_dict()
        self.assertEqual(serialized["test_name"], "ammeter_sampling_analysis")
        self.assertEqual(serialized["dut_id"], "DUT-α")
        self.assertEqual(serialized["tags"], ["nightly", "interview"])
        json.dumps(serialized, allow_nan=False)

    def test_default_metadata_has_a_stable_test_name(self) -> None:
        metadata = RunMetadata()

        self.assertEqual(metadata.test_name, "ammeter_sampling_analysis")
        self.assertEqual(metadata.tags, ())
        self.assertEqual(metadata.attributes, ())

    def test_rejects_invalid_required_text_tags_and_attributes(self) -> None:
        for invalid_name in ("", "   ", " padded ", 7):
            with self.subTest(test_name=invalid_name):
                with self.assertRaises((TypeError, ValueError)):
                    RunMetadata(test_name=invalid_name)  # type: ignore[arg-type]

        invalid_tags = (("",), (" padded ",), ("same", "same"), (3,))
        for tags in invalid_tags:
            with self.subTest(tags=tags):
                with self.assertRaises((TypeError, ValueError)):
                    RunMetadata(tags=tags)  # type: ignore[arg-type]

        invalid_attributes = (
            (("", "value"),),
            ((" padded ", "value"),),
            (("key", object()),),
            (("same", "one"), ("same", "two")),
        )
        for attributes in invalid_attributes:
            with self.subTest(attributes=attributes):
                with self.assertRaises((TypeError, ValueError)):
                    RunMetadata(attributes=attributes)  # type: ignore[arg-type]

    def test_rejects_scalars_that_cannot_be_written_as_utf8_json(self) -> None:
        for invalid_value in (10**5_000, "\ud800"):
            with self.assertRaises(ValueError):
                RunMetadata(attributes=(("invalid", invalid_value),))


class ArchivedModelProjectionTests(unittest.TestCase):
    def test_saved_loaded_and_summary_records_are_typed_immutable_and_json_ready(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: FIRST_ID,
                wall_clock=lambda: ARCHIVED_AT,
            )
            expected_result = analyzed_result()
            metadata = RunMetadata(operator="Dima", tags=("nightly",))

            saved = archive.save(expected_result, metadata)
            loaded = archive.load(saved.run_id)
            summaries = archive.list_results()

        self.assertIsInstance(saved, ArchivedTestResult)
        self.assertEqual(saved, loaded)
        self.assertEqual(saved.run_id, str(FIRST_ID))
        self.assertEqual(saved.archived_at_utc, ARCHIVED_AT)
        self.assertEqual(saved.metadata, metadata)
        self.assertEqual(saved.analyzed_result, expected_result)
        self.assertEqual(len(saved.content_sha256), 64)
        self.assertTrue(
            all(character in string.hexdigits for character in saved.content_sha256)
        )
        self.assertFalse(hasattr(saved, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            saved.run_id = str(SECOND_ID)  # type: ignore[misc]
        json.dumps(saved.to_dict(), allow_nan=False)

        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertIsInstance(summary, ArchivedResultSummary)
        self.assertEqual(summary.run_id, saved.run_id)
        self.assertEqual(summary.archived_at_utc, saved.archived_at_utc)
        self.assertEqual(summary.metadata, saved.metadata)
        self.assertEqual(summary.ammeter_name, "greenlee")
        self.assertEqual(summary.sample_count, 3)
        self.assertEqual(summary.statistics, expected_result.statistics)
        self.assertEqual(summary.sampling_plan, expected_result.sampling_result.plan)
        self.assertEqual(summary.status, saved.status)
        json.dumps(summary.to_dict(), allow_nan=False)

    def test_comparison_record_reports_candidate_minus_baseline_deltas(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID))
        archived_times = iter(
            (
                ARCHIVED_AT,
                datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc),
            )
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                Path(temporary_directory),
                id_factory=lambda: next(ids),
                wall_clock=lambda: next(archived_times),
            )
            baseline = archive.save(analyzed_result((1.0, 2.0, 3.0)))
            candidate = archive.save(analyzed_result((2.0, 4.0, 6.0)))

            comparison = archive.compare(baseline.run_id, candidate.run_id)

        self.assertIsInstance(comparison, HistoricalResultComparison)
        self.assertEqual(comparison.baseline_run_id, baseline.run_id)
        self.assertEqual(comparison.candidate_run_id, candidate.run_id)
        self.assertEqual(comparison.ammeter_name, "greenlee")
        self.assertEqual(comparison.test_name, "ammeter_sampling_analysis")
        self.assertEqual(comparison.sample_count_delta, 0)
        self.assertEqual(comparison.mean_current_delta_a, 2.0)
        self.assertEqual(comparison.median_current_delta_a, 2.0)
        self.assertGreater(comparison.standard_deviation_current_delta_a, 0.0)
        self.assertEqual(comparison.minimum_current_delta_a, 1.0)
        self.assertEqual(comparison.maximum_current_delta_a, 3.0)
        self.assertTrue(comparison.sampling_plans_match)
        serialized = comparison.to_dict()
        self.assertIn("deltas", serialized)
        json.dumps(serialized, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
