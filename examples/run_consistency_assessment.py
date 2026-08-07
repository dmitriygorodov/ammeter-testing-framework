"""Assess historical stability from three or more archived runs."""

from __future__ import annotations

import argparse

from main import run_consistency_assessment
from src.testing.reporting import format_historical_consistency_report
from src.utils.config import DEFAULT_CONFIG_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assess like-for-like historical ammeter consistency",
    )
    parser.add_argument(
        "run_ids",
        nargs="+",
        help="Three or more archived run UUIDs",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="YAML configuration used to locate the default archive",
    )
    parser.add_argument(
        "--archive-directory",
        default=None,
        help="Explicit archive directory; bypasses configuration loading",
    )
    arguments = parser.parse_args()
    assessment = run_consistency_assessment(
        arguments.config,
        run_ids=arguments.run_ids,
        archive_directory=arguments.archive_directory,
    )
    print(format_historical_consistency_report(assessment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
