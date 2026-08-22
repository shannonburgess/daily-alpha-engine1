# ruff: noqa: I001
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.contracts import EvidenceRecord, EvidenceStatus, ReadinessStatus
from daily_alpha.agentic.durable_evidence import (
    DecisionLineage,
    DurableEvidenceError,
    InMemoryDurableEvidenceRepository,
    SourceHealthEvent,
    SourceHealthStatus,
    evidence_record_from_payload,
    evidence_record_to_payload,
    source_registry_fingerprint,
)
from daily_alpha.agentic.evidence_store import EvidenceConflictError
from daily_alpha.agentic.source_registry import SourcePolicy, SourceRegistry


NOW = datetime(2026, 8, 21, 21, 0, tzinfo=UTC)


def _record(
    *,
    source: str = "SOURCE_A",
    evidence_type: str = "SECTOR",
    value="Energy",
    observed_at: datetime | None = None,
    received_at: datetime | None = None,
    status: EvidenceStatus = EvidenceStatus.COMPLETE,
) -> EvidenceRecord:
    observed = observed_at or NOW - timedelta(minutes=5)
    received = received_at or observed + timedelta(seconds=5)
    return EvidenceRecord(
        symbol="DINO",
        evidence_type=evidence_type,
        value=value,
        source=source,
        observed_at=observed,
        received_at=received,
        source_version="v1",
        status=status,
        provenance={"fixture": "durable"},
    )


def _registry(*, freshness: int = 3_600) -> SourceRegistry:
    return SourceRegistry(
        (
            SourcePolicy(
                source="SOURCE_A",
                owner="test",
                evidence_types=("SECTOR",),
                cadence_seconds=60,
                max_freshness_seconds=freshness,
                required=True,
            ),
        )
    )


def test_snapshot_id_is_deterministic_across_insertion_order():
    first = _record(source="SOURCE_A", evidence_type="SECTOR", value="Energy")
    second = _record(
        source="SOURCE_B",
        evidence_type="OVTLYR_STATE",
        value={"status": "EMERGING"},
        observed_at=NOW - timedelta(minutes=4),
    )

    repo_a = InMemoryDurableEvidenceRepository()
    repo_a.append_evidence_many((first, second))
    snapshot_a = repo_a.create_snapshot("DINO", NOW)

    repo_b = InMemoryDurableEvidenceRepository()
    repo_b.append_evidence_many((second, first))
    snapshot_b = repo_b.create_snapshot("dino", NOW)

    assert snapshot_a.snapshot_id == snapshot_b.snapshot_id
    assert snapshot_a.evidence_ids == tuple(sorted((first.evidence_id, second.evidence_id)))


def test_snapshot_excludes_evidence_not_received_by_as_of_boundary():
    available = _record()
    future_received = _record(
        source="SOURCE_B",
        evidence_type="OVTLYR_STATE",
        value={"status": "LEADER"},
        observed_at=NOW - timedelta(minutes=1),
        received_at=NOW + timedelta(seconds=1),
    )
    repo = InMemoryDurableEvidenceRepository()
    repo.append_evidence_many((available, future_received))

    snapshot = repo.create_snapshot("DINO", NOW)

    assert snapshot.evidence_ids == (available.evidence_id,)


def test_bundle_binds_registry_readiness_and_point_in_time_health():
    repo = InMemoryDurableEvidenceRepository()
    repo.append_evidence(_record())
    before = SourceHealthEvent(
        source="SOURCE_A",
        observed_at=NOW - timedelta(minutes=2),
        status=SourceHealthStatus.HEALTHY,
        evidence_type="SECTOR",
    )
    after = SourceHealthEvent(
        source="SOURCE_A",
        observed_at=NOW + timedelta(minutes=1),
        status=SourceHealthStatus.UNAVAILABLE,
        evidence_type="SECTOR",
        reason_code="OUTAGE",
    )
    repo.append_health(before)
    repo.append_health(after)
    registry = _registry()

    snapshot = repo.create_snapshot("DINO", NOW)
    bundle = repo.create_bundle(snapshot.snapshot_id, registry)

    assert bundle.registry_fingerprint == source_registry_fingerprint(registry)
    assert bundle.readiness_status is ReadinessStatus.PASS
    assert bundle.health_event_ids == (before.health_event_id,)
    assert after.health_event_id not in bundle.health_event_ids


def test_stale_required_evidence_is_replayed_as_blocked():
    repo = InMemoryDurableEvidenceRepository()
    repo.append_evidence(
        _record(
            observed_at=NOW - timedelta(minutes=10),
            received_at=NOW - timedelta(minutes=9),
        )
    )
    registry = _registry(freshness=60)

    snapshot = repo.create_snapshot("DINO", NOW)
    replay = repo.replay(snapshot.snapshot_id, registry)

    assert replay.readiness.status is ReadinessStatus.BLOCKED
    assert replay.bundle.readiness_status is ReadinessStatus.BLOCKED
    assert replay.readiness.blockers == ("STALE:SOURCE_A:SECTOR",)


def test_historical_replay_is_stable_after_later_evidence_arrives():
    repo = InMemoryDurableEvidenceRepository()
    original = _record(value="Energy")
    repo.append_evidence(original)
    registry = _registry()
    snapshot = repo.create_snapshot("DINO", NOW)
    first_replay = repo.replay(snapshot.snapshot_id, registry)

    later = _record(
        value="Technology",
        observed_at=NOW + timedelta(minutes=5),
        received_at=NOW + timedelta(minutes=5, seconds=5),
    )
    repo.append_evidence(later)
    second_replay = repo.replay(snapshot.snapshot_id, registry)

    assert first_replay.snapshot.snapshot_id == second_replay.snapshot.snapshot_id
    assert first_replay.bundle.bundle_id == second_replay.bundle.bundle_id
    assert first_replay.evidence == second_replay.evidence == (original,)


def test_evidence_wire_payload_round_trip_and_tamper_detection():
    original = _record(value={"sector": "Energy", "rank": 2})
    payload = evidence_record_to_payload(original)

    restored = evidence_record_from_payload(payload)

    assert restored == original
    assert restored.evidence_id == original.evidence_id

    payload["evidence_id"] = "not-the-real-id"
    with pytest.raises(DurableEvidenceError, match="EVIDENCE_PAYLOAD_ID_MISMATCH"):
        evidence_record_from_payload(payload)


def test_decision_lineage_is_immutable_for_one_model_decision_slot():
    repo = InMemoryDurableEvidenceRepository()
    first = DecisionLineage(
        symbol="DINO",
        decision_at=NOW,
        decision_type="POSITION_ACTION",
        decision_value="WAIT",
        evidence_bundle_id="bundle-1",
        model_id="CIO_SHADOW",
        model_version="v1",
    )
    second = DecisionLineage(
        symbol="DINO",
        decision_at=NOW,
        decision_type="POSITION_ACTION",
        decision_value="BUY",
        evidence_bundle_id="bundle-1",
        model_id="CIO_SHADOW",
        model_version="v1",
    )

    assert repo.append_lineage(first) == first.decision_id
    assert repo.append_lineage(first) == first.decision_id
    with pytest.raises(EvidenceConflictError, match="DECISION_LINEAGE_IMMUTABILITY_VIOLATION"):
        repo.append_lineage(second)


def test_durable_contract_cannot_enable_live_trading():
    with pytest.raises(DurableEvidenceError, match="DURABLE_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY"):
        SourceHealthEvent(
            source="SOURCE_A",
            observed_at=NOW,
            status=SourceHealthStatus.HEALTHY,
            live_trading_enabled=True,
        )
