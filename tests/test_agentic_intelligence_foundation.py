from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.contracts import (
    EvidenceContractError,
    EvidenceRecord,
    EvidenceStatus,
    ReadinessStatus,
)
from daily_alpha.agentic.evidence_store import EvidenceConflictError, InMemoryEvidenceStore
from daily_alpha.agentic.source_registry import SourcePolicy, SourceRegistry
from daily_alpha.agentic.supervisor import DataSupervisor


NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _record(
    *,
    source: str = "SOURCE_A",
    evidence_type: str = "SECTOR",
    value="Energy",
    observed_at: datetime | None = None,
    received_at: datetime | None = None,
    status: EvidenceStatus = EvidenceStatus.COMPLETE,
    confidence: float = 1.0,
    provenance=None,
) -> EvidenceRecord:
    observed = observed_at or NOW - timedelta(minutes=5)
    received = received_at or observed + timedelta(seconds=5)
    return EvidenceRecord(
        symbol="dino",
        evidence_type=evidence_type,
        value=value,
        source=source,
        observed_at=observed,
        received_at=received,
        source_version="v1",
        status=status,
        confidence=confidence,
        provenance=provenance or {},
    )


def _policy(
    *,
    source: str = "SOURCE_A",
    evidence_type: str = "SECTOR",
    required: bool = True,
    freshness: int = 3_600,
    agreement: bool = False,
) -> SourcePolicy:
    return SourcePolicy(
        source=source,
        owner="test",
        evidence_types=(evidence_type,),
        cadence_seconds=300,
        max_freshness_seconds=freshness,
        required=required,
        requires_cross_source_agreement=agreement,
    )


def test_evidence_identity_is_deterministic_and_provenance_order_independent():
    first = _record(provenance={"file": "shortlist.json", "sha256": "abc"})
    second = _record(provenance={"sha256": "abc", "file": "shortlist.json"})

    assert first.symbol == "DINO"
    assert first.source == "SOURCE_A"
    assert first.evidence_id == second.evidence_id
    assert first.value_hash == second.value_hash


def test_evidence_rejects_naive_or_future_point_in_time_data():
    with pytest.raises(EvidenceContractError, match="OBSERVED_AT_MUST_BE_TIMEZONE_AWARE"):
        _record(observed_at=NOW.replace(tzinfo=None))

    record = _record(
        observed_at=NOW + timedelta(seconds=1),
        received_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(EvidenceContractError, match="FUTURE_EVIDENCE_NOT_ALLOWED"):
        record.validate_point_in_time(NOW)


def test_agentic_foundation_cannot_authorize_trading():
    with pytest.raises(EvidenceContractError, match="AGENTIC_FOUNDATION_MUST_REMAIN_RESEARCH_ONLY"):
        EvidenceRecord(
            symbol="DINO",
            evidence_type="SECTOR",
            value="Energy",
            source="SOURCE_A",
            observed_at=NOW - timedelta(minutes=1),
            received_at=NOW,
            source_version="v1",
            trading_authorized=True,
        )


def test_store_is_idempotent_but_rejects_logical_observation_rewrite():
    store = InMemoryEvidenceStore()
    record = _record()

    first_id = store.put(record)
    second_id = store.put(record)
    assert first_id == second_id

    conflicting = _record(value="Technology")
    with pytest.raises(EvidenceConflictError, match="EVIDENCE_IMMUTABILITY_VIOLATION"):
        store.put(conflicting)


def test_store_returns_only_evidence_available_at_as_of_boundary():
    store = InMemoryEvidenceStore()
    available = _record(
        observed_at=NOW - timedelta(minutes=10),
        received_at=NOW - timedelta(minutes=9),
    )
    future_received = _record(
        source="SOURCE_B",
        observed_at=NOW - timedelta(minutes=2),
        received_at=NOW + timedelta(minutes=1),
    )
    store.put_many((available, future_received))

    records = store.records_for_symbol("DINO", NOW)
    assert records == (available,)


def test_supervisor_passes_complete_fresh_required_evidence():
    store = InMemoryEvidenceStore()
    store.put(_record())
    supervisor = DataSupervisor(
        registry=SourceRegistry((_policy(),)),
        store=store,
    )

    packet = supervisor.evaluate("dino", NOW)

    assert packet.status is ReadinessStatus.PASS
    assert packet.completeness_score == 100.0
    assert packet.blockers == ()
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False


def test_supervisor_blocks_missing_or_stale_required_evidence():
    registry = SourceRegistry((_policy(freshness=60),))
    missing = DataSupervisor(registry=registry, store=InMemoryEvidenceStore()).evaluate("DINO", NOW)
    assert missing.status is ReadinessStatus.BLOCKED
    assert missing.blockers == ("MISSING_REQUIRED_EVIDENCE:SOURCE_A:SECTOR",)

    store = InMemoryEvidenceStore()
    store.put(
        _record(
            observed_at=NOW - timedelta(minutes=10),
            received_at=NOW - timedelta(minutes=9),
        )
    )
    stale = DataSupervisor(registry=registry, store=store).evaluate("DINO", NOW)
    assert stale.status is ReadinessStatus.BLOCKED
    assert stale.blockers == ("STALE:SOURCE_A:SECTOR",)


def test_optional_bad_evidence_warns_without_blocking():
    store = InMemoryEvidenceStore()
    store.put(_record(status=EvidenceStatus.DATA_ERROR))
    supervisor = DataSupervisor(
        registry=SourceRegistry((_policy(required=False),)),
        store=store,
    )

    packet = supervisor.evaluate("DINO", NOW)

    assert packet.status is ReadinessStatus.WARNING
    assert packet.blockers == ()
    assert packet.warnings == ("DATA_ERROR:SOURCE_A:SECTOR",)


def test_cross_source_disagreement_blocks_when_agreement_is_required():
    store = InMemoryEvidenceStore()
    store.put(_record(source="SOURCE_A", value="Energy"))
    store.put(_record(source="SOURCE_B", value="Technology"))
    registry = SourceRegistry(
        (
            _policy(source="SOURCE_A", agreement=True),
            _policy(source="SOURCE_B", agreement=True),
        )
    )

    packet = DataSupervisor(registry=registry, store=store).evaluate("DINO", NOW)

    assert packet.status is ReadinessStatus.BLOCKED
    assert packet.blockers == ("CROSS_SOURCE_CONFLICT:SECTOR:SOURCE_A,SOURCE_B",)


def test_source_registry_rejects_silent_policy_redefinition():
    registry = SourceRegistry((_policy(),))
    with pytest.raises(EvidenceContractError, match="SOURCE_POLICY_CONFLICT:SOURCE_A"):
        registry.register(_policy(freshness=7_200))
