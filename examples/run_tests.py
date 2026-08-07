"""Run the current configuration against all supplied local emulators."""

from main import run_demo


def main() -> None:
    measurements = run_demo()
    for ammeter_name, current_a in measurements.items():
        print(f"{ammeter_name}: {current_a:.6f} A")


if __name__ == "__main__":
    main()
