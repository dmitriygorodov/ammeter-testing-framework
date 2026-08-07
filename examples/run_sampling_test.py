"""Run the configured Phase 3 sampling plan on the local emulators."""

from main import run_sampling_demo


def main() -> None:
    for ammeter_name, result in run_sampling_demo().items():
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
