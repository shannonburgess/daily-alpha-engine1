"""Research-only factor snapshots from existing Daily Alpha candidate evidence.

This adapter intentionally runs in parallel with the production/research candidate ranker.
It does not alter candidate scores, execution eligibility, sizing, or any paper/live gate.
Unavailable factor families remain explicit rather than being inferred from weak proxies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .candidates import CandidateAssessment, CandidateBucket
from .factor_attribution import FACTOR_NAMES, FactorScore, FactorVector, score_factor_vector
from .ovtlyr import ClassifiedRecord, OvtlyrRecord, OvtlyrStatus

CANDIDATE_FACTOR_SNAPSHOT_SCHEMA = "2026-08-19-candidate-factor-v1"
CANDIDATE_FACTOR_ARTIFACT_SCHEMA = "2026-08-19-candidate-factor-set-v1"

DEFAULT_CANDIDATE_FACTOR_WEIGHTS = {
    "momentum": 0.20,
    "relative_strength": 0.10,
    "trendability": 0.20,
    "liquidity_capacity": 0.15,
    "sector_industry_leadership": 0.15,
    "volatility_quality": 0.05,
    "options_confirmation": 0.10,
    "catalyst_state": 0.025,
    "breadth_regime": 0.025,
}


@dataclass(frozen=True)
class CandidateFactorSnapshot:
    schema_version: str
    snapshot_id: str
    weights_hash: str
    symbol: str
    as_of: str
    ovtlyr_status: str
    vector: FactorVector
    factor_score: FactorScore
    availability: dict[str, bool]
    weighted_coverage: float
    unavailable_factors: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "weights_hash": self.weights_hash,
            "symbol": self.symbol,
            "as_of": self.as_of,
            "ovtlyr_status": self.ovtlyr_status,
            "vector": self.vector.to_dict(),
            "factor_score": self.factor_score.to_dict(),
            "availability": dict(self.availability),
            "weighted_coverage": self.weighted_coverage,
            "unavailable_factors": list(self.unavailable_factors),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


def build_candidate_factor_snapshot(
    *,
    as_of: str,
    source: OvtlyrRecord,
    classified: ClassifiedRecord,
    candidate: CandidateAssessment,
    weights: dict[str, float] | None = None,
) -> CandidateFactorSnapshot:
    """Map only observed candidate evidence into an immutable factor snapshot.

    Factors that do not have a trustworthy point-in-time input in the current candidate
    contract are left at zero *and* marked unavailable. The factor score is therefore a
    research diagnostic only; coverage must be inspected alongside it.
    """
    symbols = {source.symbol.upper(), classified.symbol.upper(), candidate.symbol.upper()}
    if len(symbols) != 1:
        raise ValueError("CANDIDATE_FACTOR_SYMBOL_MISMATCH")
    normalized_as_of = _normalized_as_of(as_of)

    factors = {name: 0.0 for name in FACTOR_NAMES}
    availability = {name: False for name in FACTOR_NAMES}

    momentum = _momentum_value(source.momentum, classified.status)
    if momentum is not None:
        factors["momentum"] = momentum
        availability["momentum"] = True

    trendability = _trendability_value(source.trend, candidate.pine_entry)
    if trendability is not None:
        factors["trendability"] = trendability
        availability["trendability"] = True

    liquidity_capacity = _liquidity_capacity_value(source)
    if liquidity_capacity is not None:
        factors["liquidity_capacity"] = liquidity_capacity
        availability["liquidity_capacity"] = True

    factors["sector_industry_leadership"] = _clamp(candidate.sector_net_score / 40.0)
    availability["sector_industry_leadership"] = True

    options_confirmation = _options_confirmation_value(candidate)
    if options_confirmation is not None:
        factors["options_confirmation"] = options_confirmation
        availability["options_confirmation"] = True

    vector = FactorVector(
        symbol=source.symbol.upper(),
        as_of=normalized_as_of,
        factors=factors,
        sector=source.sector,
        industry=source.industry,
    )
    active_weights = dict(weights or DEFAULT_CANDIDATE_FACTOR_WEIGHTS)
    factor_score = score_factor_vector(vector, weights=active_weights)
    weighted_coverage = round(_weighted_coverage(availability, active_weights), 6)
    unavailable = tuple(name for name in FACTOR_NAMES if not availability[name])
    weights_hash = _hash_payload(active_weights)
    identity_payload = {
        "schema_version": CANDIDATE_FACTOR_SNAPSHOT_SCHEMA,
        "symbol": source.symbol.upper(),
        "as_of": normalized_as_of,
        "ovtlyr_status": classified.status.value,
        "vector": vector.to_dict(),
        "factor_score": factor_score.to_dict(),
        "availability": availability,
        "weighted_coverage": weighted_coverage,
        "unavailable_factors": list(unavailable),
        "weights_hash": weights_hash,
    }
    snapshot_id = _hash_payload(identity_payload)
    return CandidateFactorSnapshot(
        schema_version=CANDIDATE_FACTOR_SNAPSHOT_SCHEMA,
        snapshot_id=snapshot_id,
        weights_hash=weights_hash,
        symbol=source.symbol.upper(),
        as_of=normalized_as_of,
        ovtlyr_status=classified.status.value,
        vector=vector,
        factor_score=factor_score,
        availability=availability,
        weighted_coverage=weighted_coverage,
        unavailable_factors=unavailable,
    )


def write_candidate_factor_snapshots(
    path: str | Path,
    snapshots: list[CandidateFactorSnapshot],
) -> Path:
    """Write a deterministic research artifact without changing candidate ranking."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered_snapshots = sorted(
        (item.to_dict() for item in snapshots),
        key=lambda item: (item["as_of"], item["symbol"], item["snapshot_id"]),
    )
    snapshot_set_id = _hash_payload(ordered_snapshots)
    payload = {
        "schema_version": CANDIDATE_FACTOR_ARTIFACT_SCHEMA,
        "snapshot_set_id": snapshot_set_id,
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
        "count": len(ordered_snapshots),
        "snapshots": ordered_snapshots,
    }
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination


