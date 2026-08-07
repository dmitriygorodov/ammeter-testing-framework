"""Run Phase 4 sampling and statistical analysis on local emulators."""

from main import run_analysis_demo


def main() -> None:
    for name, analyzed_result in run_analysis_demo().items():
        statistics = analyzed_result.statistics
        print(f"{name.upper()} ({statistics.sample_count} samples)")
        print(f"  mean:               {statistics.mean_current_a:.6f} A")
        print(f"  median:             {statistics.median_current_a:.6f} A")
        print(
            "  population std dev: "
            f"{statistics.standard_deviation_current_a:.6f} A"
        )
        print(f"  minimum:            {statistics.minimum_current_a:.6f} A")
        print(f"  maximum:            {statistics.maximum_current_a:.6f} A")


if __name__ == "__main__":
    main()
