"""Framework integration tests for explicit Phase 4 result analysis."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.devices.errors import UnknownAmmeterError
from src.devices.factory import AmmeterRegistry
from src.devices.models import CurrentMeasurement
from src.testing.models import (
    AnalyzedSamplingResult,
    CurrentStatistics,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)
from src.testing.test_framework import AmmeterTestFramework


BASE_UTC = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


class _FakeAmmeter:
    def __init__(self, name: str) -> None:
        self.name = name

    def read_current(self) -> CurrentMeasurement:
        raise AssertionError("The injected sampling runner owns acquisition")


class _FakeSamplingRunner:
    def __init__(
        self,
        result: SamplingRunResult,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, SamplingPlan]] = []

    def run(self, ammeter: object, plan: SamplingPlan) -> SamplingRunResult:
        self.calls.append((ammeter, plan))
        if self.error is not None:
            raise self.error
        return self.result


class _FalseyAnalyzer:
    def __init__(
        self,
        result: CurrentStatistics,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[SamplingRunResult] = []

    def __bool__(self) -> bool:
        return False

    def analyze(self, run: SamplingRunResult) -> CurrentStatistics:
        self.calls.append(run)
        if self.error is not None:
            raise self.error
        return self.result


def _sampling_run(
    plan: SamplingPlan,
    *,
    ammeter_name: str = "greenlee",
) -> SamplingRunResult:
    measurement = CurrentMeasurement(
        ammeter_name=ammeter_name,
        current_a=1.25,
        measured_at_utc=BASE_UTC + timedelta(seconds=0.01),
        monotonic_time_s=100.01,
        latency_seconds=0.01,
    )
    sample = SampledMeasurement(
        sample_index=0,
        scheduled_offset_seconds=0.0,
        started_offset_seconds=0.0,
        completed_offset_seconds=0.01,
        measurement=measurement,
    )
    return SamplingRunResult(
        ammeter_name=ammeter_name,
        plan=plan,
        samples=(sample,),
        started_at_utc=BASE_UTC,
        completed_at_utc=BASE_UTC + timedelta(seconds=0.01),
        started_monotonic_s=100.0,
        completed_monotonic_s=100.01,
        stop_reason=SamplingStopReason.COUNT_REACHED,
    )


def _statistics(*, ammeter_name: str = "greenlee") -> CurrentStatistics:
    return CurrentStatistics(
        ammeter_name=ammeter_name,
        sample_count=1,
        mean_current_a=1.25,
        median_current_a=1.25,
        standard_deviation_current_a=0.0,
        minimum_current_a=1.25,
        maximum_current_a=1.25,
    )


class AmmeterTestFrameworkAnalysisTests(unittest.TestCase):
    def test_analyze_result_honors_falsey_injection_and_delegates_once(self) -> None:
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        expected = _statistics()
        analyzer = _FalseyAnalyzer(expected)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        actual = framework.analyze_result(run)

        self.assertIs(actual, expected)
        self.assertEqual(analyzer.calls, [run])

    def test_run_analyzed_test_samples_then_analyzes_and_combines_evidence(
        self,
    ) -> None:
        ammeter = _FakeAmmeter("greenlee")
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        statistics = _statistics()
        runner = _FakeSamplingRunner(run)
        analyzer = _FalseyAnalyzer(statistics)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        result = framework.run_analyzed_test("  GREENLEE ", plan)

        self.assertIsInstance(result, AnalyzedSamplingResult)
        self.assertIs(result.sampling_result, run)
        self.assertIs(result.statistics, statistics)
        self.assertEqual(runner.calls, [(ammeter, plan)])
        self.assertEqual(analyzer.calls, [run])

    def test_run_analyzed_test_uses_the_default_sampling_plan(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=1)
        run = _sampling_run(plan)
        runner = _FakeSamplingRunner(run)
        analyzer = _FalseyAnalyzer(_statistics())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
            sampling_plan=plan,
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        framework.run_analyzed_test("greenlee")

        self.assertEqual(runner.calls, [(ammeter, plan)])
        self.assertEqual(analyzer.calls, [run])

    def test_plain_run_test_remains_sampling_only(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        runner = _FakeSamplingRunner(run)
        analyzer = _FalseyAnalyzer(_statistics())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        result = framework.run_test("greenlee", plan)

        self.assertIs(result, run)
        self.assertEqual(analyzer.calls, [])

    def test_sampling_failure_propagates_unchanged_and_skips_analysis(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        failure = RuntimeError("sampling failed")
        runner = _FakeSamplingRunner(run, error=failure)
        analyzer = _FalseyAnalyzer(_statistics())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        with self.assertRaises(RuntimeError) as raised:
            framework.run_analyzed_test("greenlee", plan)

        self.assertIs(raised.exception, failure)
        self.assertEqual(analyzer.calls, [])

    def test_analysis_failure_propagates_unchanged_after_sampling(self) -> None:
        ammeter = _FakeAmmeter("greenlee")
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        failure = RuntimeError("analysis failed")
        runner = _FakeSamplingRunner(run)
        analyzer = _FalseyAnalyzer(_statistics(), error=failure)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        with self.assertRaises(RuntimeError) as raised:
            framework.run_analyzed_test("greenlee", plan)

        self.assertIs(raised.exception, failure)
        self.assertEqual(runner.calls, [(ammeter, plan)])
        self.assertEqual(analyzer.calls, [run])

    def test_unknown_ammeter_fails_before_sampling_or_analysis(self) -> None:
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)
        run = _sampling_run(plan)
        runner = _FakeSamplingRunner(run)
        analyzer = _FalseyAnalyzer(_statistics())
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry(),
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        with self.assertRaises(UnknownAmmeterError):
            framework.run_analyzed_test("missing", plan)

        self.assertEqual(runner.calls, [])
        self.assertEqual(analyzer.calls, [])

    def test_result_analyzer_must_implement_analysis_contract(self) -> None:
        with self.assertRaises(TypeError):
            AmmeterTestFramework(
                registry=AmmeterRegistry(),
                result_analyzer=object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
