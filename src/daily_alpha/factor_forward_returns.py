"""Research-only immutable forward-return joins for factor evidence.

This module binds an already-frozen candidate factor snapshot to a later, explicitly
sourced forward-return observation. The join is keyed by the snapshot SHA-256 identity
and cannot change candidate ranking, factor weights, paper execution, or live trading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

from .candidate_factor_snapshot import CandidateFactorSnapshot
from .factor_attribution import FACTOR_NAMES, FactorReturnObservation

FACTOR_FORWARD_RETURN_SCHEMA = "2026-08-19-factor-forward-return-v1"
FACTOR_FORWARD_RETURN_SET_SCHEMA = "2026-08-19-factor-forward-return-set-v1"


@dataclass(frozen=True)
class FrozenForwardReturn:
    """A later price observation tied to one immutable factor snapshot."""

    snapshot_id: str
    symbol: str
    as_of: str
    horizon_bars: int
    bars_observed: int
    reference_price: float
    evaluation_price: float
    evaluation_at: str
    source_id: str
    source_hash: str

    def __post_init__(self) -> None:
        if not _is_sha256(self.snapshot_id):
            raise ValueError("FACTOR_FORWARD_SNAPSHOT_ID_INVALID")
        if not self.symbol.strip():
            raise ValueError("FACTOR_FORWARD_SYMBOL_REQUIRED")
        if self.horizon_bars <= 0 or self.bars_observed <= 0:
            raise ValueError("FACTOR_FORWARD_HORIZON_INVALID")
        if self.horizon_bars != self.bars_observed:
            raise ValueError("FACTOR_FORWARD_BAR_COUNT_MISMATCH")
        if (
            not isfinite(self.reference_price)
            or not isfinite(self.evaluation_price)
            or self.reference_price <= 0
            or self.evaluation_price <= 0
        ):
            raise ValueError("FACTOR_FORWARD_PRICE_INVALID")
        as_of = _parse_time(self.as_of, "FACTOR_FORWARD_AS_OF")
        evaluated = _parse_time(self.evaluation_at, "FACTOR_FORWARD_EVALUATED_AT")
        if evaluated <= as_of:
            raise ValueError("FACTOR_FORWARD_EVALUATION_NOT_AFTER_SNAPSHOT")
        if not self.source_id.strip():
            raise ValueError("FACTOR_FORWARD_SOURCE_ID_REQUIRED")
        if not _is_sha256(self.source_hash):
            raise ValueError("FACTOR_FORWARD_SOURCE_HASH_INVALID")

    @property
    def forward_return(self) -> float:
        return self.evaluation_price / self.reference_price - 1.0

    @property
    def outcome_id(self) -> str:
        return _hash_payload(
            {
                "schema_version": FACTOR_FORWARD_RETURN_SCHEMA,
                "snapshot_id": self.snapshot_id,
                "symbol": self.symbol.upper(),
                "as_of": _normalize_time(self.as_of),
                "horizon_bars": self.horizon_bars,
                "bars_observed": self.bars_observed,
                "reference_price": self.reference_price,
                "evaluation_price": self.evaluation_price,
                "evaluation_at": _normalize_time(self.evaluation_at),
                "source_id": self.source_id,
                "source_hash": self.source_hash,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FACTOR_FORWARD_RETURN_SCHEMA,
            "outcome_id": self.outcome_id,
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol.upper(),
            "as_of": _normalize_time(self.as_of),
            "horizon_bars": self.horizon_bars,
            "bars_observed": self.bars_observed,
            "reference_price": self.reference_price,
            "evaluation_price": self.evaluation_price,
            "forward_return": round(self.forward_return, 12),
            "evaluation_at": _normalize_time(self.evaluation_at),
            "source_id": self.source_id,
            "source_hash": self.source_hash,
            "research_only": True,
            "trading_authorized": False,
            "live_trading_enabled": False,
        }


@dataclass(frozen=True)
class FactorForwardReturnBinding:
    """Immutable join result used to build factor IC/decay evidence."""

    snapshot_id: str
    outcome_id: str
    symbol: str
    as_of: str
    horizon_bars: int
    forward_return: float
    observations: tuple[FactorReturnObservation, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "outcome_id": self.outcome_id,
            "symbol": self.symbol,
            "as_of": self.as_of,
            "horizon_bars": self.horizon_bars,
            "forward_return": round(self.forward_return, 12),
            "factor_observation_count": len(self.observations),
            "factors": [item.factor for item in self.observations],
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


def bind_forward_return(
    snapshot: CandidateFactorSnapshot,
    outcome: FrozenForwardReturn,
) -> FactorForwardReturnBinding:
    """Bind a frozen later return to the exact snapshot that preceded it."""
    if outcome.snapshot_id != snapshot.snapshot_id:
        raise ValueError("FACTOR_FORWARD_SNAPSHOT_ID_MISMATCH")
    if outcome.symbol.upper() != snapshot.symbol.upper():
        raise ValueError("FACTOR_FORWARD_SYMBOL_MISMATCH")
    if _normalize_time(outcome.as_of) != _normalize_time(snapshot.as_of):
        raise ValueError("FACTOR_FORWARD_AS_OF_MISMATCH")

    observations = []
    for factor in FACTOR_NAMES:
        if not snapshot.availability.get(factor, False):
            continue
        observations.append(
            FactorReturnObservation(
                symbol=snapshot.symbol.upper(),
                factor=factor,
                factor_value=snapshot.vector.factors[factor],
                forward_return=outcome.forward_return,
                as_of=snapshot.as_of,
                horizon_bars=outcome.horizon_bars,
                regime=snapshot.vector.regime,
                sector=snapshot.vector.sector,
            )
        )
    if not observations:
        raise ValueError("FACTOR_FORWARD_NO_AVAILABLE_FACTORS")

    return FactorForwardReturnBinding(
        snapshot_id=snapshot.snapshot_id,
        outcome_id=outcome.outcome_id,
        symbol=snapshot.symbol.upper(),
        as_of=snapshot.as_of,
        horizon_bars=outcome.horizon_bars,
        forward_return=outcome.forward_return,
        observations=tuple(observations),
    )


def write_factor_forward_return_bindings(
    path: str | Path,
    bindings: list[FactorForwardReturnBinding],
) -> Path:
    """Write deterministic join metadata without embedding mutable ranking logic."""
    if not bindings:
        raise ValueError("FACTOR_FORWARD_BINDINGS_REQUIRED")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        (item.to_dict() for item in bindings),
        key=lambda item: (
            item["as_of"],
            item["symbol"],
            item["horizon_bars"],
            item["snapshot_id"],
            item["outcome_id"],
        ),
    )
    payload = {
        "schema_version": FACTOR_FORWARD_RETURN_SET_SCHEMA,
        "binding_set_id": _hash_payload(ordered),
        "count": len(ordered),
        "bindings": ordered,
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return destination


def _parse_time(value: str, field: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError(f"{field}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    return parsed


def _normalize_time(value: str) -> str:
    return _parse_time(value, "FACTOR_FORWARD_TIME").astimezone(UTC).isoformat()


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _hash_payload(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
