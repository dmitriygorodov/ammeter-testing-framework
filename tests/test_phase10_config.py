"""Phase 10 fault schedules are strict, opt-in, and ammeter-scoped."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Ammeters.faults import FaultKind
from src.utils.config import ConfigurationError, load_application_config


BASE = """
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE_GREENLEE -get_measurement"
  entes:
    host: "127.0.0.1"
    port: 5001
    command: "MEASURE_ENTES -get_data"
"""
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FaultInjectionConfigTests(unittest.TestCase):
    def _load(self, fault_yaml: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text(
                BASE + "\nemulation:\n  fault_injection:\n" + fault_yaml,
                encoding="utf-8",
            )
            return load_application_config(path)

    def test_all_fault_types_load_and_rules_are_sorted_deterministically(self) -> None:
        config = self._load(
            "    enabled: true\n"
            "    ammeters:\n"
            "      greenlee:\n"
            "        - request_number: 5\n"
            "          type: current_offset\n"
            "          current_offset_a: 0.75\n"
            "        - request_number: 1\n"
            "          type: response_delay\n"
            "          delay_seconds: 0.2\n"
            "        - request_number: 2\n"
            "          type: error_response\n"
            "          error_message: simulated sensor fault\n"
            "        - request_number: 3\n"
            "          type: malformed_response\n"
            "          response_payload: nan\n"
            "        - request_number: 4\n"
            "          type: disconnect\n"
        )

        self.assertIsNotNone(config.fault_injection)
        faults = config.fault_injection
        assert faults is not None
        profile = faults.profile_for(" GREENLEE ")
        assert profile is not None
        self.assertEqual(
            tuple(rule.request_number for rule in profile.rules),
            (1, 2, 3, 4, 5),
        )
        self.assertEqual(
            tuple(rule.kind for rule in profile.rules),
            tuple(FaultKind),
        )
        self.assertIsNone(faults.profile_for("entes"))

    def test_checked_in_example_covers_all_configured_ammeters(self) -> None:
        config = load_application_config(
            PROJECT_ROOT / "config" / "fault-scenario.example.yaml"
        )
        faults = config.fault_injection
        assert faults is not None

        self.assertTrue(faults.enabled)
        self.assertEqual(
            {ammeter.name for ammeter in config.ammeters},
            {"greenlee", "entes", "circutor"},
        )
        for ammeter_name in ("greenlee", "entes", "circutor"):
            with self.subTest(ammeter_name=ammeter_name):
                profile = faults.profile_for(ammeter_name)
                assert profile is not None
                self.assertEqual(len(profile.rules), 1)
                rule = profile.rules[0]
                self.assertEqual(rule.request_number, 1)
                self.assertIs(rule.kind, FaultKind.CURRENT_OFFSET)
                self.assertEqual(rule.current_offset_a, 1000.0)

    def test_absent_null_empty_and_explicitly_disabled_are_safe_defaults(self) -> None:
        documents = (
            BASE,
            BASE + "\nemulation: null\n",
            BASE + "\nemulation:\n  fault_injection: null\n",
            BASE + "\nemulation:\n  fault_injection: {}\n",
        )
        for document in documents:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    path = Path(temporary_directory) / "config.yaml"
                    path.write_text(document, encoding="utf-8")
                    self.assertIsNone(load_application_config(path).fault_injection)
        disabled = self._load("    enabled: false\n    ammeters: {}\n")
        assert disabled.fault_injection is not None
        self.assertFalse(disabled.fault_injection.enabled)

    def test_enabled_requires_profiles_and_disabled_rejects_hidden_rules(self) -> None:
        invalid_values = (
            "    enabled: true\n    ammeters: {}\n",
            "    enabled: false\n"
            "    ammeters:\n"
            "      greenlee:\n"
            "        - {request_number: 1, type: disconnect}\n",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    self._load(value)

    def test_unknown_ammeters_duplicate_requests_and_bad_fields_are_rejected(self) -> None:
        invalid_values = (
            "    enabled: true\n"
            "    ammeters:\n"
            "      unknown:\n"
            "        - {request_number: 1, type: disconnect}\n",
            "    enabled: true\n"
            "    ammeters:\n"
            "      greenlee:\n"
            "        - {request_number: 1, type: disconnect}\n"
            "        - {request_number: 1, type: disconnect}\n",
            "    enabled: true\n"
            "    ammeters:\n"
            "      greenlee:\n"
            "        - {request_number: 1, type: mystery}\n",
            "    enabled: true\n"
            "    ammeters:\n"
            "      greenlee:\n"
            "        - {request_number: 1, type: disconnect, surprise: true}\n",
            "    enabled: yes\n    ammeters: {}\n",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    self._load(value)

    def test_kind_specific_invalid_parameters_are_rejected_during_loading(self) -> None:
        invalid_rules = (
            "{request_number: 1, type: response_delay, delay_seconds: 0}",
            "{request_number: 1, type: error_response}",
            "{request_number: 1, type: malformed_response, response_payload: '1.0'}",
            "{request_number: 1, type: current_offset, current_offset_a: .nan}",
            "{request_number: 1, type: disconnect, delay_seconds: 1}",
        )
        for rule in invalid_rules:
            with self.subTest(rule=rule):
                with self.assertRaises(ConfigurationError):
                    self._load(
                        "    enabled: true\n"
                        "    ammeters:\n"
                        "      greenlee:\n"
                        f"        - {rule}\n"
                    )


if __name__ == "__main__":
    unittest.main()
