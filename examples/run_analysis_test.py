"""Run Phase 4 analysis over a configured TCP/LAN or USB ammeter."""

import argparse

from main import run_analysis_demo
from src.utils.config import DEFAULT_CONFIG_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run configured ammeter analysis over TCP/LAN or USB",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--ammeter", default=None)
    arguments = parser.parse_args()

    for name, analyzed_result in run_analysis_demo(
        arguments.config,
        ammeter_name=arguments.ammeter,
    ).items():
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
