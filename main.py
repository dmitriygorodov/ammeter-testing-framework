from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.AcmeAmmeter import AcmeAmmeter
from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.devices.errors import AmmeterClientError
from src.devices.factory import AmmeterFactory, AmmeterRegistry
from src.testing.archive import JsonResultArchive
from src.testing.archive_models import ArchivedTestResult, RunMetadata
from src.testing.acceptance import acceptance_policy_from_config
from src.testing.acceptance_models import EvaluatedSamplingResult
from src.testing.consistency_models import HistoricalConsistencyAssessment
from src.testing.accuracy_models import (
    ReferenceAccuracyAssessment,
    ReferenceCurrent,
)
from src.testing.models import (
    AnalyzedSamplingResult,
    SamplingPlan,
    SamplingRunResult,
)
from src.testing.test_framework import AmmeterTestFramework
from src.testing.visualization import ResultVisualizer
from src.utils.config import (
    DEFAULT_CONFIG_PATH,
    AmmeterConfig,
    ApplicationConfig,
    ConfigurationError,
    UsbAmmeterConfig,
    load_application_config,
)


LOGGER = logging.getLogger(__name__)

EMULATOR_TYPES: dict[str, type[AmmeterEmulatorBase]] = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
    "acme": AcmeAmmeter,
}


def run_demo(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, float]:
    """Start all configured emulators, read each once, then shut them down."""

    config = load_application_config(config_path)
    framework = AmmeterTestFramework(
        registry=AmmeterFactory().create_registry(config)
    )
    with _running_configured_emulators(config):
        measurements: dict[str, float] = {}
        for settings in config.ammeters:
            measurement = framework.measure_once(settings.name)
            measurements[settings.name] = measurement.current_a
        return measurements


def run_sampling_demo(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    ammeter_name: str | None = None,
) -> dict[str, SamplingRunResult]:
    """Run the configured sampling plan against one or all local emulators."""

    config = load_application_config(config_path)
    sampling_plan = _configured_sampling_plan(config)
    framework = AmmeterTestFramework(
        registry=AmmeterFactory().create_registry(config),
        sampling_plan=sampling_plan,
    )
    requested_names = (
        [ammeter_name]
        if ammeter_name is not None
        else [settings.name for settings in config.ammeters]
    )

    with _running_configured_emulators(config):
        results: dict[str, SamplingRunResult] = {}
        for requested_name in requested_names:
            result = framework.run_test(requested_name)
            results[result.ammeter_name] = result
        return results


def run_analysis_demo(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    ammeter_name: str | None = None,
) -> dict[str, AnalyzedSamplingResult]:
    """Sample and statistically analyze one or all local emulators."""

    config = load_application_config(config_path)
    framework = AmmeterTestFramework(
        registry=AmmeterFactory().create_registry(config),
        sampling_plan=_configured_sampling_plan(config),
    )
    requested_names = (
        [ammeter_name]
        if ammeter_name is not None
        else [settings.name for settings in config.ammeters]
    )

    with _running_configured_emulators(config):
        results: dict[str, AnalyzedSamplingResult] = {}
        for requested_name in requested_names:
            result = framework.run_analyzed_test(requested_name)
            results[result.ammeter_name] = result
        return results


def run_archive_demo(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    archive_directory: str | Path | None = None,
    ammeter_name: str | None = None,
    metadata: RunMetadata | None = None,
) -> dict[str, ArchivedTestResult]:
    """Sample, analyze, and archive one or all configured local emulators."""

    config = load_application_config(config_path)
    configured_result_management = config.result_management
    if archive_directory is None:
        if configured_result_management is None:
            raise ConfigurationError(
                "An archive demo requires result_management.archive_directory"
            )
        archive_directory = configured_result_management.archive_directory
    framework = AmmeterTestFramework(
        registry=AmmeterFactory().create_registry(config),
        sampling_plan=_configured_sampling_plan(config),
        result_archive=JsonResultArchive(archive_directory),
    )
    requested_names = (
        [ammeter_name]
        if ammeter_name is not None
        else [settings.name for settings in config.ammeters]
    )

    with _running_configured_emulators(config):
        results: dict[str, ArchivedTestResult] = {}
        for requested_name in requested_names:
            result = framework.run_archived_test(
                requested_name,
                metadata=metadata,
            )
            results[result.ammeter_name] = result
        return results


