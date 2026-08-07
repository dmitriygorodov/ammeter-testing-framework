"""Pure statistical analysis for completed ammeter sampling runs."""

from __future__ import annotations

import math
from statistics import StatisticsError, mean, median, pstdev

from .errors import ResultAnalysisError
from .models import CurrentStatistics, SamplingRunResult


class ResultAnalyzer:
    """Calculate the required current metrics without altering run evidence.

    Population standard deviation is used because a ``SamplingRunResult`` is
    the complete acquired population being summarized, rather than a sample
    used to infer a larger dataset. Consequently, a one-value run has a
    standard deviation of zero.
    """

    def analyze(self, run: SamplingRunResult) -> CurrentStatistics:
        if not isinstance(run, SamplingRunResult):
            raise TypeError("run must be a SamplingRunResult")
        if not run.samples:
            raise ResultAnalysisError(
                "A sampling run must contain at least one sample for analysis"
            )

        measurements = run.measurements
        mismatched_names = {
            measurement.ammeter_name
            for measurement in measurements
            if measurement.ammeter_name != run.ammeter_name
        }
        if mismatched_names:
            mismatched = ", ".join(sorted(mismatched_names))
            raise ResultAnalysisError(
                "Sampling evidence contains measurements from a different "
                f"ammeter: {mismatched}"
            )

        values = tuple(
            measurement.current_a for measurement in measurements
        )
        try:
            metrics = {
                "mean_current_a": mean(values),
                "median_current_a": _finite_median(values),
                "standard_deviation_current_a": (
                    _population_standard_deviation(values)
                ),
                "minimum_current_a": min(values),
                "maximum_current_a": max(values),
            }
        except (OverflowError, StatisticsError) as exc:
            raise ResultAnalysisError(
                "Current statistics could not be calculated"
            ) from exc

        if not all(math.isfinite(value) for value in metrics.values()):
            raise ResultAnalysisError(
                "Current analysis produced a non-finite statistic"
            )

        return CurrentStatistics(
            ammeter_name=run.ammeter_name,
            sample_count=run.sample_count,
            **metrics,
        )


def _finite_median(values: tuple[float, ...]) -> float:
    """Return the median without overflowing an even pair's midpoint."""

    median_value = median(values)
    if math.isfinite(median_value):
        return median_value

    ordered_values = sorted(values)
    midpoint = len(ordered_values) // 2
    return mean(
        (ordered_values[midpoint - 1], ordered_values[midpoint])
    )


def _population_standard_deviation(values: tuple[float, ...]) -> float:
    """Calculate population deviation without overflow or underflow in squares."""

    scale = max(abs(value) for value in values)
    if scale == 0:
        return 0.0
    exponent = math.frexp(scale)[1]
    normalized_values = tuple(
        math.ldexp(value, -exponent) for value in values
    )
    return math.ldexp(pstdev(normalized_values), exponent)
