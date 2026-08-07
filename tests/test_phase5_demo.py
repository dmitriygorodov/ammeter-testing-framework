"""Loopback integration test for acquisition through historical comparison."""

from __future__ import annotations

import json
import math
import socket
import tempfile
import unittest
from pathlib import Path

from main import run_archive_demo
from src.testing.archive import JsonResultArchive
from src.testing.archive_models import ArchivedTestResult


HOST = "127.0.0.1"


class ArchiveDemoTests(unittest.TestCase):
    def test_archive_demo_persists_all_devices_filters_restarts_and_compares(
        self,
    ) -> None:
        ports = self._find_available_ports(3)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_directory = root / "results"
            archive_yaml_path = str(archive_directory).replace("\\", "/")
            config_path = root / "config.yaml"
            config_path.write_text(
                f"""
testing:
  sampling:
    measurements_count: 3
    total_duration_seconds: null
    sampling_frequency_hz: 20.0
communication:
  request_timeout_seconds: 1.0
  server_startup_timeout_seconds: 2.0
  server_shutdown_timeout_seconds: 2.0
ammeters:
  greenlee:
    host: "{HOST}"
    port: {ports[0]}
    command: "MEASURE_GREENLEE -get_measurement"
  entes:
    host: "{HOST}"
    port: {ports[1]}
    command: "MEASURE_ENTES -get_data"
  circutor:
    host: "{HOST}"
    port: {ports[2]}
    command: "MEASURE_CIRCUTOR -get_measurement"
result_management:
  archive_directory: "{archive_yaml_path}"
""",
                encoding="utf-8",
            )

            first_results = run_archive_demo(config_path)
            restarted_result = run_archive_demo(
                config_path,
                ammeter_name="  ENTES ",
            )

            archive = JsonResultArchive(archive_directory)
            summaries = archive.list_results()
            entes_summaries = archive.list_results(ammeter_name="entes")
            first_entes = first_results["entes"]
            second_entes = restarted_result["entes"]
            comparison = archive.compare(
                first_entes.run_id,
                second_entes.run_id,
            )
            reloaded = {
                name: archive.load(archived.run_id)
                for name, archived in first_results.items()
            }
            archive_files = list(archive_directory.rglob("*.json"))

        self.assertEqual(
            set(first_results),
            {"greenlee", "entes", "circutor"},
        )
        self.assertEqual(set(restarted_result), {"entes"})
        self.assertEqual(len(summaries), 4)
        self.assertEqual(len(entes_summaries), 2)
        self.assertEqual(len(archive_files), 4)
        self.assertEqual(
            len({summary.run_id for summary in summaries}),
            4,
        )

        for name, archived in first_results.items():
            with self.subTest(ammeter_name=name):
                self.assertIsInstance(archived, ArchivedTestResult)
                self.assertEqual(reloaded[name], archived)
                analyzed = archived.analyzed_result
                self.assertEqual(analyzed.ammeter_name, name)
                self.assertEqual(analyzed.sampling_result.sample_count, 3)
                self.assertEqual(analyzed.statistics.sample_count, 3)
                self.assertEqual(
                    archived.metadata.test_name,
                    "ammeter_sampling_analysis",
                )
                self.assertTrue(
                    all(
                        math.isfinite(value)
                        for value in (
                            analyzed.statistics.mean_current_a,
                            analyzed.statistics.median_current_a,
                            analyzed.statistics.standard_deviation_current_a,
                            analyzed.statistics.minimum_current_a,
                            analyzed.statistics.maximum_current_a,
                        )
                    )
                )
                json.dumps(archived.to_dict(), allow_nan=False)

        self.assertEqual(comparison.baseline_run_id, first_entes.run_id)
        self.assertEqual(comparison.candidate_run_id, second_entes.run_id)
        self.assertEqual(comparison.ammeter_name, "entes")
        self.assertTrue(comparison.sampling_plans_match)
        json.dumps(comparison.to_dict(), allow_nan=False)

    @staticmethod
    def _find_available_ports(count: int) -> list[int]:
        listeners: list[socket.socket] = []
        try:
            for _ in range(count):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind((HOST, 0))
                listeners.append(listener)
            return [int(listener.getsockname()[1]) for listener in listeners]
        finally:
            for listener in listeners:
                listener.close()


if __name__ == "__main__":
    unittest.main()