def run_accuracy_assessment(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    run_ids: Iterable[str],
    reference: ReferenceCurrent,
    archive_directory: str | Path | None = None,
) -> ReferenceAccuracyAssessment:
    """Assess compatible archived runs against a supplied current reference."""

    if archive_directory is None:
        config = load_application_config(config_path)
        configured_result_management = config.result_management
        if configured_result_management is None:
            raise ConfigurationError(
                "Accuracy assessment requires an archive directory"
            )
        archive_directory = configured_result_management.archive_directory
    framework = AmmeterTestFramework(
        registry=AmmeterRegistry(),
        result_archive=JsonResultArchive(archive_directory),
    )
    return framework.assess_archived_accuracy(
        run_ids,
        reference=reference,
    )


def run_acceptance_demo(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    ammeter_name: str | None = None,
) -> dict[str, EvaluatedSamplingResult]:
    """Acquire, analyze, and evaluate configured local ammeters."""

    config = load_application_config(config_path)
    if config.acceptance is None:
        raise ConfigurationError(
            "An acceptance demo requires testing.acceptance configuration"
        )
    requested_names = (
        [ammeter_name]
        if ammeter_name is not None
        else [settings.name for settings in config.ammeters]
    )
    policies = {}
    for requested_name in requested_names:
        configured_policy = config.acceptance.policy_for(requested_name)
        if configured_policy is None:
            raise ConfigurationError(
                f"No acceptance policy applies to {requested_name!r}"
            )
        policies[requested_name] = acceptance_policy_from_config(
            configured_policy
        )
    framework = AmmeterTestFramework(
        registry=AmmeterFactory().create_registry(config),
        sampling_plan=_configured_sampling_plan(config),
    )
    with _running_configured_emulators(config):
        results: dict[str, EvaluatedSamplingResult] = {}
        for requested_name in requested_names:
            result = framework.run_evaluated_test(
                requested_name,
                policy=policies[requested_name],
            )
            results[result.analyzed_result.ammeter_name] = result
        return results


def run_consistency_assessment(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    run_ids: Iterable[str],
    archive_directory: str | Path | None = None,
) -> HistoricalConsistencyAssessment:
    """Assess a like-for-like archived series without hardware access."""

    if archive_directory is None:
        config = load_application_config(config_path)
        configured_result_management = config.result_management
        if configured_result_management is None:
            raise ConfigurationError(
                "Consistency assessment requires an archive directory"
            )
        archive_directory = configured_result_management.archive_directory
    framework = AmmeterTestFramework(
        registry=AmmeterRegistry(),
        result_archive=JsonResultArchive(archive_directory),
    )
    return framework.assess_archived_consistency(run_ids)


def render_archived_visualization(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    plot_type: str,
    run_ids: Iterable[str],
    output_path: str | Path | None = None,
    archive_directory: str | Path | None = None,
    reference: ReferenceCurrent | None = None,
    dpi: int | None = None,
) -> Path:
    """Render archived evidence without accessing hardware or changing archive data."""

    requested_ids = tuple(run_ids)
    if not requested_ids or not all(
        isinstance(run_id, str) for run_id in requested_ids
    ):
        raise TypeError("run_ids must contain one or more strings")
    supported_plot_types = {"run_overview", "accuracy", "consistency"}
    if plot_type not in supported_plot_types:
        raise ValueError(
            "plot_type must be run_overview, accuracy, or consistency"
        )
    if plot_type == "run_overview":
        if len(requested_ids) != 1:
            raise ValueError("run_overview requires exactly one run ID")
        if reference is not None:
            raise ValueError("reference is only valid for accuracy visualization")
    elif plot_type == "accuracy":
        if len(requested_ids) < 2:
            raise ValueError("accuracy requires at least two run IDs")
        if reference is None:
            raise ValueError("accuracy visualization requires a reference")
    else:
        if len(requested_ids) < 3:
            raise ValueError("consistency requires at least three run IDs")
        if reference is not None:
            raise ValueError("reference is only valid for accuracy visualization")

    config = None
    if archive_directory is None or output_path is None:
        config = load_application_config(config_path)
    if archive_directory is None:
        assert config is not None
        if config.result_management is None:
            raise ConfigurationError(
                "Visualization requires an archive directory"
            )
        archive_directory = config.result_management.archive_directory
    if output_path is None:
        assert config is not None
        visualization = config.visualization
        if (
            visualization is None
            or not visualization.enabled
            or plot_type not in visualization.plot_types
            or visualization.output_directory is None
        ):
            raise ConfigurationError(
                "A default visualization output requires an enabled plot type "
                "and output directory"
            )
        output_path = visualization.output_directory / (
            f"{plot_type}-{requested_ids[0]}.{visualization.image_format}"
        )
    if dpi is None:
        visualization = None if config is None else config.visualization
        dpi = 160 if visualization is None else visualization.dpi

    framework = AmmeterTestFramework(
        registry=AmmeterRegistry(),
        result_archive=JsonResultArchive(archive_directory),
        result_visualizer=ResultVisualizer(),
    )
    if plot_type == "run_overview":
        archived = framework.load_archived_result(requested_ids[0])
        figure = framework.visualize_result(archived.analyzed_result)
    elif plot_type == "accuracy":
        assert reference is not None
        assessment = framework.assess_archived_accuracy(
            requested_ids,
            reference=reference,
        )
        figure = framework.visualize_accuracy(assessment)
    else:
        assessment = framework.assess_archived_consistency(requested_ids)
        figure = framework.visualize_consistency(assessment)
    return framework.save_visualization(figure, output_path, dpi=dpi)


