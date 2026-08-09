from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from src.devices.factory import AmmeterFactory, AmmeterRegistry
from src.devices.models import CurrentMeasurement
from src.utils.config import (
    AcceptanceConfig,
    DEFAULT_CONFIG_PATH,
    SamplingConfig,
    load_application_config,
)

from .acceptance import ResultEvaluator, acceptance_policy_from_config
from .acceptance_models import (
    AcceptancePolicy,
    AcceptanceVerdict,
    EvaluatedSamplingResult,
)
from .analysis import ResultAnalyzer
from .accuracy import AccuracyAssessor
from .accuracy_models import ReferenceAccuracyAssessment, ReferenceCurrent
from .archive import JsonResultArchive
from .archive_models import (
    ArchivedResultSummary,
    ArchivedTestResult,
    HistoricalResultComparison,
    RunMetadata,
)
from .consistency import HistoricalConsistencyAnalyzer
from .consistency_models import HistoricalConsistencyAssessment
from .errors import (
    AcceptancePolicyNotConfiguredError,
    IncomparableAmmeterEvidenceError,
    IncomparableHistoryError,
    ResultArchiveConfigurationError,
    SamplingConfigurationError,
)
from .models import (
    AnalyzedSamplingResult,
    CurrentStatistics,
    SamplingPlan,
    SamplingRunResult,
)
from .sampling import SamplingRunner
from .visualization import ResultVisualizer


