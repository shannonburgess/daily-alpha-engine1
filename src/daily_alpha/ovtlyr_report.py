"""Write machine-readable OVTLYR comparison and sector-rotation outputs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .ovtlyr import ClassifiedRecord, SectorRotation


def write_comparison_outputs(
    output_dir: str | Path,
    classified: list[ClassifiedRecord],
    sectors: list[SectorRotation],
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    json_path = destination / "daily_comparison.json"
    csv_path = destination / "daily_comparison.csv"
    sector_path = destination / "sector_rotation.json"

    json_path.write_text(
        json.dumps([item.to_dict() for item in classified], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(classified[0].to_dict()) if classified else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(item.to_dict() for item in classified)

    sector_path.write_text(
        json.dumps([asdict(item) for item in sectors], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "comparison_json": json_path,
        "comparison_csv": csv_path,
        "sector_rotation_json": sector_path,
    }
