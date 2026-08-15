"""Command line for comparing consecutive OVTLYR universe exports."""

from __future__ import annotations

import argparse
import json

from .ovtlyr import compare_universes, load_ovtlyr_csv, summarize_sector_rotation
from .ovtlyr_report import write_comparison_outputs


def main() -> None:
    parser = argparse.ArgumentParser(prog="daily-alpha-compare")
    parser.add_argument("previous_csv")
    parser.add_argument("current_csv")
    parser.add_argument("--output-dir", default="data/output")
    args = parser.parse_args()

    previous = load_ovtlyr_csv(args.previous_csv)
    current = load_ovtlyr_csv(args.current_csv)
    classified = compare_universes(previous, current)
    sectors = summarize_sector_rotation(classified)
    paths = write_comparison_outputs(args.output_dir, classified, sectors)

    counts: dict[str, int] = {}
    for item in classified:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    print(
        json.dumps(
            {
                "status_counts": counts,
                "non_optionable": sum(item.optionable is False for item in classified),
                "optionability_unknown": sum(item.optionable is None for item in classified),
                "outputs": {name: str(path) for name, path in paths.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
