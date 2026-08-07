"""Run Phase 7 configured PASS/FAIL evaluation against local emulators."""

from __future__ import annotations

import argparse

from main import run_acceptance_demo
from src.testing.acceptance_models import VerdictStatus
from src.testing.reporting import format_acceptance_verdict
from src.utils.config import DEFAULT_CONFIG_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run configured ammeter acceptance tests",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="YAML file containing sampling and acceptance configuration",
    )
    parser.add_argument(
        "--ammeter",
        default=None,
        help="Evaluate one configured ammeter; default evaluates all",
    )
    arguments = parser.parse_args()
    results = run_acceptance_demo(
        arguments.config,
        ammeter_name=arguments.ammeter,
    )
    for index, result in enumerate(results.values()):
        if index:
            print()
        print(format_acceptance_verdict(result.verdict))
    return (
        0
        if all(
            result.verdict.status is VerdictStatus.PASS
            for result in results.values()
        )
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
