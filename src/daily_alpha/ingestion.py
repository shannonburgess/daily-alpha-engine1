"""CSV ingestion for the daily OVTLYR master universe."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UniverseRecord:
    symbol: str
    signal: str
    signal_date: str
    sector: str = ""
    industry: str = ""


_REQUIRED_ALIASES = {
    "symbol": ("symbol", "ticker"),
    "signal": ("signal", "status", "rating"),
    "signal_date": ("signal_date", "date", "overlay_start_date"),
}


def load_universe(path: str | Path) -> list[UniverseRecord]:
    """Load and normalize a daily universe CSV without changing the source file."""
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")

        normalized = {_normalize(name): name for name in reader.fieldnames}
        columns = {
            logical: _find_column(normalized, aliases)
            for logical, aliases in _REQUIRED_ALIASES.items()
        }

        records: list[UniverseRecord] = []
        for row_number, row in enumerate(reader, start=2):
            symbol = (row.get(columns["symbol"]) or "").strip().upper()
            if not symbol:
                continue
            records.append(
                UniverseRecord(
                    symbol=symbol,
                    signal=(row.get(columns["signal"]) or "").strip().upper(),
                    signal_date=(row.get(columns["signal_date"]) or "").strip(),
                    sector=_optional_value(row, normalized, "sector"),
                    industry=_optional_value(row, normalized, "industry"),
                )
            )

        if not records:
            raise ValueError("CSV contains no usable symbol rows")
        return records


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _find_column(normalized: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    raise ValueError(f"Missing required CSV column; expected one of: {', '.join(aliases)}")


def _optional_value(row: dict[str, str], normalized: dict[str, str], name: str) -> str:
    original = normalized.get(name)
    return (row.get(original) or "").strip() if original else ""
