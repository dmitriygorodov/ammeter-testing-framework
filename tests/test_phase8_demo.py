"""Read-only Phase 8 application helper integration."""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from main import run_consistency_assessment
from src.testing.archive import JsonResultArchive
from src.testing.archive_models import RunMetadata

from tests.test_phase5_support import analyzed_result
from tests.test_phase8_support import BASE_UTC


class ConsistencyAssessmentDemoTests(unittest.TestCase):
    def test_explicit_archive_is_read_only_and_bypasses_config_and_devices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_directory = Path(temporary_directory) / "archive"
            archive = JsonResultArchive(archive_directory)
            metadata = RunMetadata(
                test_name="long_term_stability",
                dut_id="dut-42",
                station_id="station-a",
                attributes=(("consistency_group", "demo-history"),),
            )
            archived = tuple(
                archive.save(
                    analyzed_result(
                        values,
                        started_at_utc=BASE_UTC + timedelta(hours=index),
                    ),
                    metadata,
                )
                for index, values in enumerate(
                    ((9.0, 11.0), (10.0, 12.0), (11.0, 13.0))
                )
            )
            files_before = {
                str(path.relative_to(archive_directory)): path.read_bytes()
                for path in archive_directory.rglob("*.json")
            }

            with (
                patch("main.load_application_config") as load_config,
                patch("main._running_configured_emulators") as emulator_scope,
            ):
                assessment = run_consistency_assessment(
                    "missing-config.yaml",
                    run_ids=tuple(item.run_id for item in reversed(archived)),
                    archive_directory=archive_directory,
                )
                load_config.assert_not_called()
                emulator_scope.assert_not_called()
            files_after = {
                str(path.relative_to(archive_directory)): path.read_bytes()
                for path in archive_directory.rglob("*.json")
            }

        self.assertEqual(assessment.consistency_group, "demo-history")
        self.assertAlmostEqual(assessment.metrics.trend_slope_a_per_hour, 1.0)
        self.assertEqual(files_after, files_before)


if __name__ == "__main__":
    unittest.main()
