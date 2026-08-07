from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from Ammeters.faults import FaultKind, FaultProfile, FaultRule

try:
    import yaml
    from yaml import YAMLError
except (ImportError, ModuleNotFoundError):  # Report an error only when config is used.
    yaml = None
    YAMLError = Exception


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
MAX_COMMAND_BYTES = 1_024
SUPPORTED_VISUALIZATION_PLOT_TYPES = (
    "run_overview",
    "accuracy",
    "consistency",
)
SUPPORTED_VISUALIZATION_FORMATS = ("png", "svg", "pdf")


class ConfigurationError(ValueError):
    """The application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AmmeterConfig:
    name: str
    host: str
    port: int
    command: str

    @property
    def command_bytes(self) -> bytes:
        return self.command.encode("utf-8")


@dataclass(frozen=True, slots=True)
class CommunicationConfig:
    request_timeout_seconds: float
    server_startup_timeout_seconds: float
    server_shutdown_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SamplingConfig:
    sampling_frequency_hz: float
    measurements_count: int | None = None
    total_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        normalized_frequency = _coerce_positive_finite_number(
            self.sampling_frequency_hz,
            "testing.sampling.sampling_frequency_hz",
        )
        object.__setattr__(
            self,
            "sampling_frequency_hz",
            normalized_frequency,
        )
        if not math.isfinite(1.0 / self.sampling_frequency_hz):
            raise ConfigurationError(
                "testing.sampling.sampling_frequency_hz is too small to "
                "produce a finite period"
            )
        if self.measurements_count is not None and (
            isinstance(self.measurements_count, bool)
            or not isinstance(self.measurements_count, int)
            or self.measurements_count <= 0
        ):
            raise ConfigurationError(
                "testing.sampling.measurements_count must be a positive integer"
            )
        if self.total_duration_seconds is not None:
            normalized_duration = _coerce_positive_finite_number(
                self.total_duration_seconds,
                "testing.sampling.total_duration_seconds",
            )
            object.__setattr__(
                self,
                "total_duration_seconds",
                normalized_duration,
            )
        if (
            self.measurements_count is None
            and self.total_duration_seconds is None
        ):
            raise ConfigurationError(
                "testing.sampling requires measurements_count, "
                "total_duration_seconds, or both"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceCurrentConfig:
    current_a: float
    source: str
    expanded_uncertainty_a: float | None = None
    calibration_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "current_a",
            _coerce_finite_number(
                self.current_a,
                "testing.acceptance.reference.current_a",
            ),
        )
        _require_clean_config_text(
            self.source,
            "testing.acceptance.reference.source",
        )
        if self.expanded_uncertainty_a is not None:
            uncertainty = _coerce_nonnegative_finite_number(
                self.expanded_uncertainty_a,
                "testing.acceptance.reference.expanded_uncertainty_a",
            )
            object.__setattr__(self, "expanded_uncertainty_a", uncertainty)
        if self.calibration_id is not None:
            _require_clean_config_text(
                self.calibration_id,
                "testing.acceptance.reference.calibration_id",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptanceLimitsConfig:
    minimum_current_a: float | None = None
    maximum_current_a: float | None = None
    maximum_absolute_bias_a: float | None = None
    maximum_relative_error_percent: float | None = None
    maximum_standard_deviation_a: float | None = None
    maximum_start_lateness_seconds: float | None = None
    maximum_acquisition_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("minimum_current_a", "maximum_current_a"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _coerce_finite_number(
                        value,
                        f"testing.acceptance.limits.{field_name}",
                    ),
                )
        for field_name in (
            "maximum_absolute_bias_a",
            "maximum_relative_error_percent",
            "maximum_standard_deviation_a",
            "maximum_start_lateness_seconds",
            "maximum_acquisition_duration_seconds",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _coerce_nonnegative_finite_number(
                        value,
                        f"testing.acceptance.limits.{field_name}",
                    ),
                )
        if (
            self.minimum_current_a is not None
            and self.maximum_current_a is not None
            and self.minimum_current_a > self.maximum_current_a
        ):
            raise ConfigurationError(
                "testing.acceptance minimum_current_a must not exceed "
                "maximum_current_a"
            )

    @property
    def has_limits(self) -> bool:
        return any(
            getattr(self, field_name) is not None
            for field_name in _ACCEPTANCE_LIMIT_KEYS
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptancePolicyConfig:
    policy_name: str
    policy_version: str
    limits: AcceptanceLimitsConfig
    reference: ReferenceCurrentConfig | None = None

    def __post_init__(self) -> None:
        _require_clean_config_text(
            self.policy_name,
            "testing.acceptance.policy_name",
        )
        _require_clean_config_text(
            self.policy_version,
            "testing.acceptance.policy_version",
        )
        if not isinstance(self.limits, AcceptanceLimitsConfig):
            raise TypeError("limits must be AcceptanceLimitsConfig")
        if not self.limits.has_limits:
            raise ConfigurationError(
                "Every acceptance policy requires at least one limit"
            )
        if self.reference is not None and not isinstance(
            self.reference,
            ReferenceCurrentConfig,
        ):
            raise TypeError("reference must be ReferenceCurrentConfig or None")
        if (
            self.limits.maximum_absolute_bias_a is not None
            or self.limits.maximum_relative_error_percent is not None
        ) and self.reference is None:
            raise ConfigurationError(
                "Acceptance bias and relative-error limits require an explicit "
                "reference"
            )
        if (
            self.limits.maximum_relative_error_percent is not None
            and self.reference is not None
            and self.reference.current_a == 0.0
        ):
            raise ConfigurationError(
                "An acceptance relative-error limit requires a nonzero "
                "reference current"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptanceConfig:
    default_policy: AcceptancePolicyConfig | None
    ammeter_policies: tuple[tuple[str, AcceptancePolicyConfig], ...] = ()

    def __post_init__(self) -> None:
        if self.default_policy is not None and not isinstance(
            self.default_policy,
            AcceptancePolicyConfig,
        ):
            raise TypeError("default_policy must be AcceptancePolicyConfig or None")
        if not isinstance(self.ammeter_policies, tuple):
            raise TypeError("ammeter_policies must be a tuple")
        names: set[str] = set()
        for item in self.ammeter_policies:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError(
                    "ammeter_policies must contain (name, policy) tuples"
                )
            name, policy = item
            _require_clean_config_text(name, "acceptance ammeter name")
            if name != name.casefold():
                raise ValueError("acceptance ammeter names must be normalized")
            if name in names:
                raise ValueError(f"Duplicate acceptance ammeter policy: {name}")
            names.add(name)
            if not isinstance(policy, AcceptancePolicyConfig):
                raise TypeError(
                    "ammeter_policies values must be AcceptancePolicyConfig"
                )
        if self.default_policy is None and not self.ammeter_policies:
            raise ConfigurationError(
                "Acceptance configuration requires a default or ammeter policy"
            )

    def policy_for(self, ammeter_name: str) -> AcceptancePolicyConfig | None:
        _require_clean_config_text(ammeter_name, "ammeter_name")
        normalized_name = ammeter_name.casefold()
        for name, policy in self.ammeter_policies:
            if name == normalized_name:
                return policy
        return self.default_policy


@dataclass(frozen=True, slots=True)
class ResultManagementConfig:
    archive_directory: Path

    def __post_init__(self) -> None:
        if not isinstance(self.archive_directory, Path):
            raise TypeError("archive_directory must be a pathlib.Path")


@dataclass(frozen=True, slots=True)
class VisualizationConfig:
    enabled: bool
    plot_types: tuple[str, ...]
    output_directory: Path | None = None
    image_format: str = "png"
    dpi: int = 160

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        if not isinstance(self.plot_types, tuple) or not all(
            isinstance(plot_type, str) for plot_type in self.plot_types
        ):
            raise TypeError("plot_types must be a tuple of strings")
        if len(set(self.plot_types)) != len(self.plot_types):
            raise ConfigurationError(
                "analysis.visualization.plot_types must not contain duplicates"
            )
        unsupported_plot_types = set(self.plot_types) - set(
            SUPPORTED_VISUALIZATION_PLOT_TYPES
        )
        if unsupported_plot_types:
            raise ConfigurationError(
                "analysis.visualization.plot_types contains unsupported values: "
                + ", ".join(sorted(unsupported_plot_types))
            )
        if self.output_directory is not None and not isinstance(
            self.output_directory,
            Path,
        ):
            raise TypeError("output_directory must be a pathlib.Path or None")
        if self.image_format not in SUPPORTED_VISUALIZATION_FORMATS:
            raise ConfigurationError(
                "analysis.visualization.image_format must be one of: "
                + ", ".join(SUPPORTED_VISUALIZATION_FORMATS)
            )
        if isinstance(self.dpi, bool) or not isinstance(self.dpi, int):
            raise ConfigurationError(
                "analysis.visualization.dpi must be an integer from 72 to 600"
            )
        if not 72 <= self.dpi <= 600:
            raise ConfigurationError(
                "analysis.visualization.dpi must be an integer from 72 to 600"
            )
        if self.enabled and not self.plot_types:
            raise ConfigurationError(
                "analysis.visualization.plot_types must not be empty when enabled"
            )
        if self.enabled and self.output_directory is None:
            raise ConfigurationError(
                "analysis.visualization.output_directory is required when enabled"
            )


@dataclass(frozen=True, slots=True)
class FaultInjectionConfig:
    enabled: bool
    ammeter_profiles: tuple[tuple[str, FaultProfile], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        if not isinstance(self.ammeter_profiles, tuple):
            raise TypeError("ammeter_profiles must be a tuple")
        names: set[str] = set()
        for item in self.ammeter_profiles:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError(
                    "ammeter_profiles must contain (name, profile) tuples"
                )
            name, profile = item
            if not isinstance(name, str) or not name or name != name.casefold():
                raise ValueError("Fault-injection ammeter names must be normalized")
            if name in names:
                raise ValueError(f"Duplicate fault profile for ammeter: {name}")
            names.add(name)
            if not isinstance(profile, FaultProfile):
                raise TypeError("Fault profiles must be FaultProfile records")
            if not profile.rules:
                raise ValueError("Configured fault profiles must contain rules")
        if self.enabled and not self.ammeter_profiles:
            raise ConfigurationError(
                "emulation.fault_injection.ammeters must not be empty when enabled"
            )
        if not self.enabled and self.ammeter_profiles:
            raise ConfigurationError(
                "Disabled fault injection must not contain ammeter rules"
            )

    def profile_for(self, ammeter_name: str) -> FaultProfile | None:
        if not isinstance(ammeter_name, str) or not ammeter_name.strip():
            raise ValueError("ammeter_name must be a non-empty string")
        normalized_name = ammeter_name.strip().casefold()
        if not self.enabled:
            return None
        for name, profile in self.ammeter_profiles:
            if name == normalized_name:
                return profile
        return None


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    ammeters: tuple[AmmeterConfig, ...]
    communication: CommunicationConfig
    sampling: SamplingConfig | None = None
    result_management: ResultManagementConfig | None = None
    acceptance: AcceptanceConfig | None = None
    visualization: VisualizationConfig | None = None
    fault_injection: FaultInjectionConfig | None = None


def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load the YAML document and validate its root shape.

    This raw loader remains available to callers that need the source mapping.
    Framework code uses ``load_application_config`` for validated settings.
    """

    if yaml is None:
        raise ConfigurationError(
            "PyYAML is required to read config.yaml. "
            "Install the project dependencies with 'python -m pip install -r requirements.txt'."
        )

    path = Path(config_path).expanduser().resolve()
    try:
        with path.open("r", encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Could not read configuration file {path}: {exc}") from exc
    except YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigurationError("Configuration root must be a mapping")
    return data


def load_application_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> ApplicationConfig:
    """Load and validate all configured application services."""

    try:
        resolved_config_path = Path(config_path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"Configuration path is invalid: {config_path!r}"
        ) from exc
    raw_config = load_config(resolved_config_path)
    raw_ammeters = raw_config.get("ammeters")
    if not isinstance(raw_ammeters, Mapping) or not raw_ammeters:
        raise ConfigurationError("'ammeters' must be a non-empty mapping")

    ammeters: list[AmmeterConfig] = []
    endpoints: set[tuple[str, int]] = set()
    names: set[str] = set()
    for raw_name, raw_settings in raw_ammeters.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ConfigurationError("Every ammeter must have a non-empty name")
        name = raw_name.strip().lower()
        if name in names:
            raise ConfigurationError(f"Duplicate ammeter name after normalization: {name}")
        names.add(name)
        if not isinstance(raw_settings, Mapping):
            raise ConfigurationError(f"ammeters.{name} must be a mapping")

        host = raw_settings.get("host")
        port = raw_settings.get("port")
        command = raw_settings.get("command")

        if not isinstance(host, str) or not host.strip():
            raise ConfigurationError(f"ammeters.{name}.host must be a non-empty string")
        host = host.strip()
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            raise ConfigurationError(
                f"ammeters.{name}.port must be an integer between 1 and 65535"
            )
        if not isinstance(command, str) or not command.strip():
            raise ConfigurationError(
                f"ammeters.{name}.command must be a non-empty string"
            )
        if command != command.strip():
            raise ConfigurationError(
                f"ammeters.{name}.command must not have leading or trailing whitespace"
            )
        if "\r" in command or "\n" in command:
            raise ConfigurationError(
                f"ammeters.{name}.command must not contain line delimiters"
            )
        if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise ConfigurationError(
                f"ammeters.{name}.command must not exceed "
                f"{MAX_COMMAND_BYTES} encoded bytes"
            )

        endpoint = (host, port)
        if endpoint in endpoints:
            raise ConfigurationError(
                f"Duplicate ammeter endpoint configured at {host}:{port}"
            )
        endpoints.add(endpoint)
        ammeters.append(
            AmmeterConfig(name=name, host=host, port=port, command=command)
        )

    raw_communication = raw_config.get("communication", {})
    if not isinstance(raw_communication, Mapping):
        raise ConfigurationError("'communication' must be a mapping")
    communication = CommunicationConfig(
        request_timeout_seconds=_positive_number(
            raw_communication,
            "request_timeout_seconds",
            default=1.0,
        ),
        server_startup_timeout_seconds=_positive_number(
            raw_communication,
            "server_startup_timeout_seconds",
            default=2.0,
        ),
        server_shutdown_timeout_seconds=_positive_number(
            raw_communication,
            "server_shutdown_timeout_seconds",
            default=2.0,
        ),
    )
    sampling = _parse_sampling_config(raw_config)
    result_management = _parse_result_management_config(
        raw_config,
        base_directory=resolved_config_path.parent,
    )
    acceptance = _parse_acceptance_config(
        raw_config,
        ammeter_names=tuple(settings.name for settings in ammeters),
    )
    visualization = _parse_visualization_config(
        raw_config,
        base_directory=resolved_config_path.parent,
    )
    fault_injection = _parse_fault_injection_config(
        raw_config,
        ammeter_names=tuple(settings.name for settings in ammeters),
    )
    return ApplicationConfig(
        ammeters=tuple(ammeters),
        communication=communication,
        sampling=sampling,
        result_management=result_management,
        acceptance=acceptance,
        visualization=visualization,
        fault_injection=fault_injection,
    )


def _parse_fault_injection_config(
    raw_config: Mapping[str, Any],
    *,
    ammeter_names: tuple[str, ...],
) -> FaultInjectionConfig | None:
    raw_emulation = raw_config.get("emulation")
    if raw_emulation is None:
        return None
    if not isinstance(raw_emulation, Mapping):
        raise ConfigurationError("'emulation' must be a mapping")
    unexpected_emulation_keys = set(raw_emulation) - {"fault_injection"}
    if unexpected_emulation_keys:
        raise ConfigurationError(
            "emulation contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_emulation_keys))
        )
    raw_faults = raw_emulation.get("fault_injection")
    if raw_faults is None:
        return None
    if not isinstance(raw_faults, Mapping):
        raise ConfigurationError("'emulation.fault_injection' must be a mapping")
    if not raw_faults:
        return None
    unexpected_keys = set(raw_faults) - {"enabled", "ammeters"}
    if unexpected_keys:
        raise ConfigurationError(
            "emulation.fault_injection contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_keys))
        )
    enabled = raw_faults.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigurationError(
            "emulation.fault_injection.enabled must be a bool"
        )
    raw_profiles = raw_faults.get("ammeters", {})
    if not isinstance(raw_profiles, Mapping):
        raise ConfigurationError(
            "emulation.fault_injection.ammeters must be a mapping"
        )

    configured_names = set(ammeter_names)
    normalized_names: set[str] = set()
    profiles: list[tuple[str, FaultProfile]] = []
    supported_rule_keys = {
        "request_number",
        "type",
        "delay_seconds",
        "error_message",
        "response_payload",
        "current_offset_a",
    }
    for raw_name, raw_rules in raw_profiles.items():
        normalized_name = _normalized_ammeter_name(
            raw_name,
            "emulation.fault_injection.ammeters",
        )
        if normalized_name in normalized_names:
            raise ConfigurationError(
                "Duplicate fault profile after normalization: "
                f"{normalized_name}"
            )
        normalized_names.add(normalized_name)
        if normalized_name not in configured_names:
            raise ConfigurationError(
                "Fault injection references an unknown ammeter: "
                f"{normalized_name}"
            )
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ConfigurationError(
                f"Fault profile {normalized_name!r} must be a non-empty list"
            )
        rules: list[FaultRule] = []
        for index, raw_rule in enumerate(raw_rules):
            field_name = (
                "emulation.fault_injection.ammeters."
                f"{normalized_name}[{index}]"
            )
            if not isinstance(raw_rule, Mapping):
                raise ConfigurationError(f"{field_name} must be a mapping")
            unexpected_rule_keys = set(raw_rule) - supported_rule_keys
            if unexpected_rule_keys:
                raise ConfigurationError(
                    f"{field_name} contains unsupported keys: "
                    + ", ".join(
                        sorted(str(key) for key in unexpected_rule_keys)
                    )
                )
            try:
                kind = FaultKind(raw_rule.get("type"))
                rule = FaultRule(
                    request_number=raw_rule.get("request_number"),
                    kind=kind,
                    delay_seconds=raw_rule.get("delay_seconds"),
                    error_message=raw_rule.get("error_message"),
                    response_payload=raw_rule.get("response_payload"),
                    current_offset_a=raw_rule.get("current_offset_a"),
                )
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(f"{field_name} is invalid: {exc}") from exc
            rules.append(rule)
        try:
            profile = FaultProfile(
                tuple(sorted(rules, key=lambda rule: rule.request_number))
            )
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"Fault profile {normalized_name!r} is invalid: {exc}"
            ) from exc
        profiles.append((normalized_name, profile))
    return FaultInjectionConfig(
        enabled=enabled,
        ammeter_profiles=tuple(sorted(profiles, key=lambda item: item[0])),
    )


