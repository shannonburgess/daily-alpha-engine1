from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.ai_industrial_factors import (
    AiIndustrialSnapshot,
    ConstraintMigration,
    EvidenceFamily,
    EvidenceStatus,
    IndustrialEvidence,
    IndustrialLayer,
    build_ai_industrial_snapshot,
)


def _row(
    evidence_id: str,
    layer: IndustrialLayer,
    family: EvidenceFamily,
    value: float,
    *,
    observed_at: datetime,
) -> IndustrialEvidence:
    return IndustrialEvidence(
        evidence_id=evidence_id,
        layer=layer,
        family=family,
        metric=evidence_id,
        observed_at=observed_at,
        source_timestamp=observed_at - timedelta(minutes=5),
        normalized_signal=value,
        provenance=f"https://example.com/{evidence_id}",
        source_version="v1",
    )


def test_builds_research_only_bottleneck_and_power_snapshot() -> None:
    as_of = datetime(2026, 8, 19, 20, tzinfo=UTC)
    evidence = (
        _row("capex", IndustrialLayer.COMPUTE, EvidenceFamily.CAPEX, 0.6, observed_at=as_of),
        _row("gpu-demand", IndustrialLayer.COMPUTE, EvidenceFamily.DEMAND, 0.8, observed_at=as_of),
        _row("gpu-capacity", IndustrialLayer.COMPUTE, EvidenceFamily.CAPACITY, 0.2, observed_at=as_of),
        _row("grid", IndustrialLayer.ELECTRICAL_EQUIPMENT, EvidenceFamily.GRID_CONGESTION, 0.7, observed_at=as_of),
        _row("load", IndustrialLayer.GENERATION, EvidenceFamily.POWER_LOAD, 0.5, observed_at=as_of),
        _row("monetization", IndustrialLayer.COMPUTE, EvidenceFamily.MONETIZATION, 0.7, observed_at=as_of),
    )

    snapshot = build_ai_industrial_snapshot(evidence, as_of=as_of)

    assert snapshot.status == EvidenceStatus.COMPLETE
    assert snapshot.capex_momentum == 60.0
    assert snapshot.ai_bottleneck_score == 85.0
    assert snapshot.ai_power_scarcity == 80.0
    assert snapshot.monetization_capex_validation == 10.0
    assert snapshot.research_only is True
    assert snapshot.trading_authorized is False
    assert snapshot.live_trading_enabled is False


def test_future_evidence_is_excluded_point_in_time() -> None:
    as_of = datetime(2026, 8, 19, 20, tzinfo=UTC)
    evidence = (
        _row("demand", IndustrialLayer.MEMORY, EvidenceFamily.DEMAND, 0.5, observed_at=as_of),
        _row("future", IndustrialLayer.MEMORY, EvidenceFamily.CAPACITY, 1.0, observed_at=as_of + timedelta(days=1)),
    )

    snapshot = build_ai_industrial_snapshot(evidence, as_of=as_of)
    memory = next(row for row in snapshot.layer_constraints if row.layer == IndustrialLayer.MEMORY)

    assert snapshot.evidence_count == 1
    assert snapshot.status == EvidenceStatus.DATA_ERROR
    assert snapshot.reason == "INSUFFICIENT_INDEPENDENT_EVIDENCE_FAMILIES"
    assert memory.capacity_relief_score is None
    assert memory.bottleneck_score == 75.0


def test_constraint_migration_tracks_downstream_shift() -> None:
    prior_time = datetime(2026, 8, 18, 20, tzinfo=UTC)
    prior = build_ai_industrial_snapshot(
        (
            _row("compute-demand", IndustrialLayer.COMPUTE, EvidenceFamily.DEMAND, 0.8, observed_at=prior_time),
            _row("compute-capacity", IndustrialLayer.COMPUTE, EvidenceFamily.CAPACITY, 0.1, observed_at=prior_time),
        ),
        as_of=prior_time,
    )
    current_time = prior_time + timedelta(days=1)
    current = build_ai_industrial_snapshot(
        (
            _row("compute-demand-2", IndustrialLayer.COMPUTE, EvidenceFamily.DEMAND, 0.2, observed_at=current_time),
            _row("compute-capacity-2", IndustrialLayer.COMPUTE, EvidenceFamily.CAPACITY, 0.5, observed_at=current_time),
            _row("power-demand", IndustrialLayer.ELECTRICAL_EQUIPMENT, EvidenceFamily.GRID_CONGESTION, 0.9, observed_at=current_time),
            _row("power-capacity", IndustrialLayer.ELECTRICAL_EQUIPMENT, EvidenceFamily.CAPACITY, 0.0, observed_at=current_time),
        ),
        as_of=current_time,
        prior_snapshot=prior,
    )

    assert prior.constraint_migration.current_leading_layer == IndustrialLayer.COMPUTE
    assert current.constraint_migration.current_leading_layer == IndustrialLayer.ELECTRICAL_EQUIPMENT
    assert current.constraint_migration.direction == "DOWNSTREAM"


def test_no_complete_evidence_is_source_unavailable() -> None:
    as_of = datetime(2026, 8, 19, 20, tzinfo=UTC)
    unavailable = IndustrialEvidence(
        evidence_id="no-grid-feed",
        layer=IndustrialLayer.TRANSMISSION,
        family=EvidenceFamily.GRID_CONGESTION,
        metric="queue",
        observed_at=as_of,
        source_timestamp=as_of,
        normalized_signal=0.0,
        provenance="provider:not-configured",
        source_version="v1",
        status=EvidenceStatus.SOURCE_UNAVAILABLE,
        reason="PROVIDER_ACCESS_NOT_CONFIGURED",
    )

    snapshot = build_ai_industrial_snapshot((unavailable,), as_of=as_of)

    assert snapshot.status == EvidenceStatus.SOURCE_UNAVAILABLE
    assert snapshot.ai_bottleneck_score is None
    assert snapshot.reason == "NO_COMPLETE_POINT_IN_TIME_INDUSTRIAL_EVIDENCE"


def test_conflicting_duplicate_evidence_fails_closed() -> None:
    as_of = datetime(2026, 8, 19, 20, tzinfo=UTC)
    first = _row("same", IndustrialLayer.MEMORY, EvidenceFamily.DEMAND, 0.5, observed_at=as_of)
    second = IndustrialEvidence(
        evidence_id=first.evidence_id,
        layer=first.layer,
        family=first.family,
        metric=first.metric,
        observed_at=first.observed_at,
        source_timestamp=first.source_timestamp,
        normalized_signal=0.8,
        provenance=first.provenance,
        source_version=first.source_version,
    )

    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE"):
        build_ai_industrial_snapshot((first, second), as_of=as_of)


def test_prior_snapshot_must_be_strictly_prior() -> None:
    as_of = datetime(2026, 8, 19, 20, tzinfo=UTC)
    prior = AiIndustrialSnapshot(
        as_of=as_of,
        capex_momentum=None,
        ai_bottleneck_score=None,
        layer_constraints=(),
        constraint_migration=ConstraintMigration(None, None, "INSUFFICIENT_HISTORY", None),
        ai_power_scarcity=None,
        monetization_capex_validation=None,
        evidence_count=0,
        complete_family_count=0,
        status=EvidenceStatus.SOURCE_UNAVAILABLE,
        reason="NO_DATA",
    )

    with pytest.raises(ValueError, match="PRIOR_SNAPSHOT_NOT_PRIOR"):
        build_ai_industrial_snapshot((), as_of=as_of, prior_snapshot=prior)
