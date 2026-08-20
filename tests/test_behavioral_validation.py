from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_change import (
    BehavioralEntity,
    BehavioralSource,
    SourceSignal,
    SourceStatus,
    build_behavioral_snapshot,
)
from daily_alpha.behavioral_validation import (
    RecognitionEvent,
    lead_lag_observations,
    source_ablation,
)


def _signal(source: BehavioralSource, score: float) -> SourceSignal:
    as_of = datetime(2026, 8, 19, 20, tzinfo=UTC)
    return SourceSignal(
        source=source,
        as_of=as_of,
        status=SourceStatus.COMPLETE,
        reason="",
        observations_used=28,
        level_7d=100.0,
        level_28d=300.0,
        velocity_7d=0.3,
        prior_velocity_7d=0.1,
        acceleration=0.2,
        abnormality_z=1.2,
        persistence=0.8,
        prototype_score=score,
    )


def _snapshot():
    entity = BehavioralEntity(entity_id="nvda", ticker="NVDA", version="v1")
    signals = (
        _signal(BehavioralSource.GOOGLE_TRENDS, 70.0),
        _signal(BehavioralSource.YOUTUBE, 80.0),
        _signal(BehavioralSource.SIMILARWEB, 65.0),
    )
    return build_behavioral_snapshot(
        entity,
        signals,
        as_of=datetime(2026, 8, 19, 20, tzinfo=UTC),
    )


def test_source_ablation_requires_independent_sources() -> None:
    snapshot = _snapshot()
    rows = source_ablation(snapshot)

    assert len(rows) == 3
    assert all(row.status == "COMPLETE" for row in rows)
    assert all(row.complete_sources_after == 2 for row in rows)
    assert all(row.ablated_score is not None for row in rows)
    assert all(row.trading_authorized is False for row in rows)
    assert all(row.live_trading_enabled is False for row in rows)


def test_two_source_snapshot_ablation_fails_closed() -> None:
    entity = BehavioralEntity(entity_id="nvda", ticker="NVDA", version="v1")
    snapshot = build_behavioral_snapshot(
        entity,
        (
            _signal(BehavioralSource.GOOGLE_TRENDS, 70.0),
            _signal(BehavioralSource.YOUTUBE, 80.0),
        ),
        as_of=datetime(2026, 8, 19, 20, tzinfo=UTC),
    )

    rows = source_ablation(snapshot)

    assert len(rows) == 2
    assert all(row.ablated_score is None for row in rows)
    assert all(
        row.status == "INSUFFICIENT_INDEPENDENT_SOURCES_AFTER_ABLATION"
        for row in rows
    )


def test_lead_lag_uses_only_events_known_by_cutoff() -> None:
    snapshot = _snapshot()
    cutoff = snapshot.as_of + timedelta(days=5)
    events = (
        RecognitionEvent(
            ticker="NVDA",
            event_type="OVTLYR_EMERGING",
            first_known_at=snapshot.as_of + timedelta(days=2),
            provenance="immutable-ovtlyr-archive",
        ),
        RecognitionEvent(
            ticker="NVDA",
            event_type="ANALYST_REVISION",
            first_known_at=snapshot.as_of + timedelta(days=8),
            provenance="point-in-time-revision-feed",
        ),
    )

    rows = lead_lag_observations(snapshot, events, evaluation_cutoff=cutoff)

    assert len(rows) == 1
    assert rows[0].recognition_type == "OVTLYR_EMERGING"
    assert rows[0].lead_days == 2.0
    assert rows[0].relationship == "BEHAVIOR_LEADS_RECOGNITION"
    assert rows[0].research_only is True


def test_lead_lag_rejects_ticker_mismatch_and_future_snapshot() -> None:
    snapshot = _snapshot()
    mismatch = RecognitionEvent(
        ticker="AMD",
        event_type="OVTLYR_EMERGING",
        first_known_at=snapshot.as_of + timedelta(days=1),
        provenance="immutable-ovtlyr-archive",
    )
    with pytest.raises(ValueError, match="TICKER_MISMATCH"):
        lead_lag_observations(
            snapshot,
            (mismatch,),
            evaluation_cutoff=snapshot.as_of + timedelta(days=2),
        )

    with pytest.raises(ValueError, match="SNAPSHOT_AFTER_EVALUATION_CUTOFF"):
        lead_lag_observations(
            snapshot,
            (),
            evaluation_cutoff=snapshot.as_of - timedelta(seconds=1),
        )