def _parse_visualization_config(
    raw_config: Mapping[str, Any],
    *,
    base_directory: Path,
) -> VisualizationConfig | None:
    raw_analysis = raw_config.get("analysis")
    if raw_analysis is None:
        return None
    if not isinstance(raw_analysis, Mapping):
        raise ConfigurationError("'analysis' must be a mapping")
    raw_visualization = raw_analysis.get("visualization")
    if raw_visualization is None:
        return None
    if not isinstance(raw_visualization, Mapping):
        raise ConfigurationError("'analysis.visualization' must be a mapping")
    if not raw_visualization:
        return None
    supported_keys = {
        "enabled",
        "plot_types",
        "output_directory",
        "image_format",
        "dpi",
    }
    unexpected_keys = set(raw_visualization) - supported_keys
    if unexpected_keys:
        raise ConfigurationError(
            "analysis.visualization contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_keys))
        )

    enabled = raw_visualization.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigurationError("analysis.visualization.enabled must be a bool")
    raw_plot_types = raw_visualization.get("plot_types", [])
    if not isinstance(raw_plot_types, list) or not all(
        isinstance(plot_type, str) and plot_type
        for plot_type in raw_plot_types
    ):
        raise ConfigurationError(
            "analysis.visualization.plot_types must be a list of supported strings"
        )
    if len(set(raw_plot_types)) != len(raw_plot_types):
        raise ConfigurationError(
            "analysis.visualization.plot_types must not contain duplicates"
        )
    unsupported_plot_types = set(raw_plot_types) - set(
        SUPPORTED_VISUALIZATION_PLOT_TYPES
    )
    if unsupported_plot_types:
        raise ConfigurationError(
            "analysis.visualization.plot_types contains unsupported values: "
            + ", ".join(sorted(unsupported_plot_types))
        )

    raw_directory = raw_visualization.get("output_directory")
    output_directory: Path | None = None
    if raw_directory is not None:
        if (
            not isinstance(raw_directory, str)
            or not raw_directory.strip()
            or raw_directory != raw_directory.strip()
            or "\x00" in raw_directory
        ):
            raise ConfigurationError(
                "analysis.visualization.output_directory must be a clean, "
                "non-empty path string or null"
            )
        try:
            output_directory = Path(raw_directory).expanduser()
            if not output_directory.is_absolute():
                output_directory = base_directory / output_directory
            output_directory = output_directory.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConfigurationError(
                "analysis.visualization.output_directory is not a valid path"
            ) from exc

    raw_format = raw_visualization.get("image_format", "png")
    if not isinstance(raw_format, str) or raw_format != raw_format.casefold():
        raise ConfigurationError(
            "analysis.visualization.image_format must be a lowercase string"
        )
    raw_dpi = raw_visualization.get("dpi", 160)
    return VisualizationConfig(
        enabled=enabled,
        plot_types=tuple(raw_plot_types),
        output_directory=output_directory,
        image_format=raw_format,
        dpi=raw_dpi,
    )