class AmmeterTestFramework:
    """Headless facade for one-shot reads and fixed-rate sampling runs."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        *,
        registry: AmmeterRegistry | None = None,
        factory: AmmeterFactory | None = None,
        sampling_plan: SamplingPlan | None = None,
        sampling_runner: SamplingRunner | None = None,
        result_analyzer: ResultAnalyzer | None = None,
        result_archive: JsonResultArchive | None = None,
        accuracy_assessor: AccuracyAssessor | None = None,
        acceptance_policy: AcceptancePolicy | None = None,
        result_evaluator: ResultEvaluator | None = None,
        consistency_analyzer: HistoricalConsistencyAnalyzer | None = None,
        result_visualizer: ResultVisualizer | None = None,
        logger: object | None = None,
    ) -> None:
        self._logger = _validated_logger(logger)
        if sampling_plan is not None and not isinstance(
            sampling_plan,
            SamplingPlan,
        ):
            raise TypeError("sampling_plan must be a SamplingPlan")
        self._default_sampling_plan = sampling_plan
        self._sampling_runner = (
            sampling_runner
            if sampling_runner is not None
            else SamplingRunner()
        )
        if not callable(getattr(self._sampling_runner, "run", None)):
            raise TypeError("sampling_runner must implement run(ammeter, plan)")
        self._result_analyzer = (
            result_analyzer
            if result_analyzer is not None
            else ResultAnalyzer()
        )
        if not callable(getattr(self._result_analyzer, "analyze", None)):
            raise TypeError(
                "result_analyzer must implement analyze(sampling_result)"
            )
        self._accuracy_assessor = (
            accuracy_assessor
            if accuracy_assessor is not None
            else AccuracyAssessor()
        )
        if not callable(getattr(self._accuracy_assessor, "assess", None)):
            raise TypeError(
                "accuracy_assessor must implement assess(results, reference=...)"
            )
        if acceptance_policy is not None and not isinstance(
            acceptance_policy,
            AcceptancePolicy,
        ):
            raise TypeError("acceptance_policy must be AcceptancePolicy")
        self._default_acceptance_policy = acceptance_policy
        self._acceptance_policies_by_ammeter: dict[str, AcceptancePolicy] = {}
        self._result_evaluator = (
            result_evaluator
            if result_evaluator is not None
            else ResultEvaluator()
        )
        if not callable(getattr(self._result_evaluator, "evaluate", None)):
            raise TypeError(
                "result_evaluator must implement "
                "evaluate(result, policy=..., source_run_id=...)"
            )
        self._consistency_analyzer = (
            consistency_analyzer
            if consistency_analyzer is not None
            else HistoricalConsistencyAnalyzer()
        )
        if not callable(getattr(self._consistency_analyzer, "assess", None)):
            raise TypeError(
                "consistency_analyzer must implement assess(results)"
            )
        self._result_visualizer = (
            result_visualizer
            if result_visualizer is not None
            else ResultVisualizer()
        )
        required_visualizer_methods = (
            "plot_run_overview",
            "plot_accuracy_assessment",
            "plot_consistency_assessment",
            "save",
        )
        if any(
            not callable(getattr(self._result_visualizer, method_name, None))
            for method_name in required_visualizer_methods
        ):
            raise TypeError(
                "result_visualizer must implement run, accuracy, consistency, "
                "and save plotting methods"
            )
        self._result_archive = result_archive
        if self._result_archive is not None:
            _validate_result_archive(self._result_archive)

        if registry is not None:
            self._registry = registry
            return

        config = load_application_config(config_path)
        effective_factory = factory if factory is not None else AmmeterFactory()
        self._registry = effective_factory.create_registry(config)
        configured_sampling = getattr(config, "sampling", None)
        if self._default_sampling_plan is None and configured_sampling is not None:
            self._default_sampling_plan = _sampling_plan_from_config(
                configured_sampling
            )
        configured_result_management = getattr(
            config,
            "result_management",
            None,
        )
        if (
            self._result_archive is None
            and configured_result_management is not None
        ):
            self._result_archive = JsonResultArchive(
                configured_result_management.archive_directory
            )
        configured_acceptance = getattr(config, "acceptance", None)
        if (
            self._default_acceptance_policy is None
            and configured_acceptance is not None
        ):
            self._configure_acceptance_policies(configured_acceptance)

    @property
    def available_ammeters(self) -> tuple[str, ...]:
        return self._registry.names

    @property
    def default_sampling_plan(self) -> SamplingPlan | None:
        return self._default_sampling_plan

    @property
    def default_acceptance_policy(self) -> AcceptancePolicy | None:
        return self._default_acceptance_policy

    def measure_once(self, ammeter_name: str) -> CurrentMeasurement:
        """Read one typed current measurement from a configured ammeter."""

        try:
            measurement = self._registry.get(ammeter_name).read_current()
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(
                    f"Single read of {ammeter_name!r} failed: {exc}"
                )
            raise
        if self._logger is not None:
            self._logger.info(
                f"Read {measurement.ammeter_name}: "
                f"{measurement.current_a:.6f} A "
                f"(latency {measurement.latency_seconds * 1e3:.3f} ms)"
            )
        return measurement

    def measure_all_once(self) -> dict[str, CurrentMeasurement]:
        """Read each configured ammeter once, preserving registry order."""

        try:
            measurements = {
                name: self._registry.get(name).read_current()
                for name in self.available_ammeters
            }
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Reading all ammeters failed: {exc}")
            raise
        if self._logger is not None:
            self._logger.info(
                f"Read {len(measurements)} ammeter(s): "
                f"{', '.join(measurements)}"
            )
        return measurements

    def run_test(
        self,
        ammeter_name: str,
        plan: SamplingPlan | None = None,
    ) -> SamplingRunResult:
        """Sample one configured ammeter using an explicit or YAML plan."""

        if plan is not None and not isinstance(plan, SamplingPlan):
            raise TypeError("plan must be a SamplingPlan")
        effective_plan = plan if plan is not None else self._default_sampling_plan
        if effective_plan is None:
            raise SamplingConfigurationError(
                "No sampling plan was provided and no default is configured"
            )
        if self._logger is not None:
            self._logger.info(
                f"Starting sampling run for {ammeter_name!r} "
                f"(frequency={effective_plan.sampling_frequency_hz} Hz, "
                f"count={effective_plan.measurements_count}, "
                f"duration={effective_plan.total_duration_seconds})"
            )
        ammeter = self._registry.get(ammeter_name)
        try:
            result = self._sampling_runner.run(ammeter, effective_plan)
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(
                    f"Sampling run for {ammeter_name!r} failed: {exc}"
                )
            raise
        if self._logger is not None:
            self._logger.info(
                f"Completed sampling run for {result.ammeter_name}: "
                f"{result.sample_count} sample(s), "
                f"elapsed {result.elapsed_seconds:.3f}s, "
                f"stop={result.stop_reason.value}"
            )
        return result

    def analyze_result(
        self,
        sampling_result: SamplingRunResult,
    ) -> CurrentStatistics:
        """Analyze already-acquired evidence without reading the device again."""

        try:
            statistics = self._result_analyzer.analyze(sampling_result)
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Result analysis failed: {exc}")
            raise
        if self._logger is not None:
            self._logger.info(
                f"Analyzed {statistics.ammeter_name}: "
                f"mean={statistics.mean_current_a:.6f} A, "
                f"std={statistics.standard_deviation_current_a:.6f} A, "
                f"min={statistics.minimum_current_a:.6f} A, "
                f"max={statistics.maximum_current_a:.6f} A "
                f"(n={statistics.sample_count})"
            )
        return statistics

    def run_analyzed_test(
        self,
        ammeter_name: str,
        plan: SamplingPlan | None = None,
    ) -> AnalyzedSamplingResult:
        """Acquire one sampling run and return its statistical summary."""

        sampling_result = self.run_test(ammeter_name, plan)
        statistics = self.analyze_result(sampling_result)
        return AnalyzedSamplingResult(
            sampling_result=sampling_result,
            statistics=statistics,
        )

    def evaluate_result(
        self,
        analyzed_result: AnalyzedSamplingResult,
        *,
        policy: AcceptancePolicy | None = None,
    ) -> AcceptanceVerdict:
        """Evaluate existing evidence without acquisition or persistence."""

        if not isinstance(analyzed_result, AnalyzedSamplingResult):
            raise TypeError("analyzed_result must be AnalyzedSamplingResult")
        effective_policy = self._acceptance_policy_for(
            analyzed_result.ammeter_name,
            policy,
        )
        try:
            verdict = self._result_evaluator.evaluate(
                analyzed_result,
                policy=effective_policy,
                source_run_id=None,
            )
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(
                    f"Evaluation of {analyzed_result.ammeter_name} failed: {exc}"
                )
            raise
        if self._logger is not None:
            self._logger.info(
                f"Verdict for {verdict.ammeter_name}: "
                f"{verdict.status.value.upper()} "
                f"({verdict.passed_check_count}/{len(verdict.checks)} "
                f"checks passed) under policy {verdict.policy.identifier}"
            )
        return verdict

    def run_evaluated_test(
        self,
        ammeter_name: str,
        plan: SamplingPlan | None = None,
        *,
        policy: AcceptancePolicy | None = None,
    ) -> EvaluatedSamplingResult:
        """Acquire, analyze, and evaluate one run without hiding evidence."""

        registered_ammeter = self._registry.get(ammeter_name)
        effective_policy = self._acceptance_policy_for(
            registered_ammeter.name,
            policy,
        )
        analyzed_result = self.run_analyzed_test(ammeter_name, plan)
        verdict = self.evaluate_result(
            analyzed_result,
            policy=effective_policy,
        )
        return EvaluatedSamplingResult(
            analyzed_result=analyzed_result,
            verdict=verdict,
        )

    def archive_result(
        self,
        analyzed_result: AnalyzedSamplingResult,
        metadata: RunMetadata | None = None,
    ) -> ArchivedTestResult:
        """Persist already-analyzed evidence without reading a device."""

        return self._save_archived(analyzed_result, metadata)

    def run_archived_test(
        self,
        ammeter_name: str,
        plan: SamplingPlan | None = None,
        *,
        metadata: RunMetadata | None = None,
    ) -> ArchivedTestResult:
        """Acquire, analyze, and persist one successful run in order."""

        result_archive = self._require_result_archive()
        if metadata is not None and not isinstance(metadata, RunMetadata):
            raise TypeError("metadata must be RunMetadata")
        analyzed_result = self.run_analyzed_test(ammeter_name, plan)
        return self._save_archived(analyzed_result, metadata, result_archive)

    def load_archived_result(self, run_id: str) -> ArchivedTestResult:
        return self._require_result_archive().load(run_id)

    def list_archived_results(
        self,
        *,
        ammeter_name: str | None = None,
        test_name: str | None = None,
        tag: str | None = None,
    ) -> tuple[ArchivedResultSummary, ...]:
        return self._require_result_archive().list_results(
            ammeter_name=ammeter_name,
            test_name=test_name,
            tag=tag,
        )

    def compare_archived_results(
        self,
        baseline_run_id: str,
        candidate_run_id: str,
    ) -> HistoricalResultComparison:
        return self._require_result_archive().compare(
            baseline_run_id,
            candidate_run_id,
        )

    def evaluate_archived_result(
        self,
        run_id: str,
        *,
        policy: AcceptancePolicy | None = None,
    ) -> AcceptanceVerdict:
        """Load one archived run and derive a traceable Phase 7 verdict."""

        archived = self._require_result_archive().load(run_id)
        effective_policy = self._acceptance_policy_for(
            archived.ammeter_name,
            policy,
        )
        return self._result_evaluator.evaluate(
            archived.analyzed_result,
            policy=effective_policy,
            source_run_id=archived.run_id,
        )

    def assess_accuracy(
        self,
        archived_results: Iterable[ArchivedTestResult],
        *,
        reference: ReferenceCurrent,
    ) -> ReferenceAccuracyAssessment:
        """Assess already-loaded runs without acquiring or persisting data."""

        return self._accuracy_assessor.assess(
            archived_results,
            reference=reference,
        )

    def assess_archived_accuracy(
        self,
        run_ids: Iterable[str],
        *,
        reference: ReferenceCurrent,
    ) -> ReferenceAccuracyAssessment:
        """Load a compatible cohort by ID and perform Phase 6 assessment."""

        result_archive = self._require_result_archive()
        if not isinstance(reference, ReferenceCurrent):
            raise TypeError("reference must be ReferenceCurrent")
        if isinstance(run_ids, (str, bytes)):
            raise TypeError("run_ids must be an iterable of run ID strings")
        try:
            requested_ids = tuple(run_ids)
        except TypeError as exc:
            raise TypeError(
                "run_ids must be an iterable of run ID strings"
            ) from exc
        if len(requested_ids) < 2:
            raise IncomparableAmmeterEvidenceError(
                "Accuracy assessment requires at least two archived run IDs"
            )
        try:
            archived_results = tuple(
                result_archive.load(run_id) for run_id in requested_ids
            )
            assessment = self.assess_accuracy(
                archived_results,
                reference=reference,
            )
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(
                    f"Accuracy assessment of {len(requested_ids)} run(s) "
                    f"failed: {exc}"
                )
            raise
        if self._logger is not None:
            self._logger.info(
                f"Completed accuracy assessment across "
                f"{len(requested_ids)} archived run(s)"
            )
        return assessment

    def assess_consistency(
        self,
        archived_results: Iterable[ArchivedTestResult],
    ) -> HistoricalConsistencyAssessment:
        """Assess already-loaded history without acquisition or persistence."""

        return self._consistency_analyzer.assess(archived_results)

    def assess_archived_consistency(
        self,
        run_ids: Iterable[str],
    ) -> HistoricalConsistencyAssessment:
        """Load a compatible historical series by ID and assess its stability."""

        result_archive = self._require_result_archive()
        if isinstance(run_ids, (str, bytes)):
            raise TypeError("run_ids must be an iterable of run ID strings")
        try:
            requested_ids = tuple(run_ids)
        except TypeError as exc:
            raise TypeError(
                "run_ids must be an iterable of run ID strings"
            ) from exc
        if len(requested_ids) < 3:
            raise IncomparableHistoryError(
                "Historical consistency requires at least three run IDs"
            )
        if not all(isinstance(run_id, str) for run_id in requested_ids):
            raise TypeError("run_ids must contain only strings")
        if len(set(requested_ids)) != len(requested_ids):
            raise IncomparableHistoryError(
                "Historical consistency run IDs must be unique"
            )
        try:
            archived_results = tuple(
                result_archive.load(run_id) for run_id in requested_ids
            )
            assessment = self.assess_consistency(archived_results)
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(
                    f"Consistency assessment of {len(requested_ids)} run(s) "
                    f"failed: {exc}"
                )
            raise
        if self._logger is not None:
            self._logger.info(
                f"Completed consistency assessment across "
                f"{len(requested_ids)} archived run(s)"
            )
        return assessment

    def visualize_result(
        self,
        analyzed_result: AnalyzedSamplingResult,
        *,
        verdict: AcceptanceVerdict | None = None,
    ) -> object:
        """Create a run overview without acquiring or modifying evidence."""

        return self._result_visualizer.plot_run_overview(
            analyzed_result,
            verdict=verdict,
        )

    def visualize_accuracy(
        self,
        assessment: ReferenceAccuracyAssessment,
    ) -> object:
        return self._result_visualizer.plot_accuracy_assessment(assessment)

    def visualize_consistency(
        self,
        assessment: HistoricalConsistencyAssessment,
    ) -> object:
        return self._result_visualizer.plot_consistency_assessment(assessment)

    def save_visualization(
        self,
        figure: object,
        output_path: str | Path,
        *,
        dpi: int = 160,
    ) -> Path:
        try:
            saved_path = self._result_visualizer.save(
                figure,
                output_path,
                dpi=dpi,
            )
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Saving visualization failed: {exc}")
            raise
        if self._logger is not None:
            self._logger.info(f"Saved visualization to {saved_path}")
        return saved_path

    def _save_archived(
        self,
        analyzed_result: AnalyzedSamplingResult,
        metadata: RunMetadata | None,
        result_archive: JsonResultArchive | None = None,
    ) -> ArchivedTestResult:
        archive = (
            result_archive
            if result_archive is not None
            else self._require_result_archive()
        )
        try:
            archived = archive.save(analyzed_result, metadata)
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(
                    f"Archiving {analyzed_result.ammeter_name} failed: {exc}"
                )
            raise
        if self._logger is not None:
            self._logger.info(
                f"Archived run {archived.run_id} for {archived.ammeter_name}"
            )
        return archived

    def _require_result_archive(self) -> JsonResultArchive:
        if self._result_archive is None:
            raise ResultArchiveConfigurationError(
                "No result archive was injected or configured"
            )
        return self._result_archive

    def _acceptance_policy_for(
        self,
        ammeter_name: str,
        explicit_policy: AcceptancePolicy | None,
    ) -> AcceptancePolicy:
        if explicit_policy is not None:
            if not isinstance(explicit_policy, AcceptancePolicy):
                raise TypeError("policy must be AcceptancePolicy")
            return explicit_policy
        configured = self._acceptance_policies_by_ammeter.get(
            ammeter_name.casefold()
        )
        if configured is not None:
            return configured
        if self._default_acceptance_policy is not None:
            return self._default_acceptance_policy
        raise AcceptancePolicyNotConfiguredError(
            f"No acceptance policy is configured for {ammeter_name!r}"
        )

    def _configure_acceptance_policies(
        self,
        config: AcceptanceConfig,
    ) -> None:
        if config.default_policy is not None:
            self._default_acceptance_policy = acceptance_policy_from_config(
                config.default_policy
            )
        self._acceptance_policies_by_ammeter = {
            name: acceptance_policy_from_config(policy)
            for name, policy in config.ammeter_policies
        }


def _sampling_plan_from_config(config: SamplingConfig) -> SamplingPlan:
    return SamplingPlan(
        sampling_frequency_hz=config.sampling_frequency_hz,
        measurements_count=config.measurements_count,
        total_duration_seconds=config.total_duration_seconds,
    )


def _validated_logger(logger: object | None) -> object | None:
    if logger is None:
        return None
    required_methods = ("info", "error", "debug", "warning")
    if any(
        not callable(getattr(logger, method_name, None))
        for method_name in required_methods
    ):
        raise TypeError(
            "logger must implement info, error, debug, and warning"
        )
    return logger


def _validate_result_archive(result_archive: object) -> None:
    required_methods = ("save", "load", "list_results", "compare")
    missing = [
        method_name
        for method_name in required_methods
        if not callable(getattr(result_archive, method_name, None))
    ]
    if missing:
        raise TypeError(
            "result_archive must implement save, load, list_results, and compare"
        )
