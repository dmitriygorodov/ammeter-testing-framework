"""Render run, accuracy, or consistency plots from archived evidence."""

from __future__ import annotations

import argparse

from main import render_archived_visualization
from src.testing.accuracy_models import ReferenceCurrent
from src.utils.config import DEFAULT_CONFIG_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a headless Phase 9 plot from archived results",
    )
    parser.add_argument(
        "plot_type",
        choices=("run_overview", "accuracy", "consistency"),
    )
    parser.add_argument("run_ids", nargs="+", help="Archived run UUIDs")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="YAML configuration for archive and optional plot defaults",
    )
    parser.add_argument(
        "--archive-directory",
        default=None,
        help="Explicit archive directory override",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output .png, .svg, or .pdf; otherwise use enabled config",
    )
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--reference-current-a", type=float, default=None)
    parser.add_argument("--reference-source", default=None)
    parser.add_argument("--expanded-uncertainty-a", type=float, default=None)
    parser.add_argument("--calibration-id", default=None)
    arguments = parser.parse_args()

    reference = None
    reference_fields = (
        arguments.reference_current_a,
        arguments.reference_source,
        arguments.expanded_uncertainty_a,
        arguments.calibration_id,
    )
    if arguments.plot_type == "accuracy":
        if arguments.reference_current_a is None or arguments.reference_source is None:
            parser.error(
                "accuracy requires --reference-current-a and --reference-source"
            )
        reference = ReferenceCurrent(
            current_a=arguments.reference_current_a,
            source=arguments.reference_source,
            expanded_uncertainty_a=arguments.expanded_uncertainty_a,
            calibration_id=arguments.calibration_id,
        )
    elif any(value is not None for value in reference_fields):
        parser.error("reference options are valid only for accuracy")

    output = render_archived_visualization(
        arguments.config,
        plot_type=arguments.plot_type,
        run_ids=arguments.run_ids,
        output_path=arguments.output,
        archive_directory=arguments.archive_directory,
        reference=reference,
        dpi=arguments.dpi,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
