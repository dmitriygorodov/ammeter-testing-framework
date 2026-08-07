"""Unit tests for Phase 2's one-shot framework facade."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.devices.errors import UnknownAmmeterError
from src.devices.factory import AmmeterRegistry
from src.devices.models import CurrentMeasurement
from src.testing.test_framework import AmmeterTestFramework


class _FakeAmmeter:
    def __init__(
        self,
        name: str,
        current_a: float,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.current_a = current_a
        self.error = error
        self.calls = 0

    def read_current(self) -> CurrentMeasurement:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CurrentMeasurement(
            ammeter_name=self.name,
            current_a=self.current_a,
            measured_at_utc=datetime(2026, 8, 6, tzinfo=timezone.utc),
            monotonic_time_s=float(self.calls),
            latency_seconds=0.0,
        )


class _FalseyFactory:
    def __init__(self, registry: AmmeterRegistry) -> None:
        self.registry = registry
        self.received_config: object | None = None

    def __bool__(self) -> bool:
        return False

    def create_registry(self, config: object) -> AmmeterRegistry:
        self.received_config = config
        return self.registry


class AmmeterTestFrameworkTests(unittest.TestCase):
    def test_falsey_injected_factory_is_honored(self) -> None:
        sentinel_config = object()
        registry = AmmeterRegistry([_FakeAmmeter("greenlee", 1.0)])
        factory = _FalseyFactory(registry)

        with patch(
            "src.testing.test_framework.load_application_config",
            return_value=sentinel_config,
        ):
            framework = AmmeterTestFramework(factory=factory)  # type: ignore[arg-type]

        self.assertIs(factory.received_config, sentinel_config)
        self.assertEqual(framework.available_ammeters, ("greenlee",))

    def test_reports_available_ammeters_and_measures_one_by_normalized_name(self) -> None:
        greenlee = _FakeAmmeter("greenlee", 1.25)
        framework = AmmeterTestFramework(registry=AmmeterRegistry([greenlee]))

        result = framework.measure_once("  GREENLEE ")

        self.assertEqual(framework.available_ammeters, ("greenlee",))
        self.assertEqual(result.current_a, 1.25)
        self.assertEqual(greenlee.calls, 1)

    def test_measure_all_once_returns_name_keyed_results_in_registry_order(self) -> None:
        greenlee = _FakeAmmeter("greenlee", 1.0)
        entes = _FakeAmmeter("entes", 2.0)
        circutor = _FakeAmmeter("circutor", 3.0)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([greenlee, entes, circutor])
        )

        results = framework.measure_all_once()

        self.assertEqual(list(results), ["greenlee", "entes", "circutor"])
        self.assertEqual(
            [measurement.current_a for measurement in results.values()],
            [1.0, 2.0, 3.0],
        )
        self.assertEqual([greenlee.calls, entes.calls, circutor.calls], [1, 1, 1])

    def test_device_error_propagates_unchanged_from_one_and_all_operations(self) -> None:
        failure = RuntimeError("simulated instrument failure")
        failing = _FakeAmmeter("greenlee", 0.0, error=failure)
        framework = AmmeterTestFramework(registry=AmmeterRegistry([failing]))

        for operation in (
            lambda: framework.measure_once("greenlee"),
            framework.measure_all_once,
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(RuntimeError) as raised:
                    operation()
                self.assertIs(raised.exception, failure)

    def test_unknown_ammeter_error_propagates_from_registry(self) -> None:
        framework = AmmeterTestFramework(registry=AmmeterRegistry())

        with self.assertRaises(UnknownAmmeterError):
            framework.measure_once("missing")


if __name__ == "__main__":
    unittest.main()
