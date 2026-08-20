"""Immutable validation artifacts for Behavioral Change research evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .behavioral_orthogonality import OrthogonalityDiagnostic
from .behavioral_validation import LeadLagObservation, SourceAblationResult


@dataclass(frozen=True)
class BehavioralValidationArtifactBundle:
    path: Path
    sha256: str


def write_behavioral_validation_artifact(
    root: str | Path,
    *,
    entity_id: str,
    ticker: str,
    behavioral_as_of: datetime,
    evaluation_cutoff: datetime,
    source_ablation: tuple[SourceAblationResult, ...],
    lead_lag: tuple[LeadLagObservation, ...],
    orthogonality: tuple[OrthogonalityDiagnostic, ...],
) -> BehavioralValidationArtifactBundle:
    """Persist one deterministic, immutable point-in-time validation evidence set."""
    _require_aware(behavioral_as_of, "behavioral_as_of")
    _require_aware(evaluation_cutoff, "evaluation_cutoff")
    as_of = behavioral_as_of.astimezone(UTC)
    cutoff = evaluation_cutoff.astimezone(UTC)
    if cutoff < as_of:
        raise ValueError("BEHAVIORAL_VALIDATION_CUTOFF_BEFORE_SNAPSHOT")

    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("BEHAVIORAL_VALIDATION_TICKER_REQUIRED")
    safe_entity = _safe_segment(entity_id)

    _validate_safety(source_ablation, lead_lag, orthogonality)
    for row in lead_lag:
        if row.ticker.upper() != normalized_ticker:
            raise ValueError("BEHAVIORAL_VALIDATION_LEAD_LAG_TICKER_MISMATCH")
        if row.behavioral_as_of.astimezone(UTC) != as_of:
            raise ValueError("BEHAVIORAL_VALIDATION_LEAD_LAG_SNAPSHOT_MISMATCH")
        if row.recognition_known_at.astimezone(UTC) > cutoff:
            raise ValueError("BEHAVIORAL_VALIDATION_LEAD_LAG_LOOKAHEAD_REJECTED")
    for row in orthogonality:
        if row.evaluation_cutoff.astimezone(UTC) != cutoff:
            raise ValueError("BEHAVIORAL_VALIDATION_ORTHOGONALITY_CUTOFF_MISMATCH")

    payload = {
        "schema_version": "2026-08-20-v1",
        "entity_id": safe_entity,
        "ticker": normalized_ticker,
        "behavioral_as_of": as_of.isoformat(),
        "evaluation_cutoff": cutoff.isoformat(),
        "source_ablation": [
            _jsonable(asdict(row))
            for row in sorted(source_ablation, key=lambda item: item.omitted_source.value)
        ],
        "lead_lag": [
            _jsonable(asdict(row))
            for row in sorted(
                lead_lag,
                key=lambda item: (
                    item.recognition_known_at.astimezone(UTC),
                    item.recognition_type,
                ),
            )
        ],
        "orthogonality": [
            _jsonable(asdict(row))
            for row in sorted(orthogonality, key=lambda item: item.family.value)
        ],
        "research_only": True,
        "promotion_authorized": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    content = (
        json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()

    directory = Path(root) / as_of.date().isoformat() / safe_entity
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "behavioral_validation_evidence.json"
    _write_immutable(path, content)
    return BehavioralValidationArtifactBundle(path=path, sha256=digest)


def _validate_safety(
    source_ablation: tuple[SourceAblationResult, ...],
    lead_lag: tuple[LeadLagObservation, ...],
    orthogonality: tuple[OrthogonalityDiagnostic, ...],
) -> None:
    for row in (*source_ablation, *lead_lag, *orthogonality):
        if getattr(row, "research_only", None) is not True:
            raise ValueError("BEHAVIORAL_VALIDATION_RESEARCH_ONLY_REQUIRED")
        if getattr(row, "trading_authorized", None) is not False:
            raise ValueError("BEHAVIORAL_VALIDATION_TRADING_AUTHORIZATION_REJECTED")
        if getattr(row, "live_trading_enabled", None) is not False:
            raise ValueError("BEHAVIORAL_VALIDATION_LIVE_TRADING_REJECTED")
    for row in orthogonality:
        if row.promotion_authorized is not False:
            raise ValueError("BEHAVIORAL_VALIDATION_PROMOTION_AUTHORIZATION_REJECTED")


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
            raise ValueError("BEHAVIORAL_VALIDATION_IMMUTABILITY_VIOLATION")
        return
    path.write_bytes(content)


def _safe_segment(value: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or any(char in text for char in "/\\"):
        raise ValueError("BEHAVIORAL_VALIDATION_ENTITY_ID_INVALID")
    return text


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