def _parse_sampling_config(raw_config: Mapping[str, Any]) -> SamplingConfig | None:
    raw_testing = raw_config.get("testing")
    if raw_testing is None:
        return None
    if not isinstance(raw_testing, Mapping):
        raise ConfigurationError("'testing' must be a mapping")

    raw_sampling = raw_testing.get("sampling")
    if raw_sampling is None:
        return None
    if not isinstance(raw_sampling, Mapping):
        raise ConfigurationError("'testing.sampling' must be a mapping")

    raw_count = raw_sampling.get("measurements_count")
    raw_duration = raw_sampling.get("total_duration_seconds")
    raw_frequency = raw_sampling.get("sampling_frequency_hz")
    if raw_count is None and raw_duration is None and raw_frequency is None:
        return None

    if raw_count is not None and (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or raw_count <= 0
    ):
        raise ConfigurationError(
            "testing.sampling.measurements_count must be a positive integer"
        )
    duration = _optional_positive_number(
        raw_duration,
        "testing.sampling.total_duration_seconds",
    )
    frequency = _optional_positive_number(
        raw_frequency,
        "testing.sampling.sampling_frequency_hz",
    )
    if raw_count is None and duration is None:
        raise ConfigurationError(
            "testing.sampling requires measurements_count, "
            "total_duration_seconds, or both"
        )
    if frequency is None:
        raise ConfigurationError(
            "testing.sampling.sampling_frequency_hz is required when sampling "
            "is configured"
        )
    return SamplingConfig(
        sampling_frequency_hz=frequency,
        measurements_count=raw_count,
        total_duration_seconds=duration,
    )


