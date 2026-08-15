"""Command line for comparing and archiving consecutive OVTLYR exports."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from .ovtlyr import compare_universes, load_ovtlyr_csv, summarize_sector_rotation
from .ovtlyr_report import archive_daily_run


def main() -> None:
    parser = argparse.ArgumentParser(prog="daily-alpha-compare")
    parser.add_argument("previous_csv")
    parser.add_argument("current_csv")
    parser.add_argument(
        "--run-date",
        default=datetime.now(UTC).date().isoformat(),
        help="Archive date in YYYY-MM-DD format",
    )
    parser.add_argument("--history-root", default="data/history")
    parser.add_argument("--engine-version", default="0.1.0")
    args = parser.parse_args()

    previous = load_ovtlyr_csv(args.previous_csv)
    current = load_ovtlyr_csv(args.current_csv)
    classified = compare_universes(previous, current)
    sectors = summarize_sector_rotation(classified)
    archive = archive_daily_run(
        history_root=args.history_root,
        run_date=args.run_date,
        source_csv=args.current_csv,
        classified=classified,
        sectors=sectors,
        engine_version=args.engine_version,
    )

    counts: dict[str, int] = {}
    for item in classified:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    print(
        json.dumps(
            {
                "run_date": archive.run_date,
                "run_directory": str(archive.run_directory),
                "source_sha256": archive.source_hash_sha256,
                "status_counts": counts,
                "non_optionable": sum(item.optionable is False for item in classified),
                "optionability_unknown": sum(item.optionable is None for item in classified),
                "artifacts": {name: str(path) for name, path in archive.files.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
