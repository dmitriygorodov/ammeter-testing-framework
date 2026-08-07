"""Phase 7 acceptance configuration and override tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.utils.config import (
    AcceptanceConfig,
    ConfigurationError,
    load_application_config,
)


BASE_CONFIG = """
communication: {}
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


def _load(extra_yaml: str):
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "config.yaml"
        path.write_text(BASE_CONFIG + extra_yaml, encoding="utf-8")
        return load_application_config(path)


class AcceptanceConfigurationTests(unittest.TestCase):
    def test_global_policy_and_per_ammeter_override_are_resolved(self) -> None:
        config = _load(
            """
testing:
  acceptance:
    policy_name: "bench-current"
    policy_version: "2026.1"
    reference:
      current_a: 10.0
      source: "Fluke setpoint"
      expanded_uncertainty_a: 0.01
      calibration_id: "CAL-42"
    limits:
      minimum_current_a: 9.0
      maximum_current_a: 11.0
      maximum_absolute_bias_a: 0.5
      maximum_standard_deviation_a: 0.2
    ammeter_overrides:
      ENTES:
        limits:
          maximum_absolute_bias_a: 0.25
          maximum_standard_deviation_a: null
"""
        )

        self.assertIsInstance(config.acceptance, AcceptanceConfig)
        assert config.acceptance is not None
        greenlee = config.acceptance.policy_for("greenlee")
        entes = config.acceptance.policy_for("entes")
        assert greenlee is not None and entes is not None
        self.assertEqual(greenlee.limits.maximum_absolute_bias_a, 0.5)
        self.assertEqual(greenlee.limits.maximum_standard_deviation_a, 0.2)
        self.assertEqual(entes.limits.maximum_absolute_bias_a, 0.25)
        self.assertIsNone(entes.limits.maximum_standard_deviation_a)
        self.assertIs(entes.reference, greenlee.reference)

    def test_reference_can_be_replaced_for_one_ammeter(self) -> None:
        config = _load(
            """
testing:
  acceptance:
    policy_name: "bench-current"
    policy_version: "1"
    reference:
      current_a: 10.0
      source: "default source"
    limits:
      maximum_absolute_bias_a: 0.5
    ammeter_overrides:
      entes:
        reference:
          current_a: 2.0
          source: "ENTES source"
"""
        )

        assert config.acceptance is not None
        entes = config.acceptance.policy_for("ENTES")
        assert entes is not None and entes.reference is not None
        self.assertEqual(entes.reference.current_a, 2.0)
        self.assertEqual(entes.reference.source, "ENTES source")

    def test_absent_null_or_empty_acceptance_is_backward_compatible(self) -> None:
        sections = (
            "",
            "\ntesting: {}\n",
            "\ntesting:\n  acceptance: null\n",
            "\ntesting:\n  acceptance: {}\n",
        )
        for section in sections:
            with self.subTest(section=section):
                self.assertIsNone(_load(section).acceptance)

    def test_rejects_unknown_ammeter_and_unsupported_keys(self) -> None:
        invalid_sections = (
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: {maximum_current_a: 1.0}
    ammeter_overrides:
      missing:
        limits: {maximum_current_a: 2.0}
""",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: {maximum_current_a: 1.0, typo_limit: 2.0}
""",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: {maximum_current_a: 1.0}
    unexpected: true
""",
        )
        for section in invalid_sections:
            with self.subTest(section=section):
                with self.assertRaises(ConfigurationError):
                    _load(section)

    def test_rejects_invalid_numeric_ranges_and_shapes(self) -> None:
        invalid_sections = (
            "\ntesting:\n  acceptance: []\n",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: []
""",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: {minimum_current_a: 2.0, maximum_current_a: 1.0}
""",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: {maximum_standard_deviation_a: -0.1}
""",
        )
        for section in invalid_sections:
            with self.subTest(section=section):
                with self.assertRaises(ConfigurationError):
                    _load(section)

    def test_accuracy_limits_require_valid_reference_provenance(self) -> None:
        invalid_sections = (
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    limits: {maximum_absolute_bias_a: 0.1}
""",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    reference: {current_a: 0.0, source: zero}
    limits: {maximum_relative_error_percent: 1.0}
""",
            """
testing:
  acceptance:
    policy_name: p
    policy_version: '1'
    reference: {current_a: 10.0, source: ''}
    limits: {maximum_absolute_bias_a: 0.1}
""",
        )
        for section in invalid_sections:
            with self.subTest(section=section):
                with self.assertRaises(ConfigurationError):
                    _load(section)

    def test_section_may_define_only_targeted_ammeter_policies(self) -> None:
        config = _load(
            """
testing:
  acceptance:
    policy_name: timing
    policy_version: '1'
    limits: {}
    ammeter_overrides:
      greenlee:
        limits: {maximum_start_lateness_seconds: 0.1}
"""
        )

        assert config.acceptance is not None
        self.assertIsNotNone(config.acceptance.policy_for("greenlee"))
        self.assertIsNone(config.acceptance.policy_for("entes"))


if __name__ == "__main__":
    unittest.main()
