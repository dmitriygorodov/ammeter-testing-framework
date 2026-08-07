"""Configuration tests for Phase 3 sampling defaults."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.utils.config import (
    ConfigurationError,
    SamplingConfig,
    load_application_config,
)


AMMETER_YAML = """
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE"
"""


def _load_yaml(document: str):  # type: ignore[no-untyped-def]
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "config.yaml"
        path.write_text(document, encoding="utf-8")
        return load_application_config(path)


class SamplingConfigurationTests(unittest.TestCase):
    def test_subnormal_frequency_with_infinite_period_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            SamplingConfig(
                sampling_frequency_hz=5e-324,
                measurements_count=1,
            )

    def test_huge_numeric_values_raise_typed_configuration_errors(self) -> None:
        for field_name in (
            "sampling_frequency_hz",
            "total_duration_seconds",
        ):
            with self.subTest(field=field_name):
                values = {
                    "sampling_frequency_hz": 1.0,
                    "measurements_count": 1,
                    "total_duration_seconds": 1.0,
                }
                values[field_name] = 10**400
                with self.assertRaises(ConfigurationError):
                    SamplingConfig(**values)  # type: ignore[arg-type]

    def test_loads_count_duration_and_frequency(self) -> None:
        config = _load_yaml(
            """
testing:
  sampling:
    measurements_count: 8
    total_duration_seconds: 2.5
    sampling_frequency_hz: 4
"""
            + AMMETER_YAML
        )

        self.assertIsNotNone(config.sampling)
        assert config.sampling is not None
        self.assertEqual(config.sampling.measurements_count, 8)
        self.assertEqual(config.sampling.total_duration_seconds, 2.5)
        self.assertEqual(config.sampling.sampling_frequency_hz, 4.0)

    def test_absent_or_all_null_sampling_has_no_default_plan(self) -> None:
        documents = (
            AMMETER_YAML,
            """
testing:
  sampling:
    measurements_count: null
    total_duration_seconds: null
    sampling_frequency_hz: null
"""
            + AMMETER_YAML,
        )
        for document in documents:
            with self.subTest(document=document):
                self.assertIsNone(_load_yaml(document).sampling)

    def test_partial_or_nonterminating_sampling_configuration_is_rejected(self) -> None:
        invalid_sampling_sections = (
            """
    measurements_count: 3
    total_duration_seconds: null
    sampling_frequency_hz: null
""",
            """
    measurements_count: null
    total_duration_seconds: null
    sampling_frequency_hz: 2
""",
        )
        for sampling_section in invalid_sampling_sections:
            with self.subTest(sampling_section=sampling_section):
                document = "testing:\n  sampling:\n" + sampling_section + AMMETER_YAML
                with self.assertRaises(ConfigurationError):
                    _load_yaml(document)

    def test_invalid_sampling_values_are_rejected(self) -> None:
        invalid_fields = (
            ("measurements_count", "true"),
            ("measurements_count", "0"),
            ("measurements_count", "1.5"),
            ("total_duration_seconds", "0"),
            ("total_duration_seconds", ".nan"),
            ("sampling_frequency_hz", "false"),
            ("sampling_frequency_hz", "0"),
            ("sampling_frequency_hz", ".inf"),
        )
        for field_name, invalid_value in invalid_fields:
            with self.subTest(field=field_name, value=invalid_value):
                values = {
                    "measurements_count": "2",
                    "total_duration_seconds": "1.0",
                    "sampling_frequency_hz": "4.0",
                }
                values[field_name] = invalid_value
                document = f"""
testing:
  sampling:
    measurements_count: {values['measurements_count']}
    total_duration_seconds: {values['total_duration_seconds']}
    sampling_frequency_hz: {values['sampling_frequency_hz']}
""" + AMMETER_YAML
                with self.assertRaises(ConfigurationError):
                    _load_yaml(document)

    def test_sampling_sections_must_be_mappings(self) -> None:
        for section in ("testing: []\n", "testing:\n  sampling: []\n"):
            with self.subTest(section=section):
                with self.assertRaises(ConfigurationError):
                    _load_yaml(section + AMMETER_YAML)

    def test_default_project_configuration_has_a_runnable_sampling_plan(self) -> None:
        self.assertIsNotNone(load_application_config().sampling)


if __name__ == "__main__":
    unittest.main()
