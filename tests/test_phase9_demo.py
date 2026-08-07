"""Phase 9 archive-to-plot helper is read-only over stored evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main import render_archived_visualization
from src.testing.archive import JsonResultArchive
from src.testing.archive_models import RunMetadata
from src.testing.accuracy_models import ReferenceCurrent

from tests.test_phase6_support import analyzed_result


class VisualizationDemoTests(unittest.TestCase):
    def test_accuracy_plot_supports_explicit_legacy_ungrouped_uuid_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_directory = root / "archive"
            archive = JsonResultArchive(archive_directory)
            metadata = RunMetadata(
                test_name="legacy-reference-accuracy",
                station_id="station-a",
            )
            stored = tuple(
                archive.save(
                    analyzed_result(values, ammeter_name=name),
                    metadata,
                )
                for name, values in (
                    ("alpha", (0.99, 1.01)),
                    ("bravo", (1.0, 1.0)),
                )
            )
            before = {
                str(path.relative_to(archive_directory)): path.read_bytes()
                for path in archive_directory.rglob("*.json")
            }
            output = root / "plots" / "accuracy.svg"

            actual = render_archived_visualization(
                plot_type="accuracy",
                run_ids=tuple(item.run_id for item in stored),
                output_path=output,
                archive_directory=archive_directory,
                reference=ReferenceCurrent(
                    current_a=1.0,
                    source="calibrated source",
                ),
                dpi=160,
            )

            after = {
                str(path.relative_to(archive_directory)): path.read_bytes()
                for path in archive_directory.rglob("*.json")
            }
            self.assertEqual(actual, output.resolve())
            self.assertTrue(output.read_bytes().startswith(b"<?xml"))
            self.assertEqual(after, before)

    def test_run_overview_reads_archive_and_writes_only_requested_plot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_directory = root / "archive"
            archive = JsonResultArchive(archive_directory)
            stored = archive.save(
                analyzed_result(
                    (9.9, 10.0, 10.1),
                    ammeter_name="greenlee",
                ),
                RunMetadata(test_name="phase9-demo"),
            )
            archive_file = next(archive_directory.rglob(f"{stored.run_id}.json"))
            original_bytes = archive_file.read_bytes()
            output = root / "plots" / "run.png"

            actual = render_archived_visualization(
                root / "configuration-must-not-be-read.yaml",
                plot_type="run_overview",
                run_ids=(stored.run_id,),
                output_path=output,
                archive_directory=archive_directory,
            )

            self.assertEqual(actual, output.resolve())
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(archive_file.read_bytes(), original_bytes)
            self.assertEqual(
                sorted(path.name for path in archive_directory.iterdir()),
                ["general"],
            )

    def test_enabled_configuration_supplies_archive_and_output_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root / "archive")
            stored = archive.save(
                analyzed_result((1.0, 1.01), ammeter_name="greenlee"),
                RunMetadata(test_name="configured-plot"),
            )
            config_directory = root / "config"
            config_directory.mkdir()
            config_path = config_directory / "config.yaml"
            config_path.write_text(
                """
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE"
result_management:
  archive_directory: "../archive"
analysis:
  visualization:
    enabled: true
    plot_types: [run_overview]
    output_directory: "../plots"
    image_format: svg
    dpi: 180
""",
                encoding="utf-8",
            )

            actual = render_archived_visualization(
                config_path,
                plot_type="run_overview",
                run_ids=(stored.run_id,),
            )

            expected = root / "plots" / f"run_overview-{stored.run_id}.svg"
            self.assertEqual(actual, expected.resolve())
            self.assertTrue(expected.read_bytes().startswith(b"<?xml"))

    def test_plot_type_and_run_count_are_validated_before_archive_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaises(ValueError):
                render_archived_visualization(
                    plot_type="unknown",
                    run_ids=("not-read",),
                    output_path=root / "x.png",
                    archive_directory=root / "missing",
                    dpi=160,
                )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                render_archived_visualization(
                    plot_type="run_overview",
                    run_ids=("one", "two"),
                    output_path=root / "x.png",
                    archive_directory=root / "missing",
                    dpi=160,
                )
            self.assertFalse((root / "missing").exists())


if __name__ == "__main__":
    unittest.main()