def _parse_result_management_config(
    raw_config: Mapping[str, Any],
    *,
    base_directory: Path,
) -> ResultManagementConfig | None:
    raw_result_management = raw_config.get("result_management")
    if raw_result_management is None:
        return None
    if not isinstance(raw_result_management, Mapping):
        raise ConfigurationError("'result_management' must be a mapping")
    if not raw_result_management:
        return None
    unexpected_keys = set(raw_result_management) - {"archive_directory"}
    if unexpected_keys:
        raise ConfigurationError(
            "result_management contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_keys))
        )

    raw_directory = raw_result_management.get("archive_directory")
    if not isinstance(raw_directory, str) or not raw_directory.strip():
        raise ConfigurationError(
            "result_management.archive_directory must be a non-empty string"
        )
    if raw_directory != raw_directory.strip():
        raise ConfigurationError(
            "result_management.archive_directory must not have surrounding "
            "whitespace"
        )
    if "\x00" in raw_directory:
        raise ConfigurationError(
            "result_management.archive_directory must not contain NUL characters"
        )
    try:
        archive_directory = Path(raw_directory).expanduser()
        if not archive_directory.is_absolute():
            archive_directory = base_directory / archive_directory
        archive_directory = archive_directory.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigurationError(
            "result_management.archive_directory is not a valid path"
        ) from exc
    return ResultManagementConfig(archive_directory=archive_directory)


