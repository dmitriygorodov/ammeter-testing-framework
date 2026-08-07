"""Atomic JSON repository for analyzed ammeter test results."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .archive_codec import (
    calculate_content_sha256,
    decode_archive_document,
    validate_analyzed_result_semantics,
)
from .archive_models import (
    ArchivedResultSummary,
    ArchivedTestResult,
    HistoricalResultComparison,
    RunMetadata,
    RunStatus,
    require_canonical_run_id,
)
from .errors import (
    ArchivedResultNotFoundError,
    DuplicateRunIdError,
    InvalidRunIdError,
    ResultArchiveConfigurationError,
    ResultArchiveCorruptionError,
    ResultArchiveError,
    ResultComparisonError,
)
from .models import AnalyzedSamplingResult


MAX_RUN_ID_ATTEMPTS = 10
_ACCURACY_DIRECTORY = "accuracy"
_CONSISTENCY_DIRECTORY = "consistency"
_GENERAL_DIRECTORY = "general"
_COMPARISON_GROUP_ATTRIBUTE = "comparison_group"
_CONSISTENCY_GROUP_ATTRIBUTE = "consistency_group"


class JsonResultArchive:
    """Persist, retrieve, browse, and compare complete analyzed test runs."""

    def __init__(
        self,
        archive_directory: str | Path,
        *,
        id_factory: Callable[[], UUID | str] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(archive_directory, (str, Path)):
            raise TypeError("archive_directory must be a path")
        if isinstance(archive_directory, str) and not archive_directory.strip():
            raise ResultArchiveConfigurationError(
                "archive_directory must not be blank"
            )
        if (
            isinstance(archive_directory, str)
            and archive_directory != archive_directory.strip()
        ):
            raise ResultArchiveConfigurationError(
                "archive_directory must not have surrounding whitespace"
            )
        try:
            self._archive_directory = (
                Path(archive_directory).expanduser().resolve()
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ResultArchiveConfigurationError(
                f"Invalid archive directory: {archive_directory!r}"
            ) from exc
        if (
            self._archive_directory.exists()
            and not self._archive_directory.is_dir()
        ):
            raise ResultArchiveConfigurationError(
                f"Archive path is not a directory: {self._archive_directory}"
            )

        self._id_factory = id_factory if id_factory is not None else uuid4
        self._wall_clock = (
            wall_clock
            if wall_clock is not None
            else lambda: datetime.now(timezone.utc)
        )
        if not callable(self._id_factory):
            raise TypeError("id_factory must be callable")
        if not callable(self._wall_clock):
            raise TypeError("wall_clock must be callable")

    @property
    def archive_directory(self) -> Path:
        return self._archive_directory

    def save(
        self,
        result: AnalyzedSamplingResult,
        metadata: RunMetadata | None = None,
    ) -> ArchivedTestResult:
        """Atomically persist one successful analyzed result."""

        if not isinstance(result, AnalyzedSamplingResult):
            raise TypeError("result must be an AnalyzedSamplingResult")
        effective_metadata = metadata if metadata is not None else RunMetadata()
        if not isinstance(effective_metadata, RunMetadata):
            raise TypeError("metadata must be RunMetadata")
        self._validate_analysis(result)
        target_directory = self._archive_directory_for_metadata(
            effective_metadata
        )
        self._ensure_archive_directory()

        run_id, final_path, reservation_path = self._reserve_run_id(
            target_directory
        )
        temporary_path: Path | None = None
        created_directories: tuple[Path, ...] = ()
        committed = False
        try:
            archived_at = self._read_wall_clock()
            content = {
                "schema_version": ArchivedTestResult.schema_version,
                "run_id": run_id,
                "status": RunStatus.COMPLETED.value,
                "archived_at_utc": _datetime_to_json(archived_at),
                "metadata": effective_metadata.to_dict(),
                "analyzed_result": result.to_dict(),
            }
            archived = ArchivedTestResult(
                run_id=run_id,
                archived_at_utc=archived_at,
                metadata=effective_metadata,
                analyzed_result=result,
                content_sha256=calculate_content_sha256(content),
                status=RunStatus.COMPLETED,
            )
            if archived.content_dict() != content:
                raise ResultArchiveError(
                    "Archive content did not normalize deterministically"
                )

            created_directories = self._ensure_archive_subdirectory(
                target_directory
            )
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{run_id}.",
                suffix=".tmp",
                dir=target_directory,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(
                    file_descriptor,
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as archive_file:
                    json.dump(
                        archived.to_dict(),
                        archive_file,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        indent=2,
                    )
                    archive_file.write("\n")
                    archive_file.flush()
                    os.fsync(archive_file.fileno())
            except BaseException:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass
                raise

            try:
                os.link(temporary_path, final_path)
            except FileExistsError as exc:
                raise DuplicateRunIdError(
                    f"Run ID already exists and will not be overwritten: {run_id}"
                ) from exc
            committed = True
            # The hard link is the atomic commit point. Cleanup of the hidden
            # staging name is best effort and must not turn a committed save
            # into a reported failure.
            try:
                temporary_path.unlink()
            except OSError:
                pass
            else:
                temporary_path = None
            return archived
        except ResultArchiveError:
            raise
        except (OSError, OverflowError, TypeError, ValueError) as exc:
            raise ResultArchiveError(
                f"Could not persist result {run_id} in "
                f"{self._archive_directory}: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                reservation_path.unlink(missing_ok=True)
            except OSError:
                pass
            if not committed:
                for directory in reversed(created_directories):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    def load(self, run_id: str) -> ArchivedTestResult:
        """Load one run by canonical UUID and validate all stored evidence."""

        canonical_run_id = _validate_requested_run_id(run_id)
        matches = self._matching_archive_paths(canonical_run_id)
        if not matches:
            raise ArchivedResultNotFoundError(
                f"Archived result not found: {canonical_run_id}"
            )
        if len(matches) != 1:
            raise ResultArchiveCorruptionError(
                f"Run ID exists at multiple archive locations: "
                f"{canonical_run_id}"
            )
        archive_path = matches[0]
        self._validate_archive_file_location(archive_path)

        try:
            with archive_path.open("r", encoding="utf-8") as archive_file:
                document = json.load(
                    archive_file,
                    object_pairs_hook=_object_without_duplicate_keys,
                    parse_constant=_reject_nonstandard_constant,
                )
        except ArchivedResultNotFoundError:
            raise
        except ResultArchiveCorruptionError:
            raise
        except FileNotFoundError as exc:
            raise ArchivedResultNotFoundError(
                f"Archived result not found: {canonical_run_id}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ResultArchiveCorruptionError(
                f"Archive JSON is malformed: {archive_path}"
            ) from exc
        except (ValueError, OverflowError, RecursionError) as exc:
            raise ResultArchiveCorruptionError(
                f"Archive JSON contains an invalid value: {archive_path}"
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise ResultArchiveError(
                f"Could not read archived result {canonical_run_id}: {exc}"
            ) from exc

        archived = decode_archive_document(
            document,
            expected_run_id=canonical_run_id,
        )
        self._validate_archive_routing(archive_path, archived.metadata)
        return archived

    def list_results(
        self,
        *,
        ammeter_name: str | None = None,
        test_name: str | None = None,
        tag: str | None = None,
    ) -> tuple[ArchivedResultSummary, ...]:
        """Return newest-first summaries, optionally filtered by metadata."""

        normalized_ammeter = _optional_filter(ammeter_name, "ammeter_name")
        normalized_test = _optional_filter(test_name, "test_name")
        normalized_tag = _optional_filter(tag, "tag")
        if not self._archive_directory.exists():
            return ()
        if not self._archive_directory.is_dir():
            raise ResultArchiveConfigurationError(
                f"Archive path is not a directory: {self._archive_directory}"
            )

        summaries: list[ArchivedResultSummary] = []
        candidates = self._archive_candidate_files()
        for candidate in candidates:
            try:
                run_id = require_canonical_run_id(candidate.stem)
            except ValueError:
                try:
                    UUID(candidate.stem)
                except (AttributeError, TypeError, ValueError):
                    continue
                raise ResultArchiveCorruptionError(
                    "UUID-shaped archive filenames must use canonical "
                    "lowercase spelling"
                )
            archived = self.load(run_id)
            summary = archived.to_summary()
            if (
                normalized_ammeter is not None
                and summary.ammeter_name.casefold() != normalized_ammeter
            ):
                continue
            if (
                normalized_test is not None
                and summary.metadata.test_name.casefold() != normalized_test
            ):
                continue
            if normalized_tag is not None and all(
                stored_tag.casefold() != normalized_tag
                for stored_tag in summary.metadata.tags
            ):
                continue
            summaries.append(summary)
        summaries.sort(
            key=lambda summary: (summary.archived_at_utc, summary.run_id),
            reverse=True,
        )
        return tuple(summaries)

    def compare(
        self,
        baseline_run_id: str,
        candidate_run_id: str,
    ) -> HistoricalResultComparison:
        """Compare two historical runs from the same ammeter."""

        baseline = self.load(baseline_run_id)
        candidate = self.load(candidate_run_id)
        if baseline.ammeter_name != candidate.ammeter_name:
            raise ResultComparisonError(
                "Phase 5 compares historical runs from the same ammeter; "
                "cross-ammeter accuracy assessment is a separate bonus"
            )
        if baseline.metadata.test_name != candidate.metadata.test_name:
            raise ResultComparisonError(
                "Historical comparisons require the same metadata test_name"
            )

        baseline_statistics = baseline.analyzed_result.statistics
        candidate_statistics = candidate.analyzed_result.statistics
        return HistoricalResultComparison(
            baseline_run_id=baseline.run_id,
            candidate_run_id=candidate.run_id,
            baseline_archived_at_utc=baseline.archived_at_utc,
            candidate_archived_at_utc=candidate.archived_at_utc,
            ammeter_name=baseline.ammeter_name,
            test_name=baseline.metadata.test_name,
            baseline_statistics=baseline_statistics,
            candidate_statistics=candidate_statistics,
            sample_count_delta=(
                candidate_statistics.sample_count
                - baseline_statistics.sample_count
            ),
            mean_current_delta_a=_finite_delta(
                candidate_statistics.mean_current_a,
                baseline_statistics.mean_current_a,
                "mean current",
            ),
            median_current_delta_a=_finite_delta(
                candidate_statistics.median_current_a,
                baseline_statistics.median_current_a,
                "median current",
            ),
            standard_deviation_current_delta_a=_finite_delta(
                candidate_statistics.standard_deviation_current_a,
                baseline_statistics.standard_deviation_current_a,
                "standard deviation",
            ),
            minimum_current_delta_a=_finite_delta(
                candidate_statistics.minimum_current_a,
                baseline_statistics.minimum_current_a,
                "minimum current",
            ),
            maximum_current_delta_a=_finite_delta(
                candidate_statistics.maximum_current_a,
                baseline_statistics.maximum_current_a,
                "maximum current",
            ),
            sampling_plans_match=(
                baseline.analyzed_result.sampling_result.plan
                == candidate.analyzed_result.sampling_result.plan
            ),
        )

    # Small vocabulary aliases for callers that prefer repository terminology.
    def archive(
        self,
        result: AnalyzedSamplingResult,
        metadata: RunMetadata | None = None,
    ) -> ArchivedTestResult:
        return self.save(result, metadata)

    def get(self, run_id: str) -> ArchivedTestResult:
        return self.load(run_id)

    def _validate_analysis(self, result: AnalyzedSamplingResult) -> None:
        try:
            validate_analyzed_result_semantics(result)
        except ResultArchiveCorruptionError as exc:
            raise ResultArchiveError(
                "Analyzed result contains inconsistent sampling evidence"
            ) from exc

    def _ensure_archive_directory(self) -> None:
        try:
            self._archive_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ResultArchiveConfigurationError(
                f"Could not create archive directory "
                f"{self._archive_directory}: {exc}"
            ) from exc
        if not self._archive_directory.is_dir():
            raise ResultArchiveConfigurationError(
                f"Archive path is not a directory: {self._archive_directory}"
            )

    def _reserve_run_id(
        self,
        target_directory: Path,
    ) -> tuple[str, Path, Path]:
        for _ in range(MAX_RUN_ID_ATTEMPTS):
            try:
                generated = self._id_factory()
            except Exception as exc:
                raise ResultArchiveConfigurationError(
                    "id_factory failed while generating a run ID"
                ) from exc
            run_id = str(generated) if isinstance(generated, UUID) else generated
            try:
                run_id = require_canonical_run_id(run_id)
            except ValueError as exc:
                raise ResultArchiveConfigurationError(
                    "id_factory must return a canonical UUID or UUID string"
                ) from exc
            final_path = target_directory / f"{run_id}.json"
            if self._matching_archive_paths(run_id):
                continue
            reservation_path = self._archive_directory / f".{run_id}.lock"
            try:
                reservation_descriptor = os.open(
                    reservation_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                continue
            except OSError as exc:
                raise ResultArchiveError(
                    f"Could not reserve run ID {run_id}: {exc}"
                ) from exc
            else:
                try:
                    os.close(reservation_descriptor)
                except OSError as exc:
                    try:
                        reservation_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise ResultArchiveError(
                        f"Could not finalize run ID reservation {run_id}: {exc}"
                    ) from exc
            if self._matching_archive_paths(run_id):
                try:
                    reservation_path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            return run_id, final_path, reservation_path
        raise DuplicateRunIdError(
            f"Could not generate a unique run ID after "
            f"{MAX_RUN_ID_ATTEMPTS} attempts"
        )

    def _read_wall_clock(self) -> datetime:
        try:
            value = self._wall_clock()
        except Exception as exc:
            raise ResultArchiveConfigurationError(
                "wall_clock failed while creating archive metadata"
            ) from exc
        if not isinstance(value, datetime):
            raise ResultArchiveConfigurationError(
                "wall_clock must return a datetime"
            )
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ResultArchiveConfigurationError(
                "wall_clock must return a timezone-aware UTC datetime"
            )
        return value

    def _archive_directory_for_metadata(self, metadata: RunMetadata) -> Path:
        attributes = {
            key.casefold(): value for key, value in metadata.attributes
        }
        comparison_group = _archive_group_value(
            attributes.get(_COMPARISON_GROUP_ATTRIBUTE),
            _COMPARISON_GROUP_ATTRIBUTE,
            present=_COMPARISON_GROUP_ATTRIBUTE in attributes,
        )
        consistency_group = _archive_group_value(
            attributes.get(_CONSISTENCY_GROUP_ATTRIBUTE),
            _CONSISTENCY_GROUP_ATTRIBUTE,
            present=_CONSISTENCY_GROUP_ATTRIBUTE in attributes,
        )
        if comparison_group is not None and consistency_group is not None:
            raise ResultArchiveError(
                "Archive metadata cannot contain both comparison_group and "
                "consistency_group"
            )
        if comparison_group is not None:
            return (
                self._archive_directory
                / _ACCURACY_DIRECTORY
                / _safe_group_directory_name(comparison_group)
            )
        if consistency_group is not None:
            return (
                self._archive_directory
                / _CONSISTENCY_DIRECTORY
                / _safe_group_directory_name(consistency_group)
            )
        return self._archive_directory / _GENERAL_DIRECTORY

    def _ensure_archive_subdirectory(
        self,
        target_directory: Path,
    ) -> tuple[Path, ...]:
        try:
            relative = target_directory.relative_to(self._archive_directory)
        except ValueError as exc:
            raise ResultArchiveConfigurationError(
                "Archive target directory escapes the configured root"
            ) from exc

        created: list[Path] = []
        current = self._archive_directory
        try:
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise ResultArchiveConfigurationError(
                        f"Archive directories must not be symbolic links: {current}"
                    )
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
                else:
                    created.append(current)
                if not current.is_dir():
                    raise ResultArchiveConfigurationError(
                        f"Archive path is not a directory: {current}"
                    )
        except ResultArchiveConfigurationError:
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
        except OSError as exc:
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise ResultArchiveConfigurationError(
                f"Could not create archive directory {target_directory}: {exc}"
            ) from exc
        return tuple(created)

    def _matching_archive_paths(self, run_id: str) -> tuple[Path, ...]:
        expected_name = f"{run_id}.json".casefold()
        return tuple(
            candidate
            for candidate in self._archive_candidate_files()
            if candidate.name.casefold() == expected_name
        )

    def _archive_candidate_files(self) -> tuple[Path, ...]:
        if not self._archive_directory.exists():
            return ()
        try:
            candidates = [
                entry
                for entry in self._archive_directory.iterdir()
                if entry.suffix.casefold() == ".json"
            ]
            general = self._archive_directory / _GENERAL_DIRECTORY
            if general.is_symlink():
                raise ResultArchiveCorruptionError(
                    f"Archive directories must not be symbolic links: {general}"
                )
            if general.exists():
                if not general.is_dir():
                    raise ResultArchiveCorruptionError(
                        f"Archive path is not a directory: {general}"
                    )
                candidates.extend(
                    entry
                    for entry in general.iterdir()
                    if entry.suffix.casefold() == ".json"
                )

            for category_name in (
                _ACCURACY_DIRECTORY,
                _CONSISTENCY_DIRECTORY,
            ):
                category = self._archive_directory / category_name
                if category.is_symlink():
                    raise ResultArchiveCorruptionError(
                        "Archive directories must not be symbolic links: "
                        f"{category}"
                    )
                if not category.exists():
                    continue
                if not category.is_dir():
                    raise ResultArchiveCorruptionError(
                        f"Archive path is not a directory: {category}"
                    )
                for group_directory in category.iterdir():
                    if group_directory.is_symlink():
                        raise ResultArchiveCorruptionError(
                            "Archive group directories must not be symbolic "
                            f"links: {group_directory}"
                        )
                    if not group_directory.is_dir():
                        continue
                    candidates.extend(
                        entry
                        for entry in group_directory.iterdir()
                        if entry.suffix.casefold() == ".json"
                    )
        except ResultArchiveError:
            raise
        except OSError as exc:
            raise ResultArchiveError(
                f"Could not browse archive {self._archive_directory}: {exc}"
            ) from exc
        return tuple(sorted(candidates, key=lambda path: str(path).casefold()))

    def _validate_archive_routing(
        self,
        archive_path: Path,
        metadata: RunMetadata,
    ) -> None:
        relative = archive_path.relative_to(self._archive_directory)
        if len(relative.parts) == 1:
            # Legacy root-level archives remain fully supported and are not
            # moved as a side effect of reading.
            return
        try:
            expected_directory = self._archive_directory_for_metadata(metadata)
        except ResultArchiveError as exc:
            raise ResultArchiveCorruptionError(
                "Nested archive contains invalid group routing metadata"
            ) from exc
        if archive_path.parent != expected_directory:
            raise ResultArchiveCorruptionError(
                "Archive file location does not match its group metadata"
            )

    def _validate_archive_file_location(self, archive_path: Path) -> None:
        if archive_path.is_symlink():
            raise ResultArchiveCorruptionError(
                f"Archive files must not be symbolic links: {archive_path}"
            )
        try:
            resolved = archive_path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ArchivedResultNotFoundError(
                f"Archived result not found: {archive_path.stem}"
            ) from exc
        except OSError as exc:
            raise ResultArchiveError(
                f"Could not resolve archive file {archive_path}: {exc}"
            ) from exc
        try:
            resolved.relative_to(self._archive_directory)
            relative = archive_path.relative_to(self._archive_directory)
        except ValueError:
            raise ResultArchiveCorruptionError(
                "Archive file resolves outside the configured archive root"
            )
        if not _is_supported_archive_relative_path(relative):
            raise ResultArchiveCorruptionError(
                f"Archive file uses an unsupported directory layout: {archive_path}"
            )
        current = self._archive_directory
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ResultArchiveCorruptionError(
                    f"Archive directories must not be symbolic links: {current}"
                )
        try:
            case_equivalent_names = {
                entry.name
                for entry in archive_path.parent.iterdir()
                if entry.name.casefold() == archive_path.name.casefold()
            }
        except OSError as exc:
            raise ResultArchiveError(
                f"Could not inspect archive file {archive_path}: {exc}"
            ) from exc
        if archive_path.name not in case_equivalent_names:
            raise ResultArchiveCorruptionError(
                "Archive filename must use the canonical lowercase run ID"
            )
        if not resolved.is_file():
            raise ResultArchiveCorruptionError(
                f"Archive path is not a regular file: {archive_path}"
            )


def _validate_requested_run_id(value: object) -> str:
    try:
        return require_canonical_run_id(value)
    except ValueError as exc:
        raise InvalidRunIdError(
            "run_id must be a canonical lowercase UUID"
        ) from exc


def _archive_group_value(
    value: object,
    attribute_name: str,
    *,
    present: bool,
) -> str | None:
    if not present:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise ResultArchiveError(
            f"{attribute_name} archive metadata must be a clean non-empty string"
        )
    return value


def _safe_group_directory_name(group: str) -> str:
    normalized = unicodedata.normalize("NFKC", group).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    slug = slug[:48].rstrip("-") or "unnamed"
    digest = hashlib.sha256(group.encode("utf-8")).hexdigest()[:12]
    return f"group-{slug}-{digest}"


def _is_supported_archive_relative_path(path: Path) -> bool:
    parts = path.parts
    if len(parts) == 1:
        return True
    if len(parts) == 2 and parts[0] == _GENERAL_DIRECTORY:
        return True
    return (
        len(parts) == 3
        and parts[0] in (_ACCURACY_DIRECTORY, _CONSISTENCY_DIRECTORY)
        and bool(parts[1])
    )


def _object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResultArchiveCorruptionError(
                f"Archive JSON contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ResultArchiveCorruptionError(
        f"Archive JSON contains non-finite number: {value}"
    )


def _optional_filter(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} filter must be a non-empty string")
    return value.strip().casefold()


def _finite_delta(candidate: float, baseline: float, label: str) -> float:
    delta = candidate - baseline
    if not math.isfinite(delta):
        raise ResultComparisonError(
            f"{label} delta is outside the finite float range"
        )
    return delta


def _datetime_to_json(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
