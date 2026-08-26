"""Command line for comparing and archiving consecutive OVTLYR exports."""

from __future__ import annotations

import argparse
import json

from .ovtlyr_ingestion import ingest_transform_archive


def main() -> None:
    parser = argparse.ArgumentParser(prog="daily-alpha-compare")
    parser.add_argument("previous_csv")
    parser.add_argument("current_csv")
    parser.add_argument(
        "--run-date",
        help="Optional YYYY-MM-DD assertion; must match current source filename",
    )
    parser.add_argument("--history-root", default="data/history")
    parser.add_argument("--engine-version", default="0.1.0")
    args = parser.parse_args()

    transformation, archive = ingest_transform_archive(
        previous_csv=args.previous_csv,
        current_csv=args.current_csv,
        history_root=args.history_root,
        run_date=args.run_date,
        engine_version=args.engine_version,
    )

    counts: dict[str, int] = {}
    for item in transformation.classified:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    print(
        json.dumps(
            {
                "run_date": archive.run_date,
                "run_directory": str(archive.run_directory),
                "source_sha256": archive.source_hash_sha256,
                "source_rows": transformation.current.row_count,
                "partial_rows": transformation.current.partial_row_count,
                "status_counts": counts,
                "non_optionable": sum(
                    item.optionable is False for item in transformation.classified
                ),
                "optionability_unknown": sum(
                    item.optionable is None for item in transformation.classified
                ),
                "trading_authorized": False,
                "live_trading_enabled": False,
                "artifacts": {name: str(path) for name, path in archive.files.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
