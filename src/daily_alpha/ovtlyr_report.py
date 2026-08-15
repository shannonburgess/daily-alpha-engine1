"""Write reproducible and immutable OVTLYR history artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .ovtlyr import ClassifiedRecord, SectorRotation


class ArchiveExistsError(FileExistsError):
    """Raised when a dated archive would overwrite an existing run."""


@dataclass(frozen=True)
class ArchiveResult:
    run_date: str
    run_directory: Path
    source_hash_sha256: str
    files: dict[str, Path]


def write_comparison_outputs(
    output_dir: str | Path,
    classified: list[ClassifiedRecord],
    sectors: list[SectorRotation],
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    json_path = destination / "comparison.json"
    csv_path = destination / "comparison.csv"
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


def archive_daily_run(
    *,
    history_root: str | Path,
    run_date: str,
    source_csv: str | Path,
    classified: list[ClassifiedRecord],
    sectors: list[SectorRotation],
    engine_version: str,
    created_at: datetime | None = None,
) -> ArchiveResult:
    """Create one immutable dated run and update the lightweight latest pointer."""
    normalized_date = _validate_date(run_date)
    root = Path(history_root)
    run_directory = root / normalized_date
    if run_directory.exists():
        raise ArchiveExistsError(
            f"History already exists for {normalized_date}; daily archives are immutable"
        )

    source = Path(source_csv)
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    run_directory.mkdir(parents=True)

    universe_path = run_directory / "universe.csv"
    shutil.copyfile(source, universe_path)
    files = write_comparison_outputs(run_directory, classified, sectors)

    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    status_counts: dict[str, int] = {}
    for item in classified:
        status_counts[item.status.value] = status_counts.get(item.status.value, 0) + 1

    manifest: dict[str, Any] = {
        "run_date": normalized_date,
        "created_at": timestamp.astimezone(UTC).isoformat(),
        "engine_version": engine_version,
        "source": {
            "original_filename": source.name,
            "archived_filename": universe_path.name,
            "sha256": source_hash,
            "size_bytes": len(source_bytes),
        },
        "record_count": len(classified),
        "status_counts": status_counts,
        "optionability": {
            "optionable": sum(item.optionable is True for item in classified),
            "non_optionable": sum(item.optionable is False for item in classified),
            "unknown": sum(item.optionable is None for item in classified),
        },
        "artifacts": sorted(path.name for path in files.values()),
    }
    manifest_path = run_directory / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    files = {
        "universe_csv": universe_path,
        **files,
        "run_manifest": manifest_path,
    }

    root.mkdir(parents=True, exist_ok=True)
    latest_path = root / "latest.json"
    latest_path.write_text(
        json.dumps(
            {
                "run_date": normalized_date,
                "run_directory": normalized_date,
                "source_sha256": source_hash,
                "engine_version": engine_version,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    files["latest_pointer"] = latest_path
    return ArchiveResult(
        run_date=normalized_date,
        run_directory=run_directory,
        source_hash_sha256=source_hash,
        files=files,
    )


def _validate_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("run_date must use YYYY-MM-DD") from exc
    normalized = parsed.isoformat()
    if value != normalized:
        raise ValueError("run_date must use zero-padded YYYY-MM-DD")
    return normalized
