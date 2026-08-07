"""Framework integration tests for explicit Phase 5 result management."""

from __future__ import annotations

import unittest
from typing import Any

from src.devices.factory import AmmeterRegistry
from src.devices.models import CurrentMeasurement
from src.testing.archive_models import RunMetadata
from src.testing.errors import ResultArchiveConfigurationError
from src.testing.models import (
    AnalyzedSamplingResult,
    CurrentStatistics,
    SamplingPlan,
    SamplingRunResult,
)
from src.testing.test_framework import AmmeterTestFramework

from tests.test_phase5_support import analyzed_result


class _FakeAmmeter:
    def __init__(self, name: str) -> None:
        self.name = name

    def read_current(self) -> CurrentMeasurement:
        raise AssertionError("The injected sampling runner owns acquisition")


class _RecordingSamplingRunner:
    def __init__(
        self,
        result: SamplingRunResult,
        events: list[str],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.events = events
        self.error = error
        self.calls: list[tuple[object, SamplingPlan]] = []

    def run(self, ammeter: object, plan: SamplingPlan) -> SamplingRunResult:
        self.events.append("sample")
        self.calls.append((ammeter, plan))
        if self.error is not None:
            raise self.error
        return self.result


class _RecordingAnalyzer:
    def __init__(
        self,
        result: CurrentStatistics,
        events: list[str],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.events = events
        self.error = error
        self.calls: list[SamplingRunResult] = []

    def analyze(self, run: SamplingRunResult) -> CurrentStatistics:
        self.events.append("analyze")
        self.calls.append(run)
        if self.error is not None:
            raise self.error
        return self.result


class _FalseyArchive:
    def __init__(
        self,
        archived_result: object,
        events: list[str] | None = None,
        *,
        save_error: BaseException | None = None,
    ) -> None:
        self.archived_result = archived_result
        self.events = events if events is not None else []
        self.save_error = save_error
        self.save_calls: list[tuple[AnalyzedSamplingResult, RunMetadata | None]] = []
        self.load_calls: list[str] = []
        self.list_calls: list[dict[str, str | None]] = []
        self.compare_calls: list[tuple[str, str]] = []
        self.loaded_result = object()
        self.listed_results: tuple[object, ...] = (object(),)
        self.comparison = object()

    def __bool__(self) -> bool:
        return False

    def save(
        self,
        result: AnalyzedSamplingResult,
        metadata: RunMetadata | None = None,
    ) -> object:
        self.events.append("archive")
        self.save_calls.append((result, metadata))
        if self.save_error is not None:
            raise self.save_error
        return self.archived_result

    def load(self, run_id: str) -> object:
        self.load_calls.append(run_id)
        return self.loaded_result

    def list_results(
        self,
        ammeter_name: str | None = None,
        test_name: str | None = None,
        tag: str | None = None,
    ) -> tuple[object, ...]:
        self.list_calls.append(
            {
                "ammeter_name": ammeter_name,
                "test_name": test_name,
                "tag": tag,
            }
        )
        return self.listed_results

    def compare(self, baseline_id: str, candidate_id: str) -> object:
        self.compare_calls.append((baseline_id, candidate_id))
        return self.comparison


def _framework_components(
    *,
    events: list[str] | None = None,
    use_default_plan: bool = False,
    sample_error: BaseException | None = None,
    analysis_error: BaseException | None = None,
    archive_error: BaseException | None = None,
) -> tuple[
    AmmeterTestFramework,
    SamplingPlan,
    _RecordingSamplingRunner,
    _RecordingAnalyzer,
    _FalseyArchive,
]:
    event_log = events if events is not None else []
    analyzed = analyzed_result()
    plan = analyzed.sampling_result.plan
    ammeter = _FakeAmmeter("greenlee")
    runner = _RecordingSamplingRunner(
        analyzed.sampling_result,
        event_log,
        error=sample_error,
    )
    analyzer = _RecordingAnalyzer(
        analyzed.statistics,
        event_log,
        error=analysis_error,
    )
    archive = _FalseyArchive(
        object(),
        event_log,
        save_error=archive_error,
    )
    framework = AmmeterTestFramework(
        registry=AmmeterRegistry([ammeter]),  # type: ignore[list-item]
        sampling_plan=plan if use_default_plan else None,
        sampling_runner=runner,  # type: ignore[arg-type]
        result_analyzer=analyzer,  # type: ignore[arg-type]
        result_archive=archive,  # type: ignore[arg-type]
    )
    return framework, plan, runner, analyzer, archive


class AmmeterTestFrameworkArchiveTests(unittest.TestCase):
    def test_archive_result_honors_falsey_injection_and_delegates_once(self) -> None:
        framework, _, runner, analyzer, archive = _framework_components()
        analyzed = analyzed_result()
        metadata = RunMetadata(operator="Dima")

        actual = framework.archive_result(analyzed, metadata=metadata)

        self.assertIs(actual, archive.archived_result)
        self.assertEqual(archive.save_calls, [(analyzed, metadata)])
        self.assertEqual(runner.calls, [])
        self.assertEqual(analyzer.calls, [])

    def test_run_archived_test_orders_sampling_analysis_and_archive(self) -> None:
        events: list[str] = []
        framework, plan, runner, analyzer, archive = _framework_components(
            events=events
        )
        metadata = RunMetadata(tags=("nightly",))

        actual = framework.run_archived_test(
            "  GREENLEE ",
            plan,
            metadata=metadata,
        )

        self.assertIs(actual, archive.archived_result)
        self.assertEqual(events, ["sample", "analyze", "archive"])
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(analyzer.calls, [runner.result])
        archived_input, archived_metadata = archive.save_calls[0]
        self.assertIs(archived_input.sampling_result, runner.result)
        self.assertIs(archived_input.statistics, analyzer.result)
        self.assertIs(archived_metadata, metadata)

    def test_run_archived_test_uses_default_plan_and_default_metadata(self) -> None:
        framework, plan, runner, _, archive = _framework_components(
            use_default_plan=True
        )

        framework.run_archived_test("greenlee")

        self.assertEqual(runner.calls[-1][1], plan)
        self.assertEqual(archive.save_calls[-1][1], None)

    def test_failures_stop_the_pipeline_and_propagate_unchanged(self) -> None:
        stages: tuple[tuple[str, BaseException], ...] = (
            ("sample", RuntimeError("sampling failed")),
            ("analysis", RuntimeError("analysis failed")),
            ("archive", RuntimeError("archive failed")),
        )
        for stage, failure in stages:
            with self.subTest(stage=stage):
                events: list[str] = []
                framework, plan, _, _, archive = _framework_components(
                    events=events,
                    sample_error=failure if stage == "sample" else None,
                    analysis_error=failure if stage == "analysis" else None,
                    archive_error=failure if stage == "archive" else None,
                )

                with self.assertRaises(RuntimeError) as raised:
                    framework.run_archived_test("greenlee", plan)

                self.assertIs(raised.exception, failure)
                expected_events = {
                    "sample": ["sample"],
                    "analysis": ["sample", "analyze"],
                    "archive": ["sample", "analyze", "archive"],
                }
                self.assertEqual(events, expected_events[stage])
                if stage != "archive":
                    self.assertEqual(archive.save_calls, [])

    def test_existing_analysis_path_does_not_archive_implicitly(self) -> None:
        framework, plan, _, _, archive = _framework_components()

        framework.run_analyzed_test("greenlee", plan)

        self.assertEqual(archive.save_calls, [])

    def test_retrieval_listing_and_comparison_delegate_without_device_access(
        self,
    ) -> None:
        framework, _, runner, analyzer, archive = _framework_components()

        loaded = framework.load_archived_result("run-one")
        listed = framework.list_archived_results(
            ammeter_name="greenlee",
            test_name="ammeter_sampling_analysis",
            tag="nightly",
        )
        compared = framework.compare_archived_results("run-one", "run-two")

        self.assertIs(loaded, archive.loaded_result)
        self.assertIs(listed, archive.listed_results)
        self.assertIs(compared, archive.comparison)
        self.assertEqual(archive.load_calls, ["run-one"])
        self.assertEqual(
            archive.list_calls,
            [
                {
                    "ammeter_name": "greenlee",
                    "test_name": "ammeter_sampling_analysis",
                    "tag": "nightly",
                }
            ],
        )
        self.assertEqual(archive.compare_calls, [("run-one", "run-two")])
        self.assertEqual(runner.calls, [])
        self.assertEqual(analyzer.calls, [])

    def test_archive_service_must_implement_the_complete_contract(self) -> None:
        with self.assertRaises(TypeError):
            AmmeterTestFramework(
                registry=AmmeterRegistry(),
                result_archive=object(),  # type: ignore[arg-type]
            )

    def test_archive_operations_require_a_configured_archive(self) -> None:
        framework = AmmeterTestFramework(registry=AmmeterRegistry())
        analyzed = analyzed_result()

        operations: tuple[tuple[str, Any], ...] = (
            ("save", lambda: framework.archive_result(analyzed)),
            ("load", lambda: framework.load_archived_result("run-id")),
            ("list", framework.list_archived_results),
            (
                "compare",
                lambda: framework.compare_archived_results("one", "two"),
            ),
        )
        for operation_name, operation in operations:
            with self.subTest(operation=operation_name):
                with self.assertRaises(RuntimeError):
                    operation()

    def test_archived_run_fails_before_acquisition_without_archive(self) -> None:
        analyzed = analyzed_result()
        events: list[str] = []
        runner = _RecordingSamplingRunner(analyzed.sampling_result, events)
        analyzer = _RecordingAnalyzer(analyzed.statistics, events)
        framework = AmmeterTestFramework(
            registry=AmmeterRegistry([_FakeAmmeter("greenlee")]),  # type: ignore[list-item]
            sampling_runner=runner,  # type: ignore[arg-type]
            result_analyzer=analyzer,  # type: ignore[arg-type]
        )

        with self.assertRaises(ResultArchiveConfigurationError):
            framework.run_archived_test(
                "greenlee",
                analyzed.sampling_result.plan,
            )

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
