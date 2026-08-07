"""Phase 10 configuration reaches emulators without creating false archives."""

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from main import run_acceptance_demo, run_archive_demo
from src.devices.errors import AmmeterProtocolError
from src.testing.acceptance_models import VerdictStatus


HOST = "127.0.0.1"


class FaultScenarioDemoTests(unittest.TestCase):
    def test_each_ammeter_offset_remains_valid_evidence_and_produces_fail(self) -> None:
        ports = self._find_available_ports(3)
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                f"""
communication:
  request_timeout_seconds: 0.5
  server_startup_timeout_seconds: 2.0
  server_shutdown_timeout_seconds: 2.0
testing:
  sampling:
    measurements_count: 1
    sampling_frequency_hz: 10.0
  acceptance:
    policy_name: simulated-overcurrent
    policy_version: "1"
    limits:
      maximum_current_a: 100.0
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
emulation:
  fault_injection:
    enabled: true
    ammeters:
      greenlee:
        - request_number: 1
          type: current_offset
          current_offset_a: 1000.0
      entes:
        - request_number: 1
          type: current_offset
          current_offset_a: 1000.0
      circutor:
        - request_number: 1
          type: current_offset
          current_offset_a: 1000.0
""",
                encoding="utf-8",
            )

            results = run_acceptance_demo(config_path)

            self.assertEqual(set(results), {"greenlee", "entes", "circutor"})
            for ammeter_name, result in results.items():
                with self.subTest(ammeter_name=ammeter_name):
                    self.assertIs(result.verdict.status, VerdictStatus.FAIL)
                    self.assertGreater(
                        result.analyzed_result.statistics.maximum_current_a,
                        100.0,
                    )

    def test_configured_execution_fault_propagates_and_creates_no_archive(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((HOST, 0))
            port = int(probe.getsockname()[1])
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_directory = root / "archive"
            config_path = root / "config.yaml"
            config_path.write_text(
                f"""
communication:
  request_timeout_seconds: 0.25
  server_startup_timeout_seconds: 2.0
  server_shutdown_timeout_seconds: 2.0
testing:
  sampling:
    measurements_count: 3
    sampling_frequency_hz: 10.0
ammeters:
  greenlee:
    host: "{HOST}"
    port: {port}
    command: "MEASURE_GREENLEE -get_measurement"
result_management:
  archive_directory: "archive"
emulation:
  fault_injection:
    enabled: true
    ammeters:
      greenlee:
        - request_number: 1
          type: error_response
          error_message: simulated ADC failure
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(AmmeterProtocolError, "simulated ADC"):
                run_archive_demo(config_path)

            self.assertFalse(archive_directory.exists())
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind((HOST, port))

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
