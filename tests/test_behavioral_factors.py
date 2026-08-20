from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.behavioral_change import (
    BehavioralSnapshot,
    BehavioralSource,
    SourceSignal,
    SourceStatus,
)
from daily_alpha.behavioral_factors import build_behavioral_research_factors

AS_OF = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)


def signal(
    source: BehavioralSource,
    *,
    acceleration=0.125,
    persistence=0.75,
    score=70.0,
    status=SourceStatus.COMPLETE,
    reason="",
):
    return SourceSignal(
        source=source,
        as_of=AS_OF,
        status=status,
        reason=reason,
        observations_used=28,
        level_7d=70.0,
        level_28d=200.0,
        velocity_7d=0.2,
        prior_velocity_7d=0.075,
        acceleration=acceleration,
        abnormality_z=1.0,
        persistence=persistence,
        prototype_score=score,
    )


def snapshot(*signals, behavioral_score=72.5, information_score=None):
    return BehavioralSnapshot(
        entity_id="NVDA:2026-08-19-v1",
        ticker="NVDA",
        as_of=AS_OF,
        source_signals=tuple(signals),
        cross_source_confirmation=100.0 if len(signals) >= 2 else 50.0,
        behavioral_change_score=behavioral_score,
        information_imbalance_score=information_score,
        information_imbalance_reason="WALL_STREET_RECOGNITION_NOT_CONNECTED",
    )


def test_named_source_acceleration_factors_use_complete_point_in_time_sources():
    factors = build_behavioral_research_factors(
        snapshot(
            signal(BehavioralSource.GOOGLE_TRENDS, acceleration=0.5),
            signal(BehavioralSource.YOUTUBE, acceleration=0.125),
            signal(BehavioralSource.SIMILARWEB, acceleration=-0.25),
        )
    )

    assert factors.search_acceleration_score == 100.0
    assert factors.video_attention_acceleration_score == 50.0
    assert factors.web_traffic_acceleration_score == 0.0
    assert factors.persistence_score == 75.0
    assert factors.behavioral_change_score == 72.5
    assert factors.trading_authorized is False
    assert factors.live_trading_enabled is False


def test_unavailable_provider_remains_none_with_explicit_reason():
    unavailable = signal(
        BehavioralSource.GOOGLE_TRENDS,
        acceleration=None,
        persistence=None,
        score=None,
        status=SourceStatus.SOURCE_UNAVAILABLE,
        reason="PROVIDER_ACCESS_NOT_CONFIGURED",
    )
    factors = build_behavioral_research_factors(
        snapshot(
            unavailable,
            signal(BehavioralSource.YOUTUBE),
            behavioral_score=None,
        )
    )

    reasons = dict(factors.unavailable_reasons)
    assert factors.search_acceleration_score is None
    assert reasons["SEARCH_ACCELERATION_SCORE"] == "PROVIDER_ACCESS_NOT_CONFIGURED"
    assert factors.video_attention_acceleration_score == 50.0
    assert factors.web_traffic_acceleration_score is None
    assert reasons["WEB_TRAFFIC_ACCELERATION_SCORE"] == "SOURCE_NOT_PRESENT"
    assert reasons["BEHAVIORAL_CHANGE_SCORE"] == "INSUFFICIENT_INDEPENDENT_COMPLETE_SOURCES"


def test_information_imbalance_stays_unavailable_until_recognition_input_exists():
    factors = build_behavioral_research_factors(
        snapshot(
            signal(BehavioralSource.YOUTUBE),
            signal(BehavioralSource.SIMILARWEB),
            information_score=None,
        )
    )

    assert factors.information_imbalance_score is None
    assert dict(factors.unavailable_reasons)["INFORMATION_IMBALANCE_SCORE"] == (
        "WALL_STREET_RECOGNITION_NOT_CONNECTED"
    )


def test_raw_source_acceleration_is_preserved_for_audit():
    factors = build_behavioral_research_factors(
        snapshot(
            signal(BehavioralSource.YOUTUBE, acceleration=0.333),
            behavioral_score=None,
        )
    )

    assert factors.source_raw_acceleration == (("YOUTUBE", 0.333),)
    assert factors.cross_source_confirmation == 50.0
    assert factors.research_only is True