_ACCEPTANCE_LIMIT_KEYS = (
    "minimum_current_a",
    "maximum_current_a",
    "maximum_absolute_bias_a",
    "maximum_relative_error_percent",
    "maximum_standard_deviation_a",
    "maximum_start_lateness_seconds",
    "maximum_acquisition_duration_seconds",
)


def _parse_acceptance_config(
    raw_config: Mapping[str, Any],
    *,
    ammeter_names: tuple[str, ...],
) -> AcceptanceConfig | None:
    raw_testing = raw_config.get("testing")
    if raw_testing is None:
        return None
    if not isinstance(raw_testing, Mapping):
        raise ConfigurationError("'testing' must be a mapping")
    raw_acceptance = raw_testing.get("acceptance")
    if raw_acceptance is None:
        return None
    if not isinstance(raw_acceptance, Mapping):
        raise ConfigurationError("'testing.acceptance' must be a mapping")
    if not raw_acceptance:
        return None

    supported_keys = {
        "policy_name",
        "policy_version",
        "reference",
        "limits",
        "ammeter_overrides",
    }
    unexpected_keys = set(raw_acceptance) - supported_keys
    if unexpected_keys:
        raise ConfigurationError(
            "testing.acceptance contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_keys))
        )
    policy_name = _require_clean_config_text(
        raw_acceptance.get("policy_name"),
        "testing.acceptance.policy_name",
    )
    policy_version = _require_clean_config_text(
        raw_acceptance.get("policy_version"),
        "testing.acceptance.policy_version",
    )
    raw_base_limits = _acceptance_limits_mapping(
        raw_acceptance.get("limits", {}),
        "testing.acceptance.limits",
    )
    base_limits = _parse_acceptance_limits(raw_base_limits)
    base_reference = _parse_reference_current_config(
        raw_acceptance.get("reference"),
        "testing.acceptance.reference",
    )
    default_policy = (
        AcceptancePolicyConfig(
            policy_name=policy_name,
            policy_version=policy_version,
            limits=base_limits,
            reference=base_reference,
        )
        if base_limits.has_limits
        else None
    )

    raw_overrides = raw_acceptance.get("ammeter_overrides", {})
    if not isinstance(raw_overrides, Mapping):
        raise ConfigurationError(
            "testing.acceptance.ammeter_overrides must be a mapping"
        )
    configured_names = set(ammeter_names)
    normalized_override_names: set[str] = set()
    ammeter_policies: list[tuple[str, AcceptancePolicyConfig]] = []
    for raw_name, raw_override in raw_overrides.items():
        normalized_name = _normalized_ammeter_name(
            raw_name,
            "testing.acceptance.ammeter_overrides",
        )
        if normalized_name in normalized_override_names:
            raise ConfigurationError(
                "Duplicate acceptance override after normalization: "
                f"{normalized_name}"
            )
        normalized_override_names.add(normalized_name)
        if normalized_name not in configured_names:
            raise ConfigurationError(
                "Acceptance override references an unknown ammeter: "
                f"{normalized_name}"
            )
        if not isinstance(raw_override, Mapping) or not raw_override:
            raise ConfigurationError(
                f"Acceptance override {normalized_name!r} must be a non-empty "
                "mapping"
            )
        unsupported_override_keys = set(raw_override) - {"reference", "limits"}
        if unsupported_override_keys:
            raise ConfigurationError(
                f"Acceptance override {normalized_name!r} contains unsupported "
                "keys: "
                + ", ".join(
                    sorted(str(key) for key in unsupported_override_keys)
                )
            )
        override_limits = _acceptance_limits_mapping(
            raw_override.get("limits", {}),
            (
                "testing.acceptance.ammeter_overrides."
                f"{normalized_name}.limits"
            ),
        )
        merged_limits = dict(raw_base_limits)
        merged_limits.update(override_limits)
        limits = _parse_acceptance_limits(merged_limits)
        if not limits.has_limits:
            raise ConfigurationError(
                f"Acceptance override {normalized_name!r} enables no limits"
            )
        reference = (
            _parse_reference_current_config(
                raw_override.get("reference"),
                (
                    "testing.acceptance.ammeter_overrides."
                    f"{normalized_name}.reference"
                ),
            )
            if "reference" in raw_override
            else base_reference
        )
        ammeter_policies.append(
            (
                normalized_name,
                AcceptancePolicyConfig(
                    policy_name=policy_name,
                    policy_version=policy_version,
                    limits=limits,
                    reference=reference,
                ),
            )
        )
    return AcceptanceConfig(
        default_policy=default_policy,
        ammeter_policies=tuple(
            sorted(ammeter_policies, key=lambda item: item[0])
        ),
    )


