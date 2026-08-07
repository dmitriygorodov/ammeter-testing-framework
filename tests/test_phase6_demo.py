"""Filesystem integration for the read-only Phase 6 application helper."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import run_accuracy_assessment
from src.testing.archive import JsonResultArchive
from src.testing.archive_models import RunMetadata
from src.testing.accuracy_models import ReferenceCurrent
from src.utils import config as config_module

from tests.test_phase6_support import analyzed_result


@unittest.skipIf(config_module.yaml is None, "PyYAML is not installed")
class AccuracyAssessmentDemoTests(unittest.TestCase):
    def test_main_loads_archived_evidence_without_starting_devices_or_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_directory = root / "archive"
            archive = JsonResultArchive(archive_directory)
            metadata = RunMetadata(
                test_name="reference_accuracy",
                dut_id="dut-42",
                station_id="station-a",
                attributes=(("comparison_group", "demo-cohort"),),
            )
            archived = tuple(
                archive.save(
                    analyzed_result(values, ammeter_name=name),
                    metadata,
                )
                for name, values in (
                    ("alpha", (9.0, 11.0)),
                    ("bravo", (10.5, 10.5)),
                    ("charlie", (9.0, 9.0)),
                )
            )
            files_before = {
                str(path.relative_to(archive_directory)): path.read_bytes()
                for path in archive_directory.rglob("*.json")
            }
            archive_yaml = str(archive_directory).replace("\\", "/")
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    (
                        "communication:",
                        "  request_timeout_seconds: 1.0",
                        "ammeters:",
                        "  unused:",
                        '    host: "127.0.0.1"',
                        "    port: 65530",
                        '    command: "UNUSED"',
                        "result_management:",
                        f'  archive_directory: "{archive_yaml}"',
                        "",
                    )
                ),
                encoding="utf-8",
            )

            with patch("main._running_configured_emulators") as emulator_scope:
                assessment = run_accuracy_assessment(
                    config_path,
                    run_ids=tuple(item.run_id for item in reversed(archived)),
                    reference=ReferenceCurrent(
                        current_a=10.0,
                        source="demo setpoint",
                    ),
                )
                emulator_scope.assert_not_called()
            files_after = {
                str(path.relative_to(archive_directory)): path.read_bytes()
                for path in archive_directory.rglob("*.json")
            }

        self.assertEqual(
            tuple(item.ammeter_name for item in assessment.ammeters),
            ("alpha", "bravo", "charlie"),
        )
        self.assertEqual(assessment.comparison_group, "demo-cohort")
        self.assertEqual(assessment.most_accurate_ammeters, ("alpha",))
        self.assertEqual(assessment.most_precise_ammeters, ("bravo", "charlie"))
        self.assertEqual(assessment.most_reliable_ammeters, ("bravo",))
        self.assertEqual(files_after, files_before)


if __name__ == "__main__":
    unittest.main()
