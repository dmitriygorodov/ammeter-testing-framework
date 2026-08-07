"""Phase 8 framework delegation and archive-read boundaries."""

from __future__ import annotations

import unittest

from src.testing.errors import IncomparableHistoryError, ResultArchiveConfigurationError
from src.testing.test_framework import AmmeterTestFramework

from tests.test_phase8_support import representative_history


class _NoDeviceRegistry:
    names: tuple[str, ...] = ()

    def get(self, name: str) -> object:
        raise AssertionError(f"Phase 8 must not access hardware: {name}")


class _RecordingConsistencyAnalyzer:
    def __init__(self, result: object, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[object] = []

    def __bool__(self) -> bool:
        return False

    def assess(self, results: object) -> object:
        self.calls.append(results)
        if self.error is not None:
            raise self.error
        return self.result


class _ReadOnlyArchive:
    def __init__(self, loaded: dict[str, object]) -> None:
        self.loaded = loaded
        self.load_calls: list[str] = []
        self.load_error_for: str | None = None

    def save(self, result: object, metadata: object = None) -> object:
        raise AssertionError("Consistency assessment must not save")

    def load(self, run_id: str) -> object:
        self.load_calls.append(run_id)
        if run_id == self.load_error_for:
            raise RuntimeError("load failed")
        return self.loaded[run_id]

    def list_results(self, **filters: object) -> tuple[object, ...]:
        raise AssertionError("Consistency assessment must not list")

    def compare(self, baseline_run_id: str, candidate_run_id: str) -> object:
        raise AssertionError("Consistency assessment must not compare pairs")


class HistoricalConsistencyFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = representative_history()

    def test_direct_assessment_honors_falsey_injection(self) -> None:
        sentinel = object()
        analyzer = _RecordingConsistencyAnalyzer(sentinel)
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            consistency_analyzer=analyzer,  # type: ignore[arg-type]
        )
        evidence = list(self.history)

        actual = framework.assess_consistency(evidence)

        self.assertIs(actual, sentinel)
        self.assertEqual(analyzer.calls, [evidence])

    def test_archived_assessment_loads_requested_ids_then_delegates(self) -> None:
        archive = _ReadOnlyArchive(
            {item.run_id: item for item in self.history}
        )
        sentinel = object()
        analyzer = _RecordingConsistencyAnalyzer(sentinel)
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_archive=archive,  # type: ignore[arg-type]
            consistency_analyzer=analyzer,  # type: ignore[arg-type]
        )
        requested = tuple(item.run_id for item in reversed(self.history))

        actual = framework.assess_archived_consistency(requested)

        self.assertIs(actual, sentinel)
        self.assertEqual(archive.load_calls, list(requested))
        self.assertEqual(analyzer.calls, [tuple(reversed(self.history))])

    def test_missing_archive_fails_before_iterating_ids(self) -> None:
        analyzer = _RecordingConsistencyAnalyzer(object())
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            consistency_analyzer=analyzer,  # type: ignore[arg-type]
        )
        iterated = False

        def run_ids():
            nonlocal iterated
            iterated = True
            yield from (item.run_id for item in self.history)

        with self.assertRaises(ResultArchiveConfigurationError):
            framework.assess_archived_consistency(run_ids())

        self.assertFalse(iterated)
        self.assertEqual(analyzer.calls, [])

    def test_invalid_id_collections_fail_before_archive_reads(self) -> None:
        archive = _ReadOnlyArchive({})
        analyzer = _RecordingConsistencyAnalyzer(object())
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_archive=archive,  # type: ignore[arg-type]
            consistency_analyzer=analyzer,  # type: ignore[arg-type]
        )
        first, second, third = (item.run_id for item in self.history)

        invalid_calls = (
            lambda: framework.assess_archived_consistency("one-id"),
            lambda: framework.assess_archived_consistency((first, second)),
            lambda: framework.assess_archived_consistency((first, first, third)),
            lambda: framework.assess_archived_consistency(
                (first, second, 3)  # type: ignore[arg-type]
            ),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises((TypeError, IncomparableHistoryError)):
                    call()
        self.assertEqual(archive.load_calls, [])
        self.assertEqual(analyzer.calls, [])

    def test_load_and_analyzer_errors_propagate_and_stop(self) -> None:
        archive = _ReadOnlyArchive(
            {item.run_id: item for item in self.history}
        )
        ids = tuple(item.run_id for item in self.history)
        archive.load_error_for = ids[1]
        analyzer = _RecordingConsistencyAnalyzer(object())
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_archive=archive,  # type: ignore[arg-type]
            consistency_analyzer=analyzer,  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(RuntimeError, "load failed"):
            framework.assess_archived_consistency(ids)
        self.assertEqual(archive.load_calls, [ids[0], ids[1]])
        self.assertEqual(analyzer.calls, [])

        failure = RuntimeError("analysis failed")
        failing = _RecordingConsistencyAnalyzer(object(), failure)
        direct = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            consistency_analyzer=failing,  # type: ignore[arg-type]
        )
        with self.assertRaises(RuntimeError) as raised:
            direct.assess_consistency(self.history)
        self.assertIs(raised.exception, failure)

    def test_consistency_analyzer_contract_is_validated(self) -> None:
        with self.assertRaises(TypeError):
            AmmeterTestFramework(
                registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
                consistency_analyzer=object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
