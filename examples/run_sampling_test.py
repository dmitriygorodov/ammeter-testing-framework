"""Run the configured Phase 3 sampling plan over TCP/LAN or USB."""

import argparse

from main import run_sampling_demo
from src.utils.config import DEFAULT_CONFIG_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run configured ammeter sampling over TCP/LAN or USB",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--ammeter", default=None)
    arguments = parser.parse_args()

    for ammeter_name, result in run_sampling_demo(
        arguments.config,
        ammeter_name=arguments.ammeter,
    ).items():
        values = ", ".join(
            f"{measurement.current_a:.6f} A"
            for measurement in result.measurements
        )
        print(
            f"{ammeter_name}: {result.sample_count} samples in "
            f"{result.elapsed_seconds:.3f} s "
            f"({result.stop_reason.value})"
        )
        print(f"  {values}")


if __name__ == "__main__":
    main()
