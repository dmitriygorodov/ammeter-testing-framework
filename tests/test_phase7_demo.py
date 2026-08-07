"""Phase 7 application helper fail-fast behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from main import run_acceptance_demo
from src.utils.config import ConfigurationError, DEFAULT_CONFIG_PATH


class AcceptanceDemoTests(unittest.TestCase):
    def test_default_config_requires_explicit_bench_policy_before_devices(self) -> None:
        with patch("main.AmmeterFactory.create_registry") as create_registry:
            with self.assertRaisesRegex(
                ConfigurationError,
                "testing.acceptance",
            ):
                run_acceptance_demo(DEFAULT_CONFIG_PATH)

        create_registry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
