"""Run Phase 5 acquisition, analysis, and JSON result archiving."""

import argparse
from uuid import uuid4

from main import run_archive_demo
from src.testing.archive_models import RunMetadata


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire one comparable archive batch from every ammeter",
    )
    parser.add_argument(
        "--comparison-group",
        default=None,
        help=(
            "Stable-stimulus identity shared by this batch; defaults to a "
            "unique demonstration group"
        ),
    )
    arguments = parser.parse_args()
    comparison_group = (
        arguments.comparison_group
        if arguments.comparison_group is not None
        else f"phase5-demo-{uuid4()}"
    )
    metadata = RunMetadata(
        station_id="local-emulator",
        tags=("phase5-demo",),
        attributes=(("comparison_group", comparison_group),),
    )
    print(f"Comparison group: {comparison_group}")
    for name, archived in run_archive_demo(metadata=metadata).items():
        statistics = archived.analyzed_result.statistics
        print(
            f"{name.upper()}: run {archived.run_id} "
            f"({statistics.sample_count} samples, "
            f"mean {statistics.mean_current_a:.6f} A)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
