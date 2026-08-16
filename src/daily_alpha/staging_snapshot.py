"""Durable normalized snapshot format for validated OVTLYR intake data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ovtlyr import OvtlyrRecord, load_ovtlyr_csv

SCHEMA_VERSION = "2026-08-16-v1"


def build_ovtlyr_snapshot(
    source_path: str | Path,
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    """Normalize one validated OVTLYR CSV into a deterministic lookup snapshot."""
    source = Path(source_path)
    observed = _aware(observed_at)
    payload = source.read_bytes()
    records = load_ovtlyr_csv(source)
    symbols = {record.symbol: _record_payload(record) for record in records}
    buy_symbols = sorted(record.symbol for record in records if record.signal == "BUY")
    return {
        "schema_version": SCHEMA_VERSION,
        "source_file": source.name,
        "observed_at": observed.isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "record_count": len(records),
        "buy_count": len(buy_symbols),
        "buy_symbols": buy_symbols,
        "symbols": symbols,
    }


def write_ovtlyr_snapshot(
    source_path: str | Path,
    output_path: str | Path,
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    """Write a normalized OVTLYR snapshot and return the serialized payload."""
    snapshot = build_ovtlyr_snapshot(source_path, observed_at=observed_at)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot


def load_ovtlyr_snapshot(value: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Validate the staging snapshot envelope before downstream use."""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError("OVTLYR snapshot must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported OVTLYR snapshot schema")
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict) or not symbols:
        raise ValueError("OVTLYR snapshot contains no symbols")
    if int(payload.get("record_count", -1)) != len(symbols):
        raise ValueError("OVTLYR snapshot record count mismatch")
    _aware(datetime.fromisoformat(str(payload.get("observed_at", ""))))
    return payload


def _record_payload(record: OvtlyrRecord) -> dict[str, Any]:
    return asdict(record)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC)
