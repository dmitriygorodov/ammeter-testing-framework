"""Framework integration tests for Phase 3 sampling runs."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.devices.errors import UnknownAmmeterError
from src.devices.factory import AmmeterRegistry
from src.testing.errors import SamplingConfigurationError
from src.testing.models import SamplingPlan
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import (
    AmmeterConfig,
    ApplicationConfig,
    CommunicationConfig,
    SamplingConfig,
)


class _FakeAmmeter:
    def __init__(self, name: str) -> None:
        self.name = name

    def read_current(self) -> object:
        raise AssertionError("The fake runner, not the framework, owns sampling")


class _FakeSamplingRunner:
    def __init__(
        self,
        result: object,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, SamplingPlan]] = []

    def run(self, ammeter: object, plan: SamplingPlan) -> object:
        self.calls.append((ammeter, plan))
        if self.error is not None:
            raise self.error
        return self.result


class _FakeFactory:
    def __init__(self, registry: AmmeterRegistry) -> None:
        self.registry = registry
        self.configs: list[ApplicationConfig] = []

    def create_registry(self, config: ApplicationConfig) -> AmmeterRegistry:
        self.configs.append(config)
        return self.registry


def _application_config(
    sampling: SamplingConfig | None,
) -> ApplicationConfig:
    return ApplicationConfig(
        ammeters=(
            AmmeterConfig(
                name="greenlee",
                host="127.0.0.1",
                port=5000,
                command="MEASURE",
            ),
        ),
        communication=CommunicationConfig(
            request_timeout_seconds=1.0,
            server_startup_timeout_seconds=2.0,
            server_shutdown_timeout_seconds=2.0,
        ),
        sampling=sampling,
    )


class AmmeterTestFrameworkSamplingTests(unittest.TestCase):
    def test_explicit_plan_uses_normalized_lookup_and_delegates_to_runner(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        expected_result = object()
        runner = _FakeSamplingRunner(expected_result)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
        )
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=3)

        result = framework.run_test("  GREENLEE ", plan)

        self.assertIs(result, expected_result)
        self.assertEqual(runner.calls, [(ammeter, plan)])

    def test_missing_explicit_and_configured_plan_raises_typed_error(self) -> None:
        runner = _FakeSamplingRunner(object())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([_FakeAmmeter("greenlee")]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
        )

        with self.assertRaises(SamplingConfigurationError):
            framework.run_test("greenlee")

        self.assertEqual(runner.calls, [])

    def test_uses_sampling_plan_loaded_with_application_configuration(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        registry = AmmeterRegistry([ammeter])  # type: ignore[list-item]
        factory = _FakeFactory(registry)
        runner = _FakeSamplingRunner(object())
        config = _application_config(
            SamplingConfig(
                sampling_frequency_hz=4.0,
                measurements_count=5,
                total_duration_seconds=2.0,
            )
        )

        with patch(
            "src.testing.test_framework.load_application_config",
            return_value=config,
        ):
            framework = AmmeterTestFramework(
                factory=factory,  # type: ignore[arg-type]
                sampling_runner=runner,  # type: ignore[arg-type]
            )

        framework.run_test("greenlee")

        self.assertEqual(factory.configs, [config])
        self.assertEqual(len(runner.calls), 1)
        used_ammeter, used_plan = runner.calls[0]
        self.assertIs(used_ammeter, ammeter)
        self.assertEqual(
            used_plan,
            SamplingPlan(
                sampling_frequency_hz=4.0,
                measurements_count=5,
                total_duration_seconds=2.0,
            ),
        )

    def test_explicit_plan_overrides_configured_default(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        registry = AmmeterRegistry([ammeter])  # type: ignore[list-item]
        factory = _FakeFactory(registry)
        runner = _FakeSamplingRunner(object())
        config = _application_config(
            SamplingConfig(
                sampling_frequency_hz=1.0,
                measurements_count=10,
                total_duration_seconds=None,
            )
        )
        explicit = SamplingPlan(
            sampling_frequency_hz=20.0,
            measurements_count=2,
        )

        with patch(
            "src.testing.test_framework.load_application_config",
            return_value=config,
        ):
            framework = AmmeterTestFramework(
                factory=factory,  # type: ignore[arg-type]
                sampling_runner=runner,  # type: ignore[arg-type]
            )

        framework.run_test("greenlee", explicit)

        self.assertEqual(runner.calls, [(ammeter, explicit)])

    def test_runner_error_propagates_unchanged(self) -> None:
        failure = RuntimeError("sampling failed")
        runner = _FakeSamplingRunner(object(), error=failure)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([_FakeAmmeter("greenlee")]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
        )
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=2)

        with self.assertRaises(RuntimeError) as raised:
            framework.run_test("greenlee", plan)

        self.assertIs(raised.exception, failure)

    def test_unknown_ammeter_fails_before_runner_is_called(self) -> None:
        runner = _FakeSamplingRunner(object())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            sampling_runner=runner,  # type: ignore[arg-type]
        )
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=2)

        with self.assertRaises(UnknownAmmeterError):
            framework.run_test("missing", plan)

        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
