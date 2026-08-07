"""Phase 9 visualization configuration is strict and side-effect free."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.utils.config import ConfigurationError, load_application_config


BASE = """
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE"
"""


class VisualizationConfigTests(unittest.TestCase):
    def _load(self, visualization_yaml: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = root / "config.yaml"
            config_path.write_text(
                BASE
                + "\nanalysis:\n  visualization:\n"
                + visualization_yaml,
                encoding="utf-8",
            )
            config = load_application_config(config_path)
            output_exists = (root / "plots").exists()
            return config, output_exists, root.resolve()

    def test_enabled_config_resolves_path_without_creating_it(self) -> None:
        config, output_exists, root = self._load(
            "    enabled: true\n"
            "    plot_types: [run_overview, accuracy, consistency]\n"
            "    output_directory: plots\n"
            "    image_format: svg\n"
            "    dpi: 240\n"
        )

        self.assertIsNotNone(config.visualization)
        visualization = config.visualization
        assert visualization is not None
        self.assertTrue(visualization.enabled)
        self.assertEqual(
            visualization.plot_types,
            ("run_overview", "accuracy", "consistency"),
        )
        self.assertEqual(visualization.output_directory, root / "plots")
        self.assertEqual(visualization.image_format, "svg")
        self.assertEqual(visualization.dpi, 240)
        self.assertFalse(output_exists)

    def test_absent_null_and_empty_visualization_are_backward_compatible(self) -> None:
        documents = (
            BASE,
            BASE + "\nanalysis:\n  visualization: null\n",
            BASE + "\nanalysis:\n  visualization: {}\n",
        )
        for document in documents:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    path = Path(temporary_directory) / "config.yaml"
                    path.write_text(document, encoding="utf-8")
                    self.assertIsNone(load_application_config(path).visualization)

    def test_disabled_config_may_reserve_output_defaults(self) -> None:
        config, output_exists, _ = self._load(
            "    enabled: false\n"
            "    plot_types: []\n"
            "    output_directory: plots\n"
        )
        assert config.visualization is not None
        self.assertEqual(config.visualization.image_format, "png")
        self.assertEqual(config.visualization.dpi, 160)
        self.assertFalse(output_exists)

    def test_enabled_requires_plot_types_and_output_directory(self) -> None:
        invalid_values = (
            "    enabled: true\n    plot_types: []\n    output_directory: plots\n",
            "    enabled: true\n    plot_types: [run_overview]\n",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    self._load(value)

    def test_unsupported_duplicate_and_malformed_plot_types_are_rejected(self) -> None:
        invalid_values = (
            "    enabled: false\n    plot_types: [unknown]\n",
            "    enabled: false\n    plot_types: [accuracy, accuracy]\n",
            "    enabled: false\n    plot_types: accuracy\n",
            "    enabled: yes\n    plot_types: []\n",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    self._load(value)

    def test_format_dpi_and_unknown_keys_are_rejected(self) -> None:
        invalid_values = (
            "    enabled: false\n    plot_types: []\n    image_format: jpg\n",
            "    enabled: false\n    plot_types: []\n    image_format: PNG\n",
            "    enabled: false\n    plot_types: []\n    dpi: 71\n",
            "    enabled: false\n    plot_types: []\n    dpi: 160.0\n",
            "    enabled: false\n    plot_types: []\n    surprise: true\n",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    self._load(value)


if __name__ == "__main__":
    unittest.main()
