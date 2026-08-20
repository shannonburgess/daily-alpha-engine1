"""Immutable point-in-time artifacts for Behavioral Change research evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .behavioral_change import BehavioralObservation, BehavioralSnapshot


@dataclass(frozen=True)
class BehavioralArtifactBundle:
    directory: Path
    observations_path: Path
    snapshot_path: Path
    manifest_path: Path
    observations_sha256: str
    snapshot_sha256: str


def write_behavioral_daily_artifacts(
    root: str | Path,
    *,
    observations: tuple[BehavioralObservation, ...],
    snapshot: BehavioralSnapshot,
) -> BehavioralArtifactBundle:
    """Persist one immutable entity/day evidence set with deterministic hashes."""
    _require_aware(snapshot.as_of, "snapshot.as_of")
    canonical_observations = _canonical_observations(observations, snapshot=snapshot)
    day = snapshot.as_of.astimezone(UTC).date().isoformat()
    entity = _safe_segment(snapshot.entity_id)
    directory = Path(root) / day / entity
    directory.mkdir(parents=True, exist_ok=True)

    observation_rows = [_observation_payload(row) for row in canonical_observations]
    observations_bytes = (
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in observation_rows
        )
    ).encode("utf-8")
    snapshot_bytes = (
        json.dumps(
            _jsonable(asdict(snapshot)),
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    observations_sha256 = hashlib.sha256(observations_bytes).hexdigest()
    snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()

    observations_path = directory / "behavioral_observations.jsonl"
    snapshot_path = directory / "behavioral_snapshot.json"
    _write_immutable(observations_path, observations_bytes)
    _write_immutable(snapshot_path, snapshot_bytes)

    manifest = {
        "schema_version": "2026-08-19-v1",
        "entity_id": snapshot.entity_id,
        "ticker": snapshot.ticker,
        "as_of": snapshot.as_of.astimezone(UTC).isoformat(),
        "observation_count": len(canonical_observations),
        "observations_sha256": observations_sha256,
        "snapshot_sha256": snapshot_sha256,
        "research_only": snapshot.research_only,
        "trading_authorized": snapshot.trading_authorized,
        "live_trading_enabled": snapshot.live_trading_enabled,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    ).encode("utf-8")
    manifest_path = directory / "behavioral_manifest.json"
    _write_immutable(manifest_path, manifest_bytes)

    return BehavioralArtifactBundle(
        directory=directory,
        observations_path=observations_path,
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
        observations_sha256=observations_sha256,
        snapshot_sha256=snapshot_sha256,
    )


def _canonical_observations(
    observations: tuple[BehavioralObservation, ...],
    *,
    snapshot: BehavioralSnapshot,
) -> tuple[BehavioralObservation, ...]:
    unique: dict[tuple[str, str, str, str, str], BehavioralObservation] = {}
    for row in observations:
        if row.entity_id != snapshot.entity_id or row.ticker.upper() != snapshot.ticker.upper():
            raise ValueError("BEHAVIORAL_ARTIFACT_ENTITY_MISMATCH")
        if row.observed_at > snapshot.as_of or row.source_timestamp > snapshot.as_of:
            raise ValueError("BEHAVIORAL_ARTIFACT_LOOKAHEAD_REJECTED")
        prior = unique.get(row.identity)
        if prior is not None and prior != row:
            raise ValueError("BEHAVIORAL_ARTIFACT_CONFLICTING_DUPLICATE")
        unique[row.identity] = row
    return tuple(sorted(unique.values(), key=lambda row: row.identity))


def _observation_payload(row: BehavioralObservation) -> dict[str, Any]:
    return {
        "source": row.source.value,
        "entity_id": row.entity_id,
        "ticker": row.ticker.upper(),
        "query_key": row.query_key,
        "metric": row.metric,
        "observed_at": row.observed_at.astimezone(UTC).isoformat(),
        "source_timestamp": row.source_timestamp.astimezone(UTC).isoformat(),
        "raw_level": row.raw_level,
        "provenance": row.provenance,
        "identity": list(row.identity),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        _require_aware(value, "datetime")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"BEHAVIORAL_ARTIFACT_IMMUTABILITY_VIOLATION:{path.name}")
        return
    path.write_bytes(content)


def _safe_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or any(char in text for char in "/\\"):
        raise ValueError("BEHAVIORAL_ARTIFACT_ENTITY_ID_INVALID")
    return text


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
