"""Inject the repo-backed Lambda source into the staging CloudFormation template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PLACEHOLDER = "__DATA_FEED_INGESTION_INLINE_CODE__"


def render(*, template_path: Path, source_path: Path, output_path: Path) -> None:
    template = json.loads(template_path.read_text(encoding="utf-8"))
    source = source_path.read_text(encoding="utf-8")
    function = template["Resources"]["DataFeedIngestionFunction"]
    if function["Properties"]["Code"]["ZipFile"] != PLACEHOLDER:
        raise ValueError("DATA_FEED_TEMPLATE_PLACEHOLDER_MISSING")
    if "trading_authorized" not in source or "live_trading_enabled" not in source:
        raise ValueError("DATA_FEED_SOURCE_AUTHORITY_GUARDS_MISSING")
    function["Properties"]["Code"]["ZipFile"] = source
    output_path.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    render(template_path=args.template, source_path=args.source, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
