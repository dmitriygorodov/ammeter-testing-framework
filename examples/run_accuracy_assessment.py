"""Assess archived ammeter runs against an explicitly supplied reference."""

from __future__ import annotations

import argparse

from main import run_accuracy_assessment
from src.testing.accuracy_models import ReferenceCurrent
from src.testing.reporting import format_reference_accuracy_report
from src.utils.config import DEFAULT_CONFIG_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare compatible archived ammeter runs with a known current "
            "reference. Every run must share comparison_group metadata."
        )
    )
    parser.add_argument("run_ids", nargs="+", help="Two or more archived UUIDs")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="YAML configuration path used to locate the default archive",
    )
    parser.add_argument(
        "--archive-directory",
        default=None,
        help="Optional archive directory override",
    )
    parser.add_argument(
        "--reference-current-a",
        type=float,
        required=True,
        help="Known reference current in amperes",
    )
    parser.add_argument(
        "--reference-source",
        required=True,
        help="Human-readable source or setpoint identifier",
    )
    parser.add_argument(
        "--expanded-uncertainty-a",
        type=float,
        default=None,
        help="Optional expanded uncertainty in amperes",
    )
    parser.add_argument(
        "--calibration-id",
        default=None,
        help="Optional calibration certificate or asset identifier",
    )
    arguments = parser.parse_args()

    assessment = run_accuracy_assessment(
        arguments.config,
        run_ids=arguments.run_ids,
        reference=ReferenceCurrent(
            current_a=arguments.reference_current_a,
            source=arguments.reference_source,
            expanded_uncertainty_a=arguments.expanded_uncertainty_a,
            calibration_id=arguments.calibration_id,
        ),
        archive_directory=arguments.archive_directory,
    )
    print(format_reference_accuracy_report(assessment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
