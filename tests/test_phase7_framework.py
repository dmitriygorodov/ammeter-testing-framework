"""Phase 7 framework orchestration and no-side-effect tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.devices.factory import AmmeterRegistry
from src.testing.acceptance_models import (
    AcceptanceLimits,
    AcceptancePolicy,
    EvaluatedSamplingResult,
)
from src.testing.errors import (
    AcceptancePolicyNotConfiguredError,
    ResultArchiveConfigurationError,
)
from src.testing.test_framework import AmmeterTestFramework

from tests.test_phase4_framework import (
    _FakeAmmeter,
    _FakeSamplingRunner,
    _FalseyAnalyzer,
    _sampling_run,
    _statistics,
)
from tests.test_phase6_support import analyzed_result, archived_result
from src.testing.models import SamplingPlan


def _policy(maximum_current_a: float = 20.0) -> AcceptancePolicy:
    return AcceptancePolicy(
        name="policy",
        version="1",
        limits=AcceptanceLimits(maximum_current_a=maximum_current_a),
    )


class _FalseyEvaluator:
    def __init__(self, result: object, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, AcceptancePolicy, str | None]] = []

    def __bool__(self) -> bool:
        return False

    def evaluate(
        self,
        result: object,
        *,
        policy: AcceptancePolicy,
        source_run_id: str | None,
    ) -> object:
        self.calls.append((result, policy, source_run_id))
        if self.error is not None:
            raise self.error
        return self.result


class _ReadOnlyArchive:
    def __init__(self, archived: object) -> None:
        self.archived = archived
        self.load_calls: list[str] = []

    def save(self, result: object, metadata: object = None) -> object:
        raise AssertionError("Phase 7 archived evaluation must not write")

    def load(self, run_id: str) -> object:
        self.load_calls.append(run_id)
        return self.archived

    def list_results(self, **filters: object) -> tuple[object, ...]:
        raise AssertionError("Phase 7 archived evaluation must not list")

    def compare(self, baseline_run_id: str, candidate_run_id: str) -> object:
        raise AssertionError("Phase 7 archived evaluation must not compare")


class AcceptanceFrameworkTests(unittest.TestCase):
    def test_direct_evaluation_honors_falsey_injection(self) -> None:
        analyzed = analyzed_result((10.0,), ammeter_name="greenlee")
        policy = _policy()
        sentinel = object()
        evaluator = _FalseyEvaluator(sentinel)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            result_evaluator=evaluator,  # type: ignore[arg-type]
        )

        actual = framework.evaluate_result(analyzed, policy=policy)

        self.assertIs(actual, sentinel)
        self.assertEqual(evaluator.calls, [(analyzed, policy, None)])

    def test_missing_policy_fails_before_evaluator_call(self) -> None:
        analyzed = analyzed_result((10.0,), ammeter_name="greenlee")
        evaluator = _FalseyEvaluator(object())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            result_evaluator=evaluator,  # type: ignore[arg-type]
        )

        with self.assertRaises(AcceptancePolicyNotConfiguredError):
            framework.evaluate_result(analyzed)

        self.assertEqual(evaluator.calls, [])

    def test_explicit_policy_overrides_constructor_default(self) -> None:
        analyzed = analyzed_result((10.0,), ammeter_name="greenlee")
        default = _policy(20.0)
        explicit = _policy(10.0)
        evaluator = _FalseyEvaluator(object())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            acceptance_policy=default,
            result_evaluator=evaluator,  # type: ignore[arg-type]
        )

        framework.evaluate_result(analyzed, policy=explicit)

        self.assertIs(evaluator.calls[0][1], explicit)

    def test_framework_selects_configured_ammeter_override(self) -> None:
        yaml_text = """
communication: {}
ammeters:
  greenlee:
    host: "127.0.0.1"
    port: 5000
    command: "MEASURE_GREENLEE -get_measurement"
testing:
  acceptance:
    policy_name: "configured"
    policy_version: "1"
    limits: {maximum_current_a: 20.0}
    ammeter_overrides:
      greenlee:
        limits: {maximum_current_a: 9.0}
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            framework = AmmeterTestFramework(config_path=path)

        verdict = framework.evaluate_result(
            analyzed_result((10.0,), ammeter_name="greenlee")
        )

        self.assertEqual(verdict.policy.identifier, "configured@1")
        self.assertEqual(verdict.checks[0].limit_value, 9.0)
        self.assertEqual(verdict.status.value, "fail")

    def test_run_evaluated_test_preserves_pipeline_evidence(self) -> None:
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        statistics = _statistics()
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([_FakeAmmeter("greenlee")]),  # type: ignore[list-item]
            sampling_runner=_FakeSamplingRunner(run),  # type: ignore[arg-type]
            result_analyzer=_FalseyAnalyzer(statistics),  # type: ignore[arg-type]
            acceptance_policy=_policy(),
        )

        result = framework.run_evaluated_test("greenlee", plan)

        self.assertIsInstance(result, EvaluatedSamplingResult)
        self.assertIs(result.analyzed_result.sampling_result, run)
        self.assertIs(result.analyzed_result.statistics, statistics)

    def test_run_evaluated_test_requires_policy_before_sampling(self) -> None:
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        runner = _FakeSamplingRunner(_sampling_run(plan))
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([_FakeAmmeter("greenlee")]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
        )

        with self.assertRaises(AcceptancePolicyNotConfiguredError):
            framework.run_evaluated_test("greenlee", plan)

        self.assertEqual(runner.calls, [])

    def test_archived_evaluation_loads_once_and_never_uses_devices_or_writes(self) -> None:
        archived = archived_result(
            (10.0,),
            ammeter_name="greenlee",
            run_number=88,
        )
        archive = _ReadOnlyArchive(archived)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            result_archive=archive,  # type: ignore[arg-type]
            acceptance_policy=_policy(),
        )

        verdict = framework.evaluate_archived_result(archived.run_id)

        self.assertEqual(archive.load_calls, [archived.run_id])
        self.assertEqual(verdict.source_run_id, archived.run_id)

    def test_missing_archive_fails_before_policy_selection(self) -> None:
        framework = AmmeterTestFramework(registry=AmmeterRegistry())

        with self.assertRaises(ResultArchiveConfigurationError):
            framework.evaluate_archived_result("not-even-loaded")

    def test_evaluator_errors_propagate_unchanged(self) -> None:
        analyzed = analyzed_result((10.0,), ammeter_name="greenlee")
        failure = RuntimeError("evaluation failed")
        evaluator = _FalseyEvaluator(object(), failure)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            acceptance_policy=_policy(),
            result_evaluator=evaluator,  # type: ignore[arg-type]
        )

        with self.assertRaises(RuntimeError) as raised:
            framework.evaluate_result(analyzed)

        self.assertIs(raised.exception, failure)

    def test_injected_evaluator_and_policy_contracts_are_validated(self) -> None:
        with self.assertRaises(TypeError):
            AmmeterTestFramework(
                registry=AmmeterRegistry(),
                acceptance_policy=object(),  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            AmmeterTestFramework(
                registry=AmmeterRegistry(),
                result_evaluator=object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
