"""Command-line entry point for validating a daily universe file."""

from __future__ import annotations

import argparse
import json

from .ingestion import load_universe


def main() -> None:
    parser = argparse.ArgumentParser(prog="daily-alpha")
    parser.add_argument("universe_csv", help="Path to the daily OVTLYR universe CSV")
    args = parser.parse_args()

    records = load_universe(args.universe_csv)
    buy_count = sum(record.signal == "BUY" for record in records)
    print(
        json.dumps(
            {
                "records_loaded": len(records),
                "buy_signals": buy_count,
                "symbols": [record.symbol for record in records],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
