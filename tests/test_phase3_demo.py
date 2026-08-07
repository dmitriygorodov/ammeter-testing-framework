"""Loopback integration test for the complete Phase 3 sampling path."""

from __future__ import annotations

import math
import socket
import tempfile
import unittest
from pathlib import Path

from main import run_sampling_demo
from src.testing.models import SamplingStopReason


HOST = "127.0.0.1"


class SamplingDemoTests(unittest.TestCase):
    def test_sampling_demo_collects_all_devices_and_restarts(self) -> None:
        ports = self._find_available_ports(3)
        config_text = f"""
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
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(config_text, encoding="utf-8")
            first_run = run_sampling_demo(config_path)
            second_run = run_sampling_demo(config_path)

        for results in (first_run, second_run):
            self.assertEqual(set(results), {"greenlee", "entes", "circutor"})
            for result in results.values():
                self.assertEqual(result.sample_count, 3)
                self.assertEqual(
                    result.stop_reason,
                    SamplingStopReason.COUNT_REACHED,
                )
                self.assertTrue(
                    all(
                        math.isfinite(measurement.current_a)
                        for measurement in result.measurements
                    )
                )
                self.assertEqual(
                    [sample.scheduled_offset_seconds for sample in result.samples],
                    [0.0, 0.05, 0.1],
                )

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
