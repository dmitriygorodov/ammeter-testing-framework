"""Headless, object-oriented Matplotlib visualizations for Phase 9."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .acceptance import ResultEvaluator
from .acceptance_models import AcceptanceVerdict
from .accuracy_models import ReferenceAccuracyAssessment
from .archive_codec import validate_analyzed_result_semantics
from .consistency_models import HistoricalConsistencyAssessment
from .errors import (
    AcceptanceEvaluationError,
    ResultArchiveCorruptionError,
    VisualizationDependencyError,
    VisualizationError,
    VisualizationOutputError,
)
from .models import AnalyzedSamplingResult


try:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
except (ImportError, ModuleNotFoundError) as exc:  # Lazy typed failure on use.
    FigureCanvasAgg = None  # type: ignore[assignment,misc]
    Figure = None  # type: ignore[assignment,misc]
    _MATPLOTLIB_IMPORT_ERROR: BaseException | None = exc
else:
    _MATPLOTLIB_IMPORT_ERROR = None


_BLUE = "#0072B2"
_ORANGE = "#E69F00"
_GREEN = "#009E73"
_VERMILLION = "#D55E00"
_PURPLE = "#CC79A7"
_GRAY = "#666666"
_LIGHT_GRAY = "#D8D8D8"
_SUPPORTED_FORMATS = {"png", "svg", "pdf"}


class ResultVisualizer:
    """Create deterministic figures without pyplot or a display server."""

    def plot_run_overview(
        self,
        result: AnalyzedSamplingResult,
        *,
        verdict: AcceptanceVerdict | None = None,
    ) -> Any:
        """Plot current time series, distribution, and recorded timing."""

        _require_matplotlib()
        if not isinstance(result, AnalyzedSamplingResult):
            raise TypeError("result must be AnalyzedSamplingResult")
        _validate_analyzed_result(result)
        if verdict is not None:
            _validate_verdict_projection(result, verdict)

        figure = _new_figure(width=10.5, height=7.5)
        grid = figure.add_gridspec(2, 2, height_ratios=(2.0, 1.15))
        series_axis = figure.add_subplot(grid[0, :])
        histogram_axis = figure.add_subplot(grid[1, 0])
        timing_axis = figure.add_subplot(grid[1, 1])
        samples = result.sampling_result.samples
        statistics = result.statistics
        elapsed = [sample.started_offset_seconds for sample in samples]
        currents = [sample.measurement.current_a for sample in samples]
        indexes = [sample.sample_index for sample in samples]

        series_axis.plot(
            elapsed,
            currents,
            color=_BLUE,
            marker="o",
            markersize=4.5,
            linewidth=1.6,
            label="Measured current",
        )
        series_axis.axhline(
            statistics.mean_current_a,
            color=_ORANGE,
            linewidth=1.4,
            linestyle="--",
            label=f"Mean {_number(statistics.mean_current_a)} A",
        )
        series_axis.axhline(
            statistics.median_current_a,
            color=_PURPLE,
            linewidth=1.2,
            linestyle=":",
            label=f"Median {_number(statistics.median_current_a)} A",
        )
        _add_acceptance_current_overlays(series_axis, verdict)
        series_axis.set_title(f"Current over time - {result.ammeter_name}")
        series_axis.set_xlabel("Elapsed time at acquisition start (s)")
        series_axis.set_ylabel("Current (A)")
        series_axis.grid(True, color=_LIGHT_GRAY, linewidth=0.7, alpha=0.7)
        series_axis.legend(loc="best", fontsize=8)

        bin_count = max(1, min(20, math.ceil(math.sqrt(len(currents)))))
        histogram_axis.hist(
            currents,
            bins=bin_count,
            color=_BLUE,
            edgecolor="white",
            alpha=0.82,
        )
        histogram_axis.axvline(
            statistics.mean_current_a,
            color=_ORANGE,
            linewidth=1.4,
            linestyle="--",
            label="Mean",
        )
        histogram_axis.axvline(
            statistics.median_current_a,
            color=_PURPLE,
            linewidth=1.2,
            linestyle=":",
            label="Median",
        )
        histogram_axis.set_title("Current distribution")
        histogram_axis.set_xlabel("Current (A)")
        histogram_axis.set_ylabel("Samples")
        histogram_axis.grid(True, axis="y", color=_LIGHT_GRAY, alpha=0.7)
        histogram_axis.legend(loc="best", fontsize=8)

        lateness = [sample.start_lateness_seconds for sample in samples]
        acquisition = [sample.acquisition_duration_seconds for sample in samples]
        timing_axis.plot(
            indexes,
            lateness,
            color=_GREEN,
            marker="o",
            markersize=4,
            linewidth=1.4,
            label="Start lateness",
        )
        timing_axis.plot(
            indexes,
            acquisition,
            color=_VERMILLION,
            marker="s",
            markersize=4,
            linewidth=1.4,
            label="Acquisition duration",
        )
        _add_acceptance_timing_overlays(timing_axis, verdict)
        timing_axis.set_title("Sampling timing")
        timing_axis.set_xlabel("Sample index")
        timing_axis.set_ylabel("Seconds")
        timing_axis.grid(True, color=_LIGHT_GRAY, linewidth=0.7, alpha=0.7)
        timing_axis.legend(loc="best", fontsize=8)
        figure.suptitle("Ammeter run overview", fontsize=14, fontweight="semibold")
        return figure

    def plot_accuracy_assessment(
        self,
        assessment: ReferenceAccuracyAssessment,
    ) -> Any:
        """Plot reference means, precision, absolute error, and RMSE."""

        _require_matplotlib()
        if not isinstance(assessment, ReferenceAccuracyAssessment):
            raise TypeError("assessment must be ReferenceAccuracyAssessment")
        figure = _new_figure(width=10.5, height=7.2)
        grid = figure.add_gridspec(2, 1, height_ratios=(1.4, 1.0))
        mean_axis = figure.add_subplot(grid[0, 0])
        error_axis = figure.add_subplot(grid[1, 0])
        names = [item.ammeter_name for item in assessment.ammeters]
        positions = list(range(len(names)))
        means = [item.mean_current_a for item in assessment.ammeters]
        deviations = [
            item.standard_deviation_current_a for item in assessment.ammeters
        ]

        mean_axis.errorbar(
            positions,
            means,
            yerr=deviations,
            fmt="o",
            color=_BLUE,
            ecolor=_BLUE,
            capsize=5,
            markersize=7,
            linewidth=1.5,
            label="Mean +/- population std dev",
        )
        reference = assessment.reference.current_a
        mean_axis.axhline(
            reference,
            color=_ORANGE,
            linestyle="--",
            linewidth=1.5,
            label=f"Reference {_number(reference)} A",
        )
        uncertainty = assessment.reference.expanded_uncertainty_a
        if uncertainty is not None:
            lower = reference - uncertainty
            upper = reference + uncertainty
            if not math.isfinite(lower) or not math.isfinite(upper):
                raise VisualizationError(
                    "Reference uncertainty band is outside finite range"
                )
            mean_axis.axhspan(
                lower,
                upper,
                color=_ORANGE,
                alpha=0.14,
                label="Reference expanded uncertainty",
            )
        mean_axis.set_xticks(positions, names)
        mean_axis.set_ylabel("Current (A)")
        mean_axis.set_title("Measured means against reference")
        mean_axis.grid(True, axis="y", color=_LIGHT_GRAY, alpha=0.7)
        mean_axis.legend(loc="best", fontsize=8)

        bar_width = 0.36
        absolute_errors = [item.absolute_error_a for item in assessment.ammeters]
        rmse_values = [
            item.root_mean_square_error_a for item in assessment.ammeters
        ]
        left_positions = [position - bar_width / 2 for position in positions]
        right_positions = [position + bar_width / 2 for position in positions]
        error_axis.bar(
            left_positions,
            absolute_errors,
            width=bar_width,
            color=_GREEN,
            label="Absolute mean error",
        )
        error_axis.bar(
            right_positions,
            rmse_values,
            width=bar_width,
            color=_VERMILLION,
            label="Reference RMSE",
        )
        error_axis.set_xticks(positions, names)
        error_axis.set_ylabel("Error (A)")
        error_axis.set_title("Accuracy and reference fidelity")
        error_axis.grid(True, axis="y", color=_LIGHT_GRAY, alpha=0.7)
        error_axis.legend(loc="best", fontsize=8)
        figure.suptitle(
            f"Cross-ammeter accuracy - {assessment.comparison_group}",
            fontsize=14,
            fontweight="semibold",
        )
        return figure

    def plot_consistency_assessment(
        self,
        assessment: HistoricalConsistencyAssessment,
    ) -> Any:
        """Plot historical run means, fitted drift, and within-run precision."""

        _require_matplotlib()
        if not isinstance(assessment, HistoricalConsistencyAssessment):
            raise TypeError("assessment must be HistoricalConsistencyAssessment")
        figure = _new_figure(width=10.5, height=7.2)
        grid = figure.add_gridspec(2, 1, height_ratios=(1.55, 1.0))
        trend_axis = figure.add_subplot(grid[0, 0])
        precision_axis = figure.add_subplot(grid[1, 0])
        hours = [
            run.elapsed_since_first_seconds / 3600.0 for run in assessment.runs
        ]
        means = [run.statistics.mean_current_a for run in assessment.runs]
        within_deviations = [
            run.statistics.standard_deviation_current_a
            for run in assessment.runs
        ]
        trend_axis.errorbar(
            hours,
            means,
            yerr=within_deviations,
            fmt="o-",
            color=_BLUE,
            ecolor=_BLUE,
            capsize=4,
            markersize=6,
            linewidth=1.5,
            label="Run mean +/- within-run std dev",
        )
        x_mean = sum(hours) / len(hours)
        y_mean = assessment.metrics.mean_of_run_means_a
        slope = assessment.metrics.trend_slope_a_per_hour
        fitted = []
        for hour in hours:
            value = y_mean + slope * (hour - x_mean)
            if not math.isfinite(value):
                raise VisualizationError("Fitted trend is outside finite range")
            fitted.append(value)
        trend_axis.plot(
            hours,
            fitted,
            color=_ORANGE,
            linestyle="--",
            linewidth=1.6,
            label=f"OLS trend {_number(slope)} A/hour",
        )
        trend_axis.set_title("Run means and fitted drift")
        trend_axis.set_xlabel("Elapsed time since first run (hours)")
        trend_axis.set_ylabel("Current (A)")
        if len(hours) <= 8:
            trend_axis.set_xticks(hours, [_number(hour) for hour in hours])
        trend_axis.grid(True, color=_LIGHT_GRAY, alpha=0.7)
        trend_axis.legend(loc="best", fontsize=8)

        positions = list(range(len(assessment.runs)))
        precision_axis.bar(
            positions,
            within_deviations,
            color=_GREEN,
            label="Within-run population std dev",
        )
        precision_axis.axhline(
            assessment.metrics.pooled_within_run_standard_deviation_a,
            color=_VERMILLION,
            linestyle="--",
            linewidth=1.4,
            label=(
                "Pooled std dev "
                f"{_number(assessment.metrics.pooled_within_run_standard_deviation_a)} A"
            ),
        )
        precision_axis.set_xticks(
            positions,
            [f"Run {index + 1}" for index in positions],
        )
        precision_axis.set_ylabel("Standard deviation (A)")
        precision_axis.set_title("Within-run repeatability")
        precision_axis.grid(True, axis="y", color=_LIGHT_GRAY, alpha=0.7)
        precision_axis.legend(loc="best", fontsize=8)
        figure.suptitle(
            f"Historical consistency - {assessment.consistency_group}",
            fontsize=14,
            fontweight="semibold",
        )
        return figure

    def save(
        self,
        figure: Any,
        output_path: str | Path,
        *,
        dpi: int = 160,
    ) -> Path:
        """Save one figure without overwriting an existing file."""

        _require_matplotlib()
        if not isinstance(figure, Figure):
            raise TypeError("figure must be a matplotlib Figure")
        if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 600:
            raise VisualizationOutputError("dpi must be an integer from 72 to 600")
        try:
            path = Path(output_path).expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise VisualizationOutputError("output_path is invalid") from exc
        image_format = path.suffix.casefold().lstrip(".")
        if image_format not in _SUPPORTED_FORMATS:
            supported = ", ".join(sorted(_SUPPORTED_FORMATS))
            raise VisualizationOutputError(
                f"Visualization output must use one of: {supported}"
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output_file:
                try:
                    figure.savefig(
                        output_file,
                        format=image_format,
                        dpi=dpi,
                        bbox_inches="tight",
                        facecolor="white",
                    )
                except Exception:
                    output_file.close()
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    raise
        except FileExistsError as exc:
            raise VisualizationOutputError(
                f"Visualization output already exists: {path}"
            ) from exc
        except Exception as exc:
            raise VisualizationOutputError(
                f"Could not save visualization to {path}"
            ) from exc
        return path


def _new_figure(*, width: float, height: float) -> Any:
    figure = Figure(
        figsize=(width, height),
        dpi=100,
        constrained_layout=True,
        facecolor="white",
    )
    FigureCanvasAgg(figure)
    return figure


def _validate_analyzed_result(result: AnalyzedSamplingResult) -> None:
    try:
        validate_analyzed_result_semantics(result)
    except ResultArchiveCorruptionError as exc:
        raise VisualizationError(
            "Analyzed statistics do not match the sampling evidence"
        ) from exc


def _validate_verdict_projection(
    result: AnalyzedSamplingResult,
    verdict: AcceptanceVerdict,
) -> None:
    if not isinstance(verdict, AcceptanceVerdict):
        raise TypeError("verdict must be AcceptanceVerdict or None")
    try:
        expected = ResultEvaluator().evaluate(result, policy=verdict.policy)
    except AcceptanceEvaluationError as exc:
        raise VisualizationError("Verdict evidence cannot be validated") from exc
    if (
        verdict.ammeter_name != expected.ammeter_name
        or verdict.sample_count != expected.sample_count
        or verdict.checks != expected.checks
    ):
        raise VisualizationError("verdict does not match the analyzed evidence")


def _add_acceptance_current_overlays(axis: Any, verdict: AcceptanceVerdict | None) -> None:
    if verdict is None:
        return
    limits = verdict.policy.limits
    lower = limits.minimum_current_a
    upper = limits.maximum_current_a
    if lower is not None and upper is not None:
        axis.axhspan(
            lower,
            upper,
            color=_GREEN,
            alpha=0.11,
            label="Configured current range",
        )
    elif lower is not None:
        axis.axhline(
            lower,
            color=_GREEN,
            linestyle="-.",
            linewidth=1.2,
            label=f"Minimum {_number(lower)} A",
        )
    elif upper is not None:
        axis.axhline(
            upper,
            color=_GREEN,
            linestyle="-.",
            linewidth=1.2,
            label=f"Maximum {_number(upper)} A",
        )
    reference = verdict.policy.reference
    if reference is not None:
        axis.axhline(
            reference.current_a,
            color=_GRAY,
            linestyle="-.",
            linewidth=1.2,
            label=f"Reference {_number(reference.current_a)} A",
        )
        half_widths: list[float] = []
        if limits.maximum_absolute_bias_a is not None:
            half_widths.append(limits.maximum_absolute_bias_a)
        if limits.maximum_relative_error_percent is not None:
            half_widths.append(
                abs(reference.current_a)
                * limits.maximum_relative_error_percent
                / 100.0
            )
        if half_widths:
            half_width = min(half_widths)
            tolerance_lower = reference.current_a - half_width
            tolerance_upper = reference.current_a + half_width
            if not math.isfinite(tolerance_lower) or not math.isfinite(
                tolerance_upper
            ):
                raise VisualizationError(
                    "Reference tolerance band is outside finite range"
                )
            axis.axhspan(
                tolerance_lower,
                tolerance_upper,
                color=_ORANGE,
                alpha=0.12,
                label="Reference mean tolerance",
            )


def _add_acceptance_timing_overlays(axis: Any, verdict: AcceptanceVerdict | None) -> None:
    if verdict is None:
        return
    limits = verdict.policy.limits
    if limits.maximum_start_lateness_seconds is not None:
        axis.axhline(
            limits.maximum_start_lateness_seconds,
            color=_GREEN,
            linestyle="--",
            linewidth=1.1,
            label="Lateness limit",
        )
    if limits.maximum_acquisition_duration_seconds is not None:
        axis.axhline(
            limits.maximum_acquisition_duration_seconds,
            color=_VERMILLION,
            linestyle="--",
            linewidth=1.1,
            label="Acquisition limit",
        )


def _require_matplotlib() -> None:
    if Figure is None or FigureCanvasAgg is None:
        raise VisualizationDependencyError(
            "Matplotlib is required for Phase 9 visualizations. Install "
            "project dependencies with 'python -m pip install -r requirements.txt'."
        ) from _MATPLOTLIB_IMPORT_ERROR


def _number(value: float) -> str:
    return f"{value:.6g}"
