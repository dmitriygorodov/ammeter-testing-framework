from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.utils.config import (
    ConfigurationError,
    UsbAmmeterConfig,
    load_application_config,
)


class ApplicationConfigTests(unittest.TestCase):
    def test_default_config_is_independent_of_current_working_directory(self) -> None:
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary_directory:
            try:
                os.chdir(temporary_directory)
                config = load_application_config()
            finally:
                os.chdir(original_directory)

        self.assertEqual(
            [ammeter.name for ammeter in config.ammeters],
            ["greenlee", "entes", "circutor", "acme"],
        )
        self.assertEqual(
            [ammeter.port for ammeter in config.ammeters[:3]],
            [5000, 5001, 5002],
        )
        self.assertEqual(
            config.ammeters[2].command,
            "READ_CURRENT",
        )
        self.assertIsInstance(config.ammeters[3], UsbAmmeterConfig)
        self.assertTrue(config.ammeters[3].emulated)

    def test_duplicate_endpoint_is_rejected(self) -> None:
        invalid_config = """
ammeters:
  first:
    host: "127.0.0.1"
    port: 5000
    command: "FIRST"
  second:
    host: "127.0.0.1"
    port: 5000
    command: "SECOND"
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(invalid_config, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "Duplicate ammeter endpoint"):
                load_application_config(config_path)

    def test_duplicate_normalized_name_is_rejected(self) -> None:
        invalid_config = """
ammeters:
  Greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "FIRST"
  greenlee:
    host: "127.0.0.1"
    port: 5001
    command: "SECOND"
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(invalid_config, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "Duplicate ammeter name"):
                load_application_config(config_path)

    def test_non_finite_timeout_is_rejected(self) -> None:
        invalid_config = """
communication:
  request_timeout_seconds: .nan
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE"
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(invalid_config, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "positive finite"):
                load_application_config(config_path)

    def test_oversized_encoded_command_is_rejected(self) -> None:
        oversized_command = "M" * 1_025
        invalid_config = f"""
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "{oversized_command}"
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(invalid_config, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "1024 encoded bytes"):
                load_application_config(config_path)


if __name__ == "__main__":
    unittest.main()
