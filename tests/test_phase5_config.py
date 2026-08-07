"""Configuration tests for the optional Phase 5 JSON archive."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.utils.config import (
    ConfigurationError,
    ResultManagementConfig,
    load_application_config,
)


BASE_CONFIG = """
communication:
  request_timeout_seconds: 1.0
  server_startup_timeout_seconds: 2.0
  server_shutdown_timeout_seconds: 2.0
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE_GREENLEE -get_measurement"
"""


def _write_config(root: Path, result_management_yaml: str = "") -> Path:
    config_path = root / "config.yaml"
    config_path.write_text(
        BASE_CONFIG + result_management_yaml,
        encoding="utf-8",
    )
    return config_path


class ResultManagementConfigurationTests(unittest.TestCase):
    def test_valid_relative_archive_directory_is_typed_and_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "historical-results"
            config_path = _write_config(
                root,
                """
result_management:
  archive_directory: "historical-results"
""",
            )

            config = load_application_config(config_path)

            self.assertIsInstance(config.result_management, ResultManagementConfig)
            assert config.result_management is not None
            self.assertEqual(
                Path(config.result_management.archive_directory).resolve(),
                archive_path.resolve(),
            )
            self.assertFalse(archive_path.exists())

    def test_absolute_archive_directory_is_preserved_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "outside-config" / "archive"
            escaped_path = str(archive_path).replace("\\", "/")
            config_path = _write_config(
                root,
                f"""
result_management:
  archive_directory: "{escaped_path}"
""",
            )

            config = load_application_config(config_path)

            assert config.result_management is not None
            self.assertEqual(
                Path(config.result_management.archive_directory),
                archive_path.resolve(),
            )
            self.assertFalse(archive_path.exists())

    def test_missing_empty_or_null_section_preserves_previous_phase_compatibility(
        self,
    ) -> None:
        sections = (
            "",
            "\nresult_management: {}\n",
            "\nresult_management: null\n",
        )
        for section in sections:
            with self.subTest(section=section):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    config_path = _write_config(Path(temporary_directory), section)

                    config = load_application_config(config_path)

                    self.assertIsNone(config.result_management)

    def test_rejects_invalid_result_management_shapes_and_paths(self) -> None:
        invalid_sections = (
            "\nresult_management: []\n",
            "\nresult_management: enabled\n",
            "\nresult_management:\n  archive_directory: null\n",
            "\nresult_management:\n  archive_directory: ''\n",
            "\nresult_management:\n  archive_directory: '   '\n",
            "\nresult_management:\n  archive_directory: 42\n",
        )
        for section in invalid_sections:
            with self.subTest(section=section):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    config_path = _write_config(Path(temporary_directory), section)

                    with self.assertRaises(ConfigurationError):
                        load_application_config(config_path)

    def test_application_config_trailing_default_remains_constructor_compatible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = _write_config(Path(temporary_directory))

            config = load_application_config(config_path)

        self.assertIsNone(config.result_management)


if __name__ == "__main__":
    unittest.main()