def _configured_sampling_plan(config: ApplicationConfig) -> SamplingPlan:
    if config.sampling is None:
        raise ConfigurationError(
            "A sampled demo requires a valid testing.sampling configuration"
        )
    return SamplingPlan(
        sampling_frequency_hz=config.sampling.sampling_frequency_hz,
        measurements_count=config.sampling.measurements_count,
        total_duration_seconds=config.sampling.total_duration_seconds,
    )


@contextmanager
def _running_configured_emulators(
    config: ApplicationConfig,
) -> Iterator[list[tuple[AmmeterConfig, AmmeterEmulatorBase]]]:
    configured_emulators = _build_emulators(config)
    started_emulators: list[AmmeterEmulatorBase] = []
    active_exception = False

    try:
        startup_timeout = config.communication.server_startup_timeout_seconds
        for _, emulator in configured_emulators:
            emulator.start(startup_timeout)
            started_emulators.append(emulator)
        yield configured_emulators
    except BaseException:
        active_exception = True
        raise
    finally:
        shutdown_timeout = config.communication.server_shutdown_timeout_seconds
        shutdown_errors: list[str] = []
        for emulator in reversed(started_emulators):
            try:
                emulator.stop(shutdown_timeout)
            except RuntimeError as exc:
                shutdown_errors.append(str(exc))

        if shutdown_errors:
            message = "Server shutdown failed: " + "; ".join(shutdown_errors)
            if active_exception:
                LOGGER.error("%s; preserving the original failure", message)
            else:
                raise RuntimeError(message)


def _build_emulators(
    config: ApplicationConfig,
) -> list[tuple[AmmeterConfig, AmmeterEmulatorBase]]:
    configured_emulators: list[tuple[AmmeterConfig, AmmeterEmulatorBase]] = []
    for settings in config.ammeters:
        if not settings.emulated:
            continue
        # Emulated USB is an in-process backend created by AmmeterFactory; it
        # has no listening socket or separate lifecycle to start here.
        if isinstance(settings, UsbAmmeterConfig):
            continue
        if not isinstance(settings, AmmeterConfig):
            raise ConfigurationError(
                f"Only TCP ammeters can use local emulation: {settings.name!r}"
            )
        try:
            emulator_type = EMULATOR_TYPES[settings.name]
        except KeyError as exc:
            supported = ", ".join(sorted(EMULATOR_TYPES))
            raise ConfigurationError(
                f"Unsupported ammeter {settings.name!r}; supported values: {supported}"
            ) from exc
        configured_emulators.append(
            (
                settings,
                emulator_type(
                    port=settings.port,
                    host=settings.host,
                    command=settings.command_bytes,
                    fault_profile=(
                        None
                        if config.fault_injection is None
                        else config.fault_injection.profile_for(settings.name)
                    ),
                ),
            )
        )
    return configured_emulators


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        measurements = run_demo()
    except (AmmeterClientError, ConfigurationError, OSError, RuntimeError) as exc:
        LOGGER.error("Ammeter demo failed: %s", exc)
        return 1

    print("Ammeter measurements:")
    for name, current_a in measurements.items():
        print(f"  {name.upper():8s} {current_a:.6f} A")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