def _acceptance_limits_mapping(
    value: object,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{field_name} must be a mapping")
    unexpected_keys = set(value) - set(_ACCEPTANCE_LIMIT_KEYS)
    if unexpected_keys:
        raise ConfigurationError(
            f"{field_name} contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_keys))
        )
    return value


def _parse_acceptance_limits(
    raw_limits: Mapping[str, Any],
) -> AcceptanceLimitsConfig:
    return AcceptanceLimitsConfig(
        **{key: raw_limits.get(key) for key in _ACCEPTANCE_LIMIT_KEYS}
    )


def _parse_reference_current_config(
    value: object,
    field_name: str,
) -> ReferenceCurrentConfig | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{field_name} must be a mapping or null")
    supported_keys = {
        "current_a",
        "source",
        "expanded_uncertainty_a",
        "calibration_id",
    }
    unexpected_keys = set(value) - supported_keys
    if unexpected_keys:
        raise ConfigurationError(
            f"{field_name} contains unsupported keys: "
            + ", ".join(sorted(str(key) for key in unexpected_keys))
        )
    return ReferenceCurrentConfig(
        current_a=value.get("current_a"),
        source=value.get("source"),
        expanded_uncertainty_a=value.get("expanded_uncertainty_a"),
        calibration_id=value.get("calibration_id"),
    )


def _normalized_ammeter_name(value: object, field_name: str) -> str:
    clean = _require_clean_config_text(value, field_name)
    return clean.casefold()


def _positive_number(
    values: Mapping[str, Any],
    key: str,
    *,
    default: float,
) -> float:
    value = values.get(key, default)
    return _coerce_positive_finite_number(value, f"communication.{key}")


def _optional_positive_number(
    value: object,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    return _coerce_positive_finite_number(value, field_name)


def _coerce_positive_finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{field_name} must be a positive finite number")
    try:
        normalized_value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"{field_name} must be a positive finite number"
        ) from exc
    if not math.isfinite(normalized_value) or normalized_value <= 0:
        raise ConfigurationError(f"{field_name} must be a positive finite number")
    return normalized_value


def _coerce_finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{field_name} must be a finite number")
    try:
        normalized_value = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(normalized_value):
        raise ConfigurationError(f"{field_name} must be a finite number")
    return 0.0 if normalized_value == 0.0 else normalized_value


def _coerce_nonnegative_finite_number(
    value: object,
    field_name: str,
) -> float:
    normalized_value = _coerce_finite_number(value, field_name)
    if normalized_value < 0.0:
        raise ConfigurationError(f"{field_name} must be nonnegative")
    return normalized_value


def _require_clean_config_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ConfigurationError(
            f"{field_name} must not have surrounding whitespace"
        )
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ConfigurationError(
            f"{field_name} must not contain control delimiters"
        )
    return value
