class SamplingConfigurationError(ValueError):
    """A sampling plan is missing or cannot terminate safely."""


class ResultAnalysisError(ValueError):
    """A completed sampling result cannot be analyzed safely."""


class ResultArchiveError(RuntimeError):
    """Base class for persistent result-management failures."""


class ResultArchiveConfigurationError(ResultArchiveError):
    """The result archive is missing or cannot be initialized safely."""


class InvalidRunIdError(ResultArchiveError):
    """A requested run identifier is not a canonical UUID."""


class ArchivedResultNotFoundError(ResultArchiveError):
    """No archived result exists for a valid run identifier."""


class ResultArchiveCorruptionError(ResultArchiveError):
    """An archive document is malformed, unsupported, or inconsistent."""


class DuplicateRunIdError(ResultArchiveError):
    """A generated run identifier already exists in the archive."""


class ResultComparisonError(ResultArchiveError):
    """Two archived runs cannot be compared under the Phase 5 contract."""


class AccuracyAssessmentError(ValueError):
    """Reference-based accuracy metrics cannot be calculated safely."""


class IncomparableAmmeterEvidenceError(AccuracyAssessmentError):
    """Archived runs do not describe one like-for-like assessment cohort."""


class AcceptanceEvaluationError(ValueError):
    """Valid PASS/FAIL evaluation cannot be completed safely."""


class AcceptancePolicyNotConfiguredError(AcceptanceEvaluationError):
    """No explicit acceptance policy applies to the requested ammeter."""


class ConsistencyAnalysisError(ValueError):
    """Historical performance consistency cannot be calculated safely."""


class IncomparableHistoryError(ConsistencyAnalysisError):
    """Archived runs do not form one like-for-like historical series."""


class VisualizationError(RuntimeError):
    """A requested testing visualization cannot be produced safely."""


class VisualizationDependencyError(VisualizationError):
    """The optional plotting runtime is unavailable."""


class VisualizationOutputError(VisualizationError):
    """A visualization output path or write operation is invalid."""
