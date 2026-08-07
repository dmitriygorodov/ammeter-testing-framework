"""Test execution and result-analysis services for the ammeter framework."""

from .acceptance import ResultEvaluator, acceptance_policy_from_config
from .acceptance_models import (
    AcceptanceCheck,
    AcceptanceLimits,
    AcceptanceMetric,
    AcceptancePolicy,
    AcceptanceVerdict,
    EvaluatedSamplingResult,
    LimitComparison,
    VerdictStatus,
)
from .analysis import ResultAnalyzer
from .accuracy import (
    AccuracyAssessor,
    COMPARISON_GROUP_ATTRIBUTE,
    UNGROUPED_EXPLICIT_SELECTION,
)
from .accuracy_models import (
    AmmeterAccuracyMetrics,
    PairwiseAmmeterAgreement,
    ReferenceAccuracyAssessment,
    ReferenceCurrent,
)
from .archive import JsonResultArchive
from .archive_models import (
    ArchivedResultSummary,
    ArchivedTestResult,
    HistoricalResultComparison,
    RunMetadata,
    RunStatus,
)
from .consistency import CONSISTENCY_GROUP_ATTRIBUTE, HistoricalConsistencyAnalyzer
from .consistency_models import (
    ConsistencyRunPoint,
    HistoricalConsistencyAssessment,
    HistoricalConsistencyMetrics,
)
from .errors import (
    AcceptanceEvaluationError,
    AcceptancePolicyNotConfiguredError,
    AccuracyAssessmentError,
    ArchivedResultNotFoundError,
    ConsistencyAnalysisError,
    DuplicateRunIdError,
    InvalidRunIdError,
    IncomparableAmmeterEvidenceError,
    IncomparableHistoryError,
    ResultAnalysisError,
    ResultArchiveConfigurationError,
    ResultArchiveCorruptionError,
    ResultArchiveError,
    ResultComparisonError,
    SamplingConfigurationError,
    VisualizationDependencyError,
    VisualizationError,
    VisualizationOutputError,
)
from .models import (
    AnalyzedSamplingResult,
    CurrentStatistics,
    SampledMeasurement,
    SamplingPlan,
    SamplingRunResult,
    SamplingStopReason,
)
from .sampling import SamplingRunner
from .test_framework import AmmeterTestFramework
from .visualization import ResultVisualizer
from .reporting import (
    format_acceptance_verdict,
    format_historical_consistency_report,
    format_reference_accuracy_report,
)

__all__ = [
    "AnalyzedSamplingResult",
    "AcceptanceCheck",
    "AcceptanceEvaluationError",
    "AcceptanceLimits",
    "AcceptanceMetric",
    "AcceptancePolicy",
    "AcceptancePolicyNotConfiguredError",
    "AcceptanceVerdict",
    "AccuracyAssessmentError",
    "AccuracyAssessor",
    "AmmeterAccuracyMetrics",
    "AmmeterTestFramework",
    "ArchivedResultNotFoundError",
    "ArchivedResultSummary",
    "ArchivedTestResult",
    "COMPARISON_GROUP_ATTRIBUTE",
    "CONSISTENCY_GROUP_ATTRIBUTE",
    "ConsistencyAnalysisError",
    "ConsistencyRunPoint",
    "CurrentStatistics",
    "DuplicateRunIdError",
    "EvaluatedSamplingResult",
    "HistoricalResultComparison",
    "HistoricalConsistencyAnalyzer",
    "HistoricalConsistencyAssessment",
    "HistoricalConsistencyMetrics",
    "InvalidRunIdError",
    "IncomparableAmmeterEvidenceError",
    "IncomparableHistoryError",
    "JsonResultArchive",
    "LimitComparison",
    "PairwiseAmmeterAgreement",
    "ReferenceAccuracyAssessment",
    "ReferenceCurrent",
    "ResultAnalysisError",
    "ResultArchiveConfigurationError",
    "ResultArchiveCorruptionError",
    "ResultArchiveError",
    "ResultAnalyzer",
    "ResultEvaluator",
    "ResultVisualizer",
    "ResultComparisonError",
    "RunMetadata",
    "RunStatus",
    "SampledMeasurement",
    "SamplingConfigurationError",
    "SamplingPlan",
    "SamplingRunResult",
    "SamplingRunner",
    "SamplingStopReason",
    "UNGROUPED_EXPLICIT_SELECTION",
    "VerdictStatus",
    "VisualizationDependencyError",
    "VisualizationError",
    "VisualizationOutputError",
    "acceptance_policy_from_config",
    "format_acceptance_verdict",
    "format_historical_consistency_report",
    "format_reference_accuracy_report",
]
