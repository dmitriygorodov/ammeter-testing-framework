"""Framework delegation and fail-fast contracts for Phase 6."""

from __future__ import annotations

import unittest

from src.testing.accuracy_models import ReferenceCurrent
from src.testing.errors import (
    IncomparableAmmeterEvidenceError,
    ResultArchiveConfigurationError,
)
from src.testing.test_framework import AmmeterTestFramework

from tests.test_phase6_support import representative_cohort


class _NoDeviceRegistry:
    """A registry that makes any accidental hardware lookup immediately fail."""

    names: tuple[str, ...] = ()

    def get(self, name: str) -> object:
        raise AssertionError(f"Phase 6 must not access a device: {name}")


class _RecordingAssessor:
    def __init__(self, result: object, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, ReferenceCurrent]] = []

    def __bool__(self) -> bool:
        return False

    def assess(self, results: object, *, reference: ReferenceCurrent) -> object:
        self.calls.append((results, reference))
        if self.error is not None:
            raise self.error
        return self.result


class _RecordingArchive:
    def __init__(self, loaded: dict[str, object]) -> None:
        self.loaded = loaded
        self.load_calls: list[str] = []
        self.load_error_for: str | None = None

    def save(self, result: object, metadata: object = None) -> object:
        raise AssertionError("Accuracy assessment must not save evidence")

    def load(self, run_id: str) -> object:
        self.load_calls.append(run_id)
        if run_id == self.load_error_for:
            raise RuntimeError("load failed")
        return self.loaded[run_id]

    def list_results(self, **filters: object) -> tuple[object, ...]:
        raise AssertionError("Accuracy assessment must not list the archive")

    def compare(self, baseline_run_id: str, candidate_run_id: str) -> object:
        raise AssertionError("Accuracy assessment must not use Phase 5 compare")


class AccuracyFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = ReferenceCurrent(current_a=10.0, source="setpoint")
        self.cohort = representative_cohort()[:2]

    def test_assess_accuracy_delegates_evidence_without_archive_or_device(self) -> None:
        sentinel = object()
        assessor = _RecordingAssessor(sentinel)
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            accuracy_assessor=assessor,  # type: ignore[arg-type]
        )
        evidence = list(self.cohort)

        actual = framework.assess_accuracy(
            evidence,
            reference=self.reference,
        )

        self.assertIs(actual, sentinel)
        self.assertEqual(assessor.calls, [(evidence, self.reference)])

    def test_assess_archived_accuracy_loads_in_requested_order_then_delegates(self) -> None:
        first_id, second_id = (item.run_id for item in self.cohort)
        archive = _RecordingArchive(
            {
                first_id: self.cohort[0],
                second_id: self.cohort[1],
            }
        )
        sentinel = object()
        assessor = _RecordingAssessor(sentinel)
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_archive=archive,  # type: ignore[arg-type]
            accuracy_assessor=assessor,  # type: ignore[arg-type]
        )

        actual = framework.assess_archived_accuracy(
            (second_id, first_id),
            reference=self.reference,
        )

        self.assertIs(actual, sentinel)
        self.assertEqual(archive.load_calls, [second_id, first_id])
        loaded_results, delegated_reference = assessor.calls[0]
        self.assertEqual(loaded_results, (self.cohort[1], self.cohort[0]))
        self.assertIs(delegated_reference, self.reference)

    def test_missing_archive_fails_before_iterating_ids_or_assessing(self) -> None:
        assessor = _RecordingAssessor(object())
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            accuracy_assessor=assessor,  # type: ignore[arg-type]
        )
        iterated = False

        def run_ids() -> object:
            nonlocal iterated
            iterated = True
            yield self.cohort[0].run_id
            yield self.cohort[1].run_id

        with self.assertRaises(ResultArchiveConfigurationError):
            framework.assess_archived_accuracy(
                run_ids(),  # type: ignore[arg-type]
                reference=self.reference,
            )

        self.assertFalse(iterated)
        self.assertEqual(assessor.calls, [])

    def test_invalid_reference_and_id_collections_fail_before_archive_reads(self) -> None:
        archive = _RecordingArchive({})
        assessor = _RecordingAssessor(object())
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_archive=archive,  # type: ignore[arg-type]
            accuracy_assessor=assessor,  # type: ignore[arg-type]
        )

        with self.assertRaises(TypeError):
            framework.assess_archived_accuracy(
                ("one", "two"),
                reference=10.0,  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            framework.assess_archived_accuracy(
                "one-id",  # type: ignore[arg-type]
                reference=self.reference,
            )
        with self.assertRaises(IncomparableAmmeterEvidenceError):
            framework.assess_archived_accuracy(
                ("only-one",),
                reference=self.reference,
            )

        self.assertEqual(archive.load_calls, [])
        self.assertEqual(assessor.calls, [])

    def test_load_and_assessor_errors_propagate_and_stop_the_pipeline(self) -> None:
        first_id, second_id = (item.run_id for item in self.cohort)
        archive = _RecordingArchive(
            {
                first_id: self.cohort[0],
                second_id: self.cohort[1],
            }
        )
        assessor = _RecordingAssessor(object())
        archive.load_error_for = second_id
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_archive=archive,  # type: ignore[arg-type]
            accuracy_assessor=assessor,  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(RuntimeError, "load failed"):
            framework.assess_archived_accuracy(
                (first_id, second_id),
                reference=self.reference,
            )
        self.assertEqual(archive.load_calls, [first_id, second_id])
        self.assertEqual(assessor.calls, [])

        expected_error = RuntimeError("assessment failed")
        failing_assessor = _RecordingAssessor(object(), expected_error)
        direct_framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            accuracy_assessor=failing_assessor,  # type: ignore[arg-type]
        )
        with self.assertRaises(RuntimeError) as raised:
            direct_framework.assess_accuracy(
                self.cohort,
                reference=self.reference,
            )
        self.assertIs(raised.exception, expected_error)

    def test_accuracy_assessor_injection_requires_assess_protocol(self) -> None:
        with self.assertRaises(TypeError):
            AmmeterTestFramework(
                registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
                accuracy_assessor=object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
