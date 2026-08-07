"""Persistence, retrieval, filtering, integrity, and safety tests for Phase 5."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from src.devices.models import CurrentMeasurement
from src.testing.analysis import ResultAnalyzer
from src.testing.archive import JsonResultArchive
from src.testing.archive_codec import calculate_content_sha256
from src.testing.archive_models import RunMetadata
from src.testing.errors import (
    ArchivedResultNotFoundError,
    DuplicateRunIdError,
    InvalidRunIdError,
    ResultArchiveConfigurationError,
    ResultArchiveCorruptionError,
    ResultArchiveError,
    ResultComparisonError,
)
from src.testing.models import (
    AnalyzedSamplingResult,
    SamplingPlan,
    SamplingStopReason,
)
from src.testing.sampling import SamplingRunner

from tests.test_phase5_support import analyzed_result


FIRST_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
THIRD_ID = UUID("33333333-3333-4333-8333-333333333333")
CASE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ARCHIVED_AT = datetime(2026, 8, 6, 13, 0, tzinfo=timezone.utc)


def _stored_path(root: Path, run_id: str) -> Path:
    matches = tuple(root.rglob(f"{run_id}.json"))
    if len(matches) != 1:
        raise AssertionError(f"Expected one stored path for {run_id}: {matches}")
    return matches[0]


class JsonResultArchiveRoundTripTests(unittest.TestCase):
    def test_save_creates_one_atomic_json_record_and_load_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "nested" / "archive"
            archive = JsonResultArchive(
                root,
                id_factory=lambda: FIRST_ID,
                wall_clock=lambda: ARCHIVED_AT,
            )
            evidence = analyzed_result((1e-300, -0.0, 1e300))
            metadata = RunMetadata(
                operator="Dima",
                dut_id="DUT-α",
                station_id="ATE-01",
                notes="full evidence",
                tags=("nightly", "unicode-✓"),
                attributes=(("build", "phase5"),),
            )

            saved = archive.save(evidence, metadata)
            files = list(root.iterdir())
            stored_parent = _stored_path(root, saved.run_id).parent
            loaded = JsonResultArchive(root).load(saved.run_id)

        self.assertEqual(saved, loaded)
        self.assertEqual(saved.analyzed_result, evidence)
        self.assertEqual(saved.metadata, metadata)
        self.assertEqual(saved.run_id, str(FIRST_ID))
        self.assertEqual(saved.archived_at_utc, ARCHIVED_AT)
        self.assertEqual(
            [path.name for path in files],
            ["general"],
        )
        self.assertEqual(stored_parent, root / "general")

    def test_save_generates_unique_identifiers_and_never_overwrites_a_collision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            first = first_archive.save(analyzed_result((1.0,)))
            first_path = _stored_path(root, first.run_id)
            original_bytes = first_path.read_bytes()

            colliding_archive = JsonResultArchive(
                root,
                id_factory=lambda: FIRST_ID,
            )
            with self.assertRaises(DuplicateRunIdError):
                colliding_archive.save(analyzed_result((9.0,)))

            self.assertEqual(first_path.read_bytes(), original_bytes)
            self.assertEqual(len(list(root.rglob("*.json"))), 1)

    def test_default_factories_create_distinct_canonical_ids_and_utc_times(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(temporary_directory)

            first = archive.save(analyzed_result())
            second = archive.save(analyzed_result())

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(str(UUID(first.run_id)), first.run_id)
        self.assertEqual(str(UUID(second.run_id)), second.run_id)
        self.assertEqual(first.archived_at_utc.utcoffset(), timedelta(0))
        self.assertEqual(second.archived_at_utc.utcoffset(), timedelta(0))

    def test_concurrent_saves_have_unique_complete_reloadable_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(temporary_directory)
            evidence = analyzed_result()

            with ThreadPoolExecutor(max_workers=8) as executor:
                saved = tuple(executor.map(lambda _: archive.save(evidence), range(24)))

            run_ids = {record.run_id for record in saved}
            reloaded = tuple(archive.load(run_id) for run_id in run_ids)

        self.assertEqual(len(run_ids), 24)
        self.assertEqual({record.run_id for record in reloaded}, run_ids)
        self.assertTrue(
            all(record.analyzed_result == evidence for record in reloaded)
        )

    def test_listing_is_newest_first_and_filters_metadata_and_device(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID, THIRD_ID))
        times = iter(
            (
                ARCHIVED_AT,
                ARCHIVED_AT + timedelta(minutes=1),
                ARCHIVED_AT + timedelta(minutes=2),
            )
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: next(ids),
                wall_clock=lambda: next(times),
            )
            first = archive.save(
                analyzed_result(ammeter_name="greenlee"),
                RunMetadata(test_name="linearity", tags=("nightly",)),
            )
            second = archive.save(
                analyzed_result(ammeter_name="entes"),
                RunMetadata(test_name="linearity", tags=("release",)),
            )
            third = archive.save(
                analyzed_result(ammeter_name="greenlee"),
                RunMetadata(test_name="stability", tags=("nightly",)),
            )

            all_summaries = archive.list_results()
            greenlee = archive.list_results(ammeter_name="  GREENLEE ")
            linearity = archive.list_results(test_name="linearity")
            nightly = archive.list_results(tag="nightly")
            intersection = archive.list_results(
                ammeter_name="greenlee",
                test_name="stability",
                tag="nightly",
            )

        self.assertEqual(
            [summary.run_id for summary in all_summaries],
            [third.run_id, second.run_id, first.run_id],
        )
        self.assertEqual(
            [summary.run_id for summary in greenlee],
            [third.run_id, first.run_id],
        )
        self.assertEqual(
            [summary.run_id for summary in linearity],
            [second.run_id, first.run_id],
        )
        self.assertEqual(
            [summary.run_id for summary in nightly],
            [third.run_id, first.run_id],
        )
        self.assertEqual([summary.run_id for summary in intersection], [third.run_id])

    def test_empty_archive_and_unmatched_filters_return_immutable_empty_results(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(temporary_directory)

            self.assertEqual(archive.list_results(), ())
            archive.save(analyzed_result())
            self.assertEqual(archive.list_results(ammeter_name="entes"), ())

    def test_deadline_float_cancellation_from_runner_round_trips(self) -> None:
        started = float.fromhex("0x1.d0a176ece7236p+41")
        duration = float.fromhex("0x1.44aedf5538868p+43")
        sample_time = float.fromhex("0x1.b8d73d10724f5p+43")
        self.assertLess(sample_time, started + duration)
        self.assertEqual(sample_time - started, duration)
        clock_values = iter(
            (started, started, started, sample_time, sample_time, sample_time)
        )

        class _CancellationAmmeter:
            name = "greenlee"

            def read_current(self) -> CurrentMeasurement:
                return CurrentMeasurement(
                    ammeter_name=self.name,
                    current_a=1.0,
                    measured_at_utc=ARCHIVED_AT,
                    monotonic_time_s=sample_time,
                    latency_seconds=0.0,
                )

        runner = SamplingRunner(
            monotonic_clock=lambda: next(clock_values),
            wall_clock=lambda: ARCHIVED_AT,
            sleeper=lambda _: self.fail("the deterministic clock is ready"),
        )
        run = runner.run(
            _CancellationAmmeter(),  # type: ignore[arg-type]
            SamplingPlan(
                sampling_frequency_hz=2.0 / duration,
                measurements_count=2,
                total_duration_seconds=duration,
            ),
        )
        evidence = AnalyzedSamplingResult(
            sampling_result=run,
            statistics=ResultAnalyzer().analyze(run),
        )
        self.assertIs(run.stop_reason, SamplingStopReason.COUNT_REACHED)

        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: FIRST_ID,
            )
            saved = archive.save(evidence)
            loaded = archive.load(saved.run_id)

        self.assertEqual(loaded, saved)


class JsonResultArchiveRoutingTests(unittest.TestCase):
    def test_new_records_are_partitioned_by_assessment_group(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID, THIRD_ID, CASE_ID))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: next(ids))
            general = archive.save(analyzed_result())
            first_accuracy = archive.save(
                analyzed_result(ammeter_name="alpha"),
                RunMetadata(
                    attributes=(("comparison_group", "Bench / Room: A?"),)
                ),
            )
            second_accuracy = archive.save(
                analyzed_result(ammeter_name="bravo"),
                RunMetadata(
                    attributes=(("comparison_group", "Bench / Room: A?"),)
                ),
            )
            consistency = archive.save(
                analyzed_result(),
                RunMetadata(
                    attributes=(("consistency_group", "weekly-stability"),)
                ),
            )

            general_path = _stored_path(root, general.run_id)
            first_accuracy_path = _stored_path(root, first_accuracy.run_id)
            second_accuracy_path = _stored_path(root, second_accuracy.run_id)
            consistency_path = _stored_path(root, consistency.run_id)
            listed_ids = {item.run_id for item in archive.list_results()}

        self.assertEqual(general_path.parent.name, "general")
        self.assertEqual(first_accuracy_path.parent.parent.name, "accuracy")
        self.assertEqual(first_accuracy_path.parent, second_accuracy_path.parent)
        self.assertRegex(
            first_accuracy_path.parent.name,
            r"^group-bench-room-a-[0-9a-f]{12}$",
        )
        self.assertEqual(
            consistency_path.parent.parent.name,
            "consistency",
        )
        self.assertEqual(
            listed_ids,
            {
                general.run_id,
                first_accuracy.run_id,
                second_accuracy.run_id,
                consistency.run_id,
            },
        )

    def test_legacy_root_record_remains_loadable_and_listable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            nested_path = _stored_path(root, saved.run_id)
            legacy_path = root / nested_path.name
            nested_path.replace(legacy_path)
            nested_path.parent.rmdir()

            self.assertEqual(archive.load(saved.run_id), saved)
            self.assertEqual(
                tuple(item.run_id for item in archive.list_results()),
                (saved.run_id,),
            )

    def test_duplicate_uuid_across_legacy_and_nested_locations_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            nested_path = _stored_path(root, saved.run_id)
            (root / nested_path.name).write_bytes(nested_path.read_bytes())

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.load(saved.run_id)
            with self.assertRaises(ResultArchiveCorruptionError):
                archive.list_results()

    def test_reserved_group_metadata_must_select_one_valid_route(self) -> None:
        invalid_attributes = (
            (("comparison_group", 42),),
            (("consistency_group", " bad "),),
            (
                ("comparison_group", "accuracy-a"),
                ("consistency_group", "history-a"),
            ),
        )
        for attributes in invalid_attributes:
            with self.subTest(attributes=attributes):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
                    with self.assertRaises(ResultArchiveError):
                        archive.save(
                            analyzed_result(),
                            RunMetadata(attributes=attributes),
                        )
                    self.assertEqual(list(root.iterdir()), [])

    def test_nested_record_location_must_match_its_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(
                analyzed_result(),
                RunMetadata(
                    attributes=(("comparison_group", "correct-group"),)
                ),
            )
            original = _stored_path(root, saved.run_id)
            wrong_group = root / "accuracy" / "group-wrong-000000000000"
            wrong_group.mkdir()
            original.replace(wrong_group / original.name)
            original.parent.rmdir()

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.load(saved.run_id)

    def test_uuid_collision_is_detected_across_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            JsonResultArchive(root, id_factory=lambda: FIRST_ID).save(
                analyzed_result(),
                RunMetadata(
                    attributes=(("comparison_group", "accuracy-a"),)
                ),
            )
            consistency_archive = JsonResultArchive(
                root,
                id_factory=lambda: FIRST_ID,
            )
            with self.assertRaises(DuplicateRunIdError):
                consistency_archive.save(
                    analyzed_result(),
                    RunMetadata(
                        attributes=(("consistency_group", "history-a"),)
                    ),
                )


class JsonResultArchiveErrorTests(unittest.TestCase):
    def test_missing_and_invalid_run_identifiers_have_distinct_typed_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(temporary_directory)
            with self.assertRaises(ArchivedResultNotFoundError):
                archive.load(str(FIRST_ID))

            invalid_ids = (
                "",
                "not-a-uuid",
                "../outside",
                "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
                f" {FIRST_ID} ",
                f"{FIRST_ID}.json",
            )
            for invalid_id in invalid_ids:
                with self.subTest(run_id=invalid_id):
                    with self.assertRaises(InvalidRunIdError):
                        archive.load(invalid_id)

    def test_malformed_nonfinite_and_unsupported_documents_are_corrupt(self) -> None:
        malformed_documents = (
            "{",
            "[]",
            '{"value": NaN}',
            '{"schema_version": 999}',
        )
        for index, document in enumerate(malformed_documents, start=1):
            with self.subTest(document=document):
                run_id = UUID(f"00000000-0000-4000-8000-{index:012d}")
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    (root / f"{run_id}.json").write_text(
                        document,
                        encoding="utf-8",
                    )
                    archive = JsonResultArchive(root)

                    with self.assertRaises(ResultArchiveCorruptionError):
                        archive.load(str(run_id))

    def test_json_parser_limits_are_wrapped_as_typed_corruption(self) -> None:
        documents = (
            '{"schema_version": ' + ("9" * 5_000) + "}",
            ("[" * 2_000) + "0" + ("]" * 2_000),
        )
        for index, document in enumerate(documents, start=1):
            with self.subTest(index=index):
                run_id = UUID(f"90000000-0000-4000-8000-{index:012d}")
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    (root / f"{run_id}.json").write_text(
                        document,
                        encoding="utf-8",
                    )

                    with self.assertRaises(ResultArchiveCorruptionError):
                        JsonResultArchive(root).load(str(run_id))

    def test_tampering_with_payload_or_checksum_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            path = _stored_path(root, saved.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))

            payload["analyzed_result"]["statistics"]["mean_current_a"] = 999.0
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.load(saved.run_id)

    def test_semantic_tampering_is_detected_even_with_a_recomputed_checksum(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            path = _stored_path(root, saved.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["analyzed_result"]["statistics"]["mean_current_a"] = 2.5
            content = {
                key: value for key, value in payload.items() if key != "integrity"
            }
            payload["integrity"]["content_sha256"] = (
                calculate_content_sha256(content)
            )
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.load(saved.run_id)

    def test_rehashed_sampling_grid_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            path = _stored_path(root, saved.run_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            sample = payload["analyzed_result"]["sampling_result"]["samples"][1]
            sample["scheduled_offset_seconds"] = 99.0
            sample["start_lateness_seconds"] = 0.0
            content = {
                key: value for key, value in payload.items() if key != "integrity"
            }
            payload["integrity"]["content_sha256"] = (
                calculate_content_sha256(content)
            )
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.load(saved.run_id)

    def test_units_and_derived_fields_are_strict_after_checksum_verification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            path = _stored_path(root, saved.run_id)
            original = json.loads(path.read_text(encoding="utf-8"))

            def wrong_measurement_unit(payload: dict[str, object]) -> None:
                payload["analyzed_result"]["sampling_result"]["samples"][0][  # type: ignore[index]
                    "measurement"
                ]["unit"] = "mA"

            def wrong_statistics_unit(payload: dict[str, object]) -> None:
                payload["analyzed_result"]["statistics"]["unit"] = "mA"  # type: ignore[index]

            def wrong_sample_count(payload: dict[str, object]) -> None:
                payload["analyzed_result"]["sampling_result"]["sample_count"] = 99  # type: ignore[index]

            def wrong_elapsed(payload: dict[str, object]) -> None:
                payload["analyzed_result"]["sampling_result"]["elapsed_seconds"] = 99.0  # type: ignore[index]

            def wrong_lateness(payload: dict[str, object]) -> None:
                payload["analyzed_result"]["sampling_result"]["samples"][0][  # type: ignore[index]
                    "start_lateness_seconds"
                ] = 99.0

            def boolean_zero_lateness(payload: dict[str, object]) -> None:
                payload["analyzed_result"]["sampling_result"]["samples"][0][  # type: ignore[index]
                    "start_lateness_seconds"
                ] = False

            corruptions = (
                wrong_measurement_unit,
                wrong_statistics_unit,
                wrong_sample_count,
                wrong_elapsed,
                wrong_lateness,
                boolean_zero_lateness,
            )
            for corrupt in corruptions:
                with self.subTest(corruption=corrupt.__name__):
                    payload = copy.deepcopy(original)
                    corrupt(payload)
                    content = {
                        key: value
                        for key, value in payload.items()
                        if key != "integrity"
                    }
                    payload["integrity"]["content_sha256"] = (  # type: ignore[index]
                        calculate_content_sha256(content)
                    )
                    path.write_text(json.dumps(payload), encoding="utf-8")

                    with self.assertRaises(ResultArchiveCorruptionError):
                        archive.load(saved.run_id)

    def test_duplicate_json_keys_are_rejected_before_schema_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / f"{FIRST_ID}.json"
            path.write_text(
                '{"schema_version": 1, "schema_version": 1}',
                encoding="utf-8",
            )

            with self.assertRaises(ResultArchiveCorruptionError):
                JsonResultArchive(root).load(str(FIRST_ID))

    def test_filename_and_payload_run_id_mismatch_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            saved = archive.save(analyzed_result())
            original_path = _stored_path(root, saved.run_id)
            mismatched_path = root / f"{SECOND_ID}.json"
            mismatched_path.write_bytes(original_path.read_bytes())

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.load(str(SECOND_ID))

    def test_listing_surfaces_corrupt_canonical_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / f"{FIRST_ID}.json").write_text("not json", encoding="utf-8")

            with self.assertRaises(ResultArchiveCorruptionError):
                JsonResultArchive(root).list_results()

    def test_listing_rejects_noncanonical_uuid_filename_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: CASE_ID)
            saved = archive.save(analyzed_result())
            canonical = _stored_path(root, saved.run_id)
            intermediate = canonical.parent / "case-change.tmp"
            noncanonical = canonical.parent / f"{saved.run_id.upper()}.json"
            canonical.rename(intermediate)
            intermediate.rename(noncanonical)

            with self.assertRaises(ResultArchiveCorruptionError):
                archive.list_results()

    def test_unrelated_and_temporary_files_do_not_become_archive_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "notes.json").write_text("not an archive", encoding="utf-8")
            (root / "partial.tmp").write_text("partial", encoding="utf-8")

            self.assertEqual(JsonResultArchive(root).list_results(), ())

    def test_archive_root_must_be_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root_file = Path(temporary_directory) / "archive"
            root_file.write_text("occupied", encoding="utf-8")

            with self.assertRaises(ResultArchiveConfigurationError):
                JsonResultArchive(root_file)

    def test_invalid_injected_id_and_clock_fail_without_leaving_reservations(
        self,
    ) -> None:
        invalid_factories = (
            (lambda: "../outside", lambda: ARCHIVED_AT),
            (lambda: FIRST_ID, lambda: "not a datetime"),
            (lambda: FIRST_ID, lambda: ARCHIVED_AT.replace(tzinfo=None)),
        )
        for id_factory, wall_clock in invalid_factories:
            with self.subTest(id_factory=id_factory, wall_clock=wall_clock):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    archive = JsonResultArchive(
                        root,
                        id_factory=id_factory,
                        wall_clock=wall_clock,  # type: ignore[arg-type]
                    )

                    with self.assertRaises(ResultArchiveConfigurationError):
                        archive.save(analyzed_result())

                    self.assertEqual(list(root.iterdir()), [])

    def test_save_rejects_statistics_that_do_not_match_raw_evidence(self) -> None:
        evidence = analyzed_result()
        inconsistent = replace(
            evidence,
            statistics=replace(evidence.statistics, mean_current_a=2.5),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(temporary_directory)

            with self.assertRaises(ResultArchiveError):
                archive.save(inconsistent)

            self.assertEqual(list(Path(temporary_directory).iterdir()), [])

    def test_save_rejects_evidence_it_could_not_reload(self) -> None:
        evidence = analyzed_result()
        invalid_sample = replace(
            evidence.sampling_result.samples[1],
            scheduled_offset_seconds=0.05,
        )
        invalid_run = replace(
            evidence.sampling_result,
            samples=(
                evidence.sampling_result.samples[0],
                invalid_sample,
                evidence.sampling_result.samples[2],
            ),
        )
        invalid_evidence = replace(evidence, sampling_result=invalid_run)
        signed_zero_statistics = replace(
            analyzed_result((0.0,)).statistics,
            mean_current_a=-0.0,
        )
        signed_zero_evidence = replace(
            analyzed_result((0.0,)),
            statistics=signed_zero_statistics,
        )

        for invalid_result in (invalid_evidence, signed_zero_evidence):
            with self.subTest(result=invalid_result):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    with self.assertRaises(ResultArchiveError):
                        JsonResultArchive(root).save(invalid_result)
                    self.assertEqual(list(root.iterdir()), [])

    def test_archive_file_symlink_is_rejected_where_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "source"
            destination_root = root / "destination"
            source = JsonResultArchive(source_root, id_factory=lambda: FIRST_ID)
            saved = source.save(analyzed_result())
            destination_root.mkdir()
            link = destination_root / f"{saved.run_id}.json"
            try:
                link.symlink_to(_stored_path(source_root, saved.run_id))
            except OSError as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            with self.assertRaises(ResultArchiveCorruptionError):
                JsonResultArchive(destination_root).load(saved.run_id)

    def test_commit_failure_leaves_no_final_or_temporary_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            failure = OSError("link failed")

            with patch("os.link", side_effect=failure):
                with self.assertRaises(ResultArchiveError) as raised:
                    archive.save(analyzed_result())

            self.assertIs(raised.exception.__cause__, failure)
            self.assertEqual(list(root.iterdir()), [])

    def test_post_commit_cleanup_failure_does_not_report_a_failed_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            original_unlink = Path.unlink
            failed_once = False

            def fail_first_temporary_unlink(
                path: Path,
                *args: object,
                **kwargs: object,
            ) -> None:
                nonlocal failed_once
                if path.suffix == ".tmp" and not failed_once:
                    failed_once = True
                    raise OSError("cleanup failed once")
                original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", new=fail_first_temporary_unlink):
                saved = archive.save(analyzed_result())

            self.assertEqual(archive.load(saved.run_id), saved)
            self.assertEqual(
                [path.name for path in root.iterdir()],
                ["general"],
            )
            self.assertEqual(
                _stored_path(root, saved.run_id).parent,
                root / "general",
            )

    def test_reservation_close_failure_is_typed_and_cleans_the_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = JsonResultArchive(root, id_factory=lambda: FIRST_ID)
            original_close = os.close
            failed_once = False

            def close_then_fail_once(file_descriptor: int) -> None:
                nonlocal failed_once
                original_close(file_descriptor)
                if not failed_once:
                    failed_once = True
                    raise OSError("close reported failure")

            with patch("os.close", side_effect=close_then_fail_once):
                with self.assertRaises(ResultArchiveError):
                    archive.save(analyzed_result())

            self.assertEqual(list(root.iterdir()), [])


class JsonResultArchiveComparisonTests(unittest.TestCase):
    def test_comparison_uses_candidate_minus_baseline_and_reverses_sign(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID))
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: next(ids),
            )
            baseline = archive.save(analyzed_result((1.0, 2.0, 3.0)))
            candidate = archive.save(analyzed_result((2.0, 4.0, 6.0)))

            forward = archive.compare(baseline.run_id, candidate.run_id)
            reverse = archive.compare(candidate.run_id, baseline.run_id)

        self.assertEqual(forward.mean_current_delta_a, 2.0)
        self.assertEqual(reverse.mean_current_delta_a, -2.0)
        self.assertEqual(
            forward.standard_deviation_current_delta_a,
            -reverse.standard_deviation_current_delta_a,
        )

    def test_different_sampling_plans_are_reported_without_hiding_deltas(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID))
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: next(ids),
            )
            baseline = archive.save(analyzed_result((1.0, 2.0)))
            candidate = archive.save(analyzed_result((1.0, 2.0, 3.0)))

            comparison = archive.compare(baseline.run_id, candidate.run_id)

        self.assertFalse(comparison.sampling_plans_match)
        self.assertEqual(comparison.sample_count_delta, 1)

    def test_cross_ammeter_comparison_is_rejected_for_phase5(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID))
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: next(ids),
            )
            greenlee = archive.save(analyzed_result(ammeter_name="greenlee"))
            entes = archive.save(analyzed_result(ammeter_name="entes"))

            with self.assertRaises(ResultComparisonError):
                archive.compare(greenlee.run_id, entes.run_id)

    def test_different_test_definitions_cannot_be_compared(self) -> None:
        ids = iter((FIRST_ID, SECOND_ID))
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: next(ids),
            )
            baseline = archive.save(
                analyzed_result(),
                RunMetadata(test_name="linearity"),
            )
            candidate = archive.save(
                analyzed_result(),
                RunMetadata(test_name="stability"),
            )

            with self.assertRaises(ResultComparisonError):
                archive.compare(baseline.run_id, candidate.run_id)

    def test_nonfinite_delta_is_rejected_instead_of_entering_reports(self) -> None:
        maximum = float.fromhex("0x1.fffffffffffffp+1023")
        ids = iter((FIRST_ID, SECOND_ID))
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = JsonResultArchive(
                temporary_directory,
                id_factory=lambda: next(ids),
            )
            baseline = archive.save(analyzed_result((-maximum,)))
            candidate = archive.save(analyzed_result((maximum,)))

            with self.assertRaises(ResultComparisonError):
                archive.compare(baseline.run_id, candidate.run_id)


if __name__ == "__main__":
    unittest.main()