def _normalized_as_of(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("CANDIDATE_FACTOR_AS_OF_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("CANDIDATE_FACTOR_AS_OF_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CANDIDATE_FACTOR_AS_OF_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC).isoformat()


def _hash_payload(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _momentum_value(momentum: str, status: OvtlyrStatus) -> float | None:
    normalized = momentum.strip().upper()
    if normalized in {"ACCELERATING", "STRONG", "RISING", "POSITIVE", "MOVING UP"}:
        return 1.0
    if normalized in {"UP", "BULLISH", "IMPROVING"}:
        return 0.5
    if normalized in {"WEAKENING", "FADING", "DECLINING", "NEGATIVE", "MOVING DOWN"}:
        return -0.75
    if normalized in {"DOWN", "BEARISH"}:
        return -1.0
    if normalized:
        return 0.0
    if status in {OvtlyrStatus.EMERGING, OvtlyrStatus.NEW_BUY, OvtlyrStatus.RE_ENTRY}:
        return 0.25
    if status in {OvtlyrStatus.DETERIORATING, OvtlyrStatus.REMOVED}:
        return -0.5
    return None


def _trendability_value(trend: str, pine_entry: bool) -> float | None:
    normalized = trend.strip().upper()
    if normalized in {"UP", "UPTREND", "BULLISH", "RISING"}:
        base = 0.5
    elif normalized in {"DOWN", "DOWNTREND", "BEARISH", "FALLING"}:
        base = -0.75
    elif normalized:
        base = 0.0
    else:
        return 0.5 if pine_entry else None
    return _clamp(base + (0.5 if pine_entry else 0.0))


def _liquidity_capacity_value(source: OvtlyrRecord) -> float | None:
    if source.partial_data or source.price <= 0 or source.average_volume <= 0:
        return None
    average_daily_dollar_volume = source.price * source.average_volume
    if average_daily_dollar_volume >= 500_000_000:
        return 1.0
    if average_daily_dollar_volume >= 100_000_000:
        return 0.75
    if average_daily_dollar_volume >= 50_000_000:
        return 0.5
    if average_daily_dollar_volume >= 20_000_000:
        return 0.25
    return 0.0


def _options_confirmation_value(candidate: CandidateAssessment) -> float | None:
    if candidate.bucket != CandidateBucket.OPTION_SETUP:
        return None
    spread = candidate.selected_spread_pct
    if spread is None or spread < 0:
        return None
    spread_quality = 1.0 - min(spread / 0.10, 1.0)
    unusual_bonus = 0.25 if candidate.unusual_options_activity else 0.0
    return _clamp(spread_quality + unusual_bonus)


def _weighted_coverage(
    availability: dict[str, bool],
    weights: dict[str, float],
) -> float:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("CANDIDATE_FACTOR_WEIGHT_SUM_MUST_BE_POSITIVE")
    covered = sum(weight for factor, weight in weights.items() if availability.get(factor))
    return covered / total


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))
