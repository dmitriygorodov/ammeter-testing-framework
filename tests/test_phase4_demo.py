"""Loopback integration test for the complete Phase 4 analysis path."""

from __future__ import annotations

import json
import math
import socket
import statistics as statistics_module
import tempfile
import unittest
from pathlib import Path

from main import run_analysis_demo
from src.testing.models import AnalyzedSamplingResult


HOST = "127.0.0.1"


class AnalysisDemoTests(unittest.TestCase):
    def test_analysis_demo_reports_all_metrics_filters_and_restarts(self) -> None:
        ports = self._find_available_ports(3)
        config_text = f"""
testing:
  sampling:
    measurements_count: 4
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
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(config_text, encoding="utf-8")
            all_results = run_analysis_demo(config_path)
            filtered_results = run_analysis_demo(
                config_path,
                ammeter_name="  ENTES ",
            )

        self.assertEqual(set(all_results), {"greenlee", "entes", "circutor"})
        self.assertEqual(set(filtered_results), {"entes"})
        for results in (all_results, filtered_results):
            for ammeter_name, analyzed in results.items():
                with self.subTest(
                    result_set_size=len(results),
                    ammeter_name=ammeter_name,
                ):
                    self.assertIsInstance(analyzed, AnalyzedSamplingResult)
                    run = analyzed.sampling_result
                    current_statistics = analyzed.statistics
                    values = tuple(
                        measurement.current_a for measurement in run.measurements
                    )

                    self.assertEqual(run.ammeter_name, ammeter_name)
                    self.assertEqual(run.sample_count, 4)
                    self.assertEqual(current_statistics.ammeter_name, ammeter_name)
                    self.assertEqual(current_statistics.sample_count, 4)
                    self.assertAlmostEqual(
                        current_statistics.mean_current_a,
                        statistics_module.fmean(values),
                    )
                    self.assertAlmostEqual(
                        current_statistics.median_current_a,
                        statistics_module.median(values),
                    )
                    self.assertAlmostEqual(
                        current_statistics.standard_deviation_current_a,
                        statistics_module.pstdev(values),
                    )
                    self.assertEqual(
                        current_statistics.minimum_current_a,
                        min(values),
                    )
                    self.assertEqual(
                        current_statistics.maximum_current_a,
                        max(values),
                    )
                    self.assertTrue(
                        all(
                            math.isfinite(metric)
                            for metric in (
                                current_statistics.mean_current_a,
                                current_statistics.median_current_a,
                                current_statistics.standard_deviation_current_a,
                                current_statistics.minimum_current_a,
                                current_statistics.maximum_current_a,
                            )
                        )
                    )
                    self.assertLessEqual(
                        current_statistics.minimum_current_a,
                        current_statistics.median_current_a,
                    )
                    self.assertLessEqual(
                        current_statistics.median_current_a,
                        current_statistics.maximum_current_a,
                    )
                    json.dumps(analyzed.to_dict())

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
