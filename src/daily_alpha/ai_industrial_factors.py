"""Research-only AI industrial mobilization and bottleneck-migration factors.

This module models observable industrial/economic evidence only. It does not encode
AGI timelines, authorize trades, or override the canonical Daily Alpha execution
stack. Provider-specific collectors should normalize their own point-in-time data
into the bounded evidence contract defined here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class IndustrialLayer(StrEnum):
    COMPUTE = "COMPUTE"
    MEMORY = "MEMORY"
    PACKAGING = "PACKAGING"
    NETWORKING_OPTICS = "NETWORKING_OPTICS"
    DATA_CENTER_INFRA = "DATA_CENTER_INFRA"
    ELECTRICAL_EQUIPMENT = "ELECTRICAL_EQUIPMENT"
    GENERATION = "GENERATION"
    TRANSMISSION = "TRANSMISSION"
    MATERIALS = "MATERIALS"


LAYER_ORDER = tuple(IndustrialLayer)


class EvidenceFamily(StrEnum):
    CAPEX = "CAPEX"
    BACKLOG_ORDERS = "BACKLOG_ORDERS"
    DEMAND = "DEMAND"
    CAPACITY = "CAPACITY"
    MONETIZATION = "MONETIZATION"
    POWER_LOAD = "POWER_LOAD"
    POWER_PRICE = "POWER_PRICE"
    GRID_CONGESTION = "GRID_CONGESTION"
    INTERCONNECTION = "INTERCONNECTION"
    SUPPLY_BACKLOG = "SUPPLY_BACKLOG"
    MATERIAL_SUPPLY = "MATERIAL_SUPPLY"
    GEOPOLITICAL_SUPPLY = "GEOPOLITICAL_SUPPLY"


class EvidenceStatus(StrEnum):
    COMPLETE = "COMPLETE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class IndustrialEvidence:
    evidence_id: str
    layer: IndustrialLayer
    family: EvidenceFamily
    metric: str
    observed_at: datetime
    source_timestamp: datetime
    normalized_signal: float
    provenance: str
    source_version: str
    status: EvidenceStatus = EvidenceStatus.COMPLETE
    reason: str = ""

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.source_timestamp, "source_timestamp")
        if self.source_timestamp > self.observed_at:
            raise ValueError("AI_INDUSTRIAL_SOURCE_TIMESTAMP_AFTER_OBSERVED_AT")
        if not self.evidence_id.strip() or not self.metric.strip():
            raise ValueError("AI_INDUSTRIAL_EVIDENCE_IDENTITY_REQUIRED")
        if not self.provenance.strip() or not self.source_version.strip():
            raise ValueError("AI_INDUSTRIAL_EVIDENCE_PROVENANCE_REQUIRED")
        if self.status == EvidenceStatus.COMPLETE:
            if not math.isfinite(self.normalized_signal):
                raise ValueError("AI_INDUSTRIAL_SIGNAL_NOT_FINITE")
            if not -1.0 <= self.normalized_signal <= 1.0:
                raise ValueError("AI_INDUSTRIAL_SIGNAL_OUT_OF_RANGE")
        elif self.normalized_signal != 0.0:
            raise ValueError("AI_INDUSTRIAL_UNAVAILABLE_SIGNAL_MUST_BE_ZERO")
        if self.status != EvidenceStatus.COMPLETE and not self.reason.strip():
            raise ValueError("AI_INDUSTRIAL_UNAVAILABLE_REASON_REQUIRED")

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.evidence_id,
            self.layer.value,
            self.family.value,
            self.metric,
            self.source_timestamp.astimezone(UTC).isoformat(),
        )


@dataclass(frozen=True)
class LayerConstraint:
    layer: IndustrialLayer
    demand_score: float | None
    capacity_relief_score: float | None
    bottleneck_score: float | None
    evidence_count: int
    source_families: tuple[str, ...]


@dataclass(frozen=True)
class ConstraintMigration:
    prior_leading_layer: IndustrialLayer | None
    current_leading_layer: IndustrialLayer | None
    direction: str
    persistence: float | None


@dataclass(frozen=True)
class AiIndustrialSnapshot:
    as_of: datetime
    capex_momentum: float | None
    ai_bottleneck_score: float | None
    layer_constraints: tuple[LayerConstraint, ...]
    constraint_migration: ConstraintMigration
    ai_power_scarcity: float | None
    monetization_capex_validation: float | None
    evidence_count: int
    complete_family_count: int
    status: EvidenceStatus
    reason: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


_DEMAND_FAMILIES = {
    EvidenceFamily.DEMAND,
    EvidenceFamily.BACKLOG_ORDERS,
    EvidenceFamily.SUPPLY_BACKLOG,
    EvidenceFamily.POWER_LOAD,
    EvidenceFamily.POWER_PRICE,
    EvidenceFamily.GRID_CONGESTION,
    EvidenceFamily.INTERCONNECTION,
    EvidenceFamily.MATERIAL_SUPPLY,
    EvidenceFamily.GEOPOLITICAL_SUPPLY,
}
_CAPACITY_FAMILIES = {EvidenceFamily.CAPACITY}
_POWER_FAMILIES = {
    EvidenceFamily.POWER_LOAD,
    EvidenceFamily.POWER_PRICE,
    EvidenceFamily.GRID_CONGESTION,
    EvidenceFamily.INTERCONNECTION,
    EvidenceFamily.SUPPLY_BACKLOG,
}


def build_ai_industrial_snapshot(
    evidence: tuple[IndustrialEvidence, ...],
    *,
    as_of: datetime,
    prior_snapshot: AiIndustrialSnapshot | None = None,
) -> AiIndustrialSnapshot:
    """Build one point-in-time industrial snapshot from pre-normalized evidence."""
    _require_aware(as_of, "as_of")
    cutoff = as_of.astimezone(UTC)
    rows = _dedupe_point_in_time(evidence, as_of=cutoff)
    complete = tuple(row for row in rows if row.status == EvidenceStatus.COMPLETE)
    if prior_snapshot is not None:
        _require_aware(prior_snapshot.as_of, "prior_snapshot.as_of")
        if prior_snapshot.as_of.astimezone(UTC) >= cutoff:
            raise ValueError("AI_INDUSTRIAL_PRIOR_SNAPSHOT_NOT_PRIOR")

    layer_constraints = tuple(_layer_constraint(layer, complete) for layer in LAYER_ORDER)
    available_bottlenecks = [
        item.bottleneck_score
        for item in layer_constraints
        if item.bottleneck_score is not None
    ]
    bottleneck_score = (
        None
        if not available_bottlenecks
        else round(max(available_bottlenecks), 4)
    )
    current_leader = _leading_layer(layer_constraints)
    migration = _migration(prior_snapshot, current_leader, layer_constraints)

    capex = _family_score(complete, {EvidenceFamily.CAPEX}, signed=True)
    power = _family_score(complete, _POWER_FAMILIES, signed=False)
    monetization = _monetization_capex_validation(complete)
    complete_families = {row.family for row in complete}

    if not complete:
        status = EvidenceStatus.SOURCE_UNAVAILABLE
        reason = "NO_COMPLETE_POINT_IN_TIME_INDUSTRIAL_EVIDENCE"
    elif len(complete_families) < 2:
        status = EvidenceStatus.DATA_ERROR
        reason = "INSUFFICIENT_INDEPENDENT_EVIDENCE_FAMILIES"
    else:
        status = EvidenceStatus.COMPLETE
        reason = ""

    return AiIndustrialSnapshot(
        as_of=cutoff,
        capex_momentum=capex,
        ai_bottleneck_score=bottleneck_score,
        layer_constraints=layer_constraints,
        constraint_migration=migration,
        ai_power_scarcity=power,
        monetization_capex_validation=monetization,
        evidence_count=len(complete),
        complete_family_count=len(complete_families),
        status=status,
        reason=reason,
    )


def _layer_constraint(
    layer: IndustrialLayer,
    evidence: tuple[IndustrialEvidence, ...],
) -> LayerConstraint:
    rows = [row for row in evidence if row.layer == layer]
    demand_values = [row.normalized_signal for row in rows if row.family in _DEMAND_FAMILIES]
    capacity_values = [
        row.normalized_signal for row in rows if row.family in _CAPACITY_FAMILIES
    ]
    demand = _bounded_mean(demand_values)
    capacity = _bounded_mean(capacity_values)
    bottleneck = None
    if demand is not None:
        capacity_relief = 0.0 if capacity is None else max(-1.0, min(1.0, capacity))
        raw = demand - capacity_relief
        bottleneck = round(max(0.0, min(100.0, 50.0 + 50.0 * raw)), 4)
    return LayerConstraint(
        layer=layer,
        demand_score=None if demand is None else round(100.0 * demand, 4),
        capacity_relief_score=None if capacity is None else round(100.0 * capacity, 4),
        bottleneck_score=bottleneck,
        evidence_count=len(rows),
        source_families=tuple(sorted({row.family.value for row in rows})),
    )


def _family_score(
    evidence: tuple[IndustrialEvidence, ...],
    families: set[EvidenceFamily],
    *,
    signed: bool,
) -> float | None:
    values = [row.normalized_signal for row in evidence if row.family in families]
    mean = _bounded_mean(values)
    if mean is None:
        return None
    if signed:
        return round(100.0 * mean, 4)
    return round(max(0.0, min(100.0, 50.0 + 50.0 * mean)), 4)


def _monetization_capex_validation(
    evidence: tuple[IndustrialEvidence, ...],
) -> float | None:
    capex = _bounded_mean(
        [row.normalized_signal for row in evidence if row.family == EvidenceFamily.CAPEX]
    )
    monetization = _bounded_mean(
        [
            row.normalized_signal
            for row in evidence
            if row.family == EvidenceFamily.MONETIZATION
        ]
    )
    if capex is None or monetization is None:
        return None
    return round(max(-100.0, min(100.0, 100.0 * (monetization - capex))), 4)


def _leading_layer(constraints: tuple[LayerConstraint, ...]) -> IndustrialLayer | None:
    available = [item for item in constraints if item.bottleneck_score is not None]
    if not available:
        return None
    available.sort(
        key=lambda item: (
            -(item.bottleneck_score or 0.0),
            LAYER_ORDER.index(item.layer),
        )
    )
    return available[0].layer


def _migration(
    prior_snapshot: AiIndustrialSnapshot | None,
    current_leader: IndustrialLayer | None,
    constraints: tuple[LayerConstraint, ...],
) -> ConstraintMigration:
    prior_leader = (
        None if prior_snapshot is None else prior_snapshot.constraint_migration.current_leading_layer
    )
    if prior_leader is None or current_leader is None:
        direction = "INSUFFICIENT_HISTORY"
    elif prior_leader == current_leader:
        direction = "PERSISTENT"
    else:
        prior_index = LAYER_ORDER.index(prior_leader)
        current_index = LAYER_ORDER.index(current_leader)
        direction = "DOWNSTREAM" if current_index > prior_index else "UPSTREAM"

    persistence = None
    if current_leader is not None:
        selected = next(item for item in constraints if item.layer == current_leader)
        if selected.bottleneck_score is not None:
            persistence = round(selected.bottleneck_score / 100.0, 4)
    return ConstraintMigration(
        prior_leading_layer=prior_leader,
        current_leading_layer=current_leader,
        direction=direction,
        persistence=persistence,
    )


def _dedupe_point_in_time(
    evidence: tuple[IndustrialEvidence, ...],
    *,
    as_of: datetime,
) -> tuple[IndustrialEvidence, ...]:
    unique: dict[tuple[str, str, str, str, str], IndustrialEvidence] = {}
    for row in evidence:
        if row.observed_at.astimezone(UTC) > as_of:
            continue
        prior = unique.get(row.identity)
        if prior is not None and prior != row:
            raise ValueError("AI_INDUSTRIAL_CONFLICTING_DUPLICATE_EVIDENCE")
        unique[row.identity] = row
    return tuple(sorted(unique.values(), key=lambda row: row.identity))


def _bounded_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return max(-1.0, min(1.0, statistics.fmean(values)))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
