from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_change import (
    BehavioralEntity,
    BehavioralObservation,
    BehavioralSource,
    GoogleTrendsAdapter,
    SimilarwebAdapter,
    SourceSignal,
    SourceStatus,
    YouTubeDataAdapter,
    build_behavioral_snapshot,
    derive_source_signal,
)

AS_OF = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
ENTITY = BehavioralEntity(
    entity_id="NVDA:v1",
    ticker="NVDA",
    version="1",
    company_name="Nvidia",
    aliases=("NVIDIA", "Nvidia"),
    brands=("GeForce",),
    products=("Blackwell", "DGX"),
    domains=("nvidia.com",),
    technologies=("CUDA", "AI GPU"),
)


def _history(source, *, current_multiplier=2.2, future_level=None):
    rows = []
    for days_ago in range(27, -1, -1):
        timestamp = AS_OF - timedelta(days=days_ago)
        if days_ago >= 14:
            level = 100.0
        elif days_ago >= 7:
            level = 120.0
        else:
            level = 120.0 * current_multiplier
        rows.append(
            BehavioralObservation(
                source=source,
                entity_id=ENTITY.entity_id,
                ticker=ENTITY.ticker,
                query_key="Blackwell",
                metric="attention",
                observed_at=timestamp,
                source_timestamp=timestamp,
                raw_level=level,
                provenance=f"synthetic:{source.value}:{timestamp.date()}",
            )
        )
    if future_level is not None:
        timestamp = AS_OF + timedelta(days=1)
        rows.append(
            BehavioralObservation(
                source=source,
                entity_id=ENTITY.entity_id,
                ticker=ENTITY.ticker,
                query_key="Blackwell",
                metric="attention",
                observed_at=timestamp,
                source_timestamp=timestamp,
                raw_level=future_level,
                provenance="synthetic:future",
            )
        )
    return rows


def _complete_signal(source, *, score=80.0, persistence=0.8):
    return SourceSignal(
        source=source,
        as_of=AS_OF,
        status=SourceStatus.COMPLETE,
        reason="",
        observations_used=28,
        level_7d=1400.0,
        level_28d=4000.0,
        velocity_7d=0.5,
        prior_velocity_7d=0.1,
        acceleration=0.4,
        abnormality_z=2.0,
        persistence=persistence,
        prototype_score=score,
    )


def test_entity_dictionary_deduplicates_terms_and_separates_domains():
    assert ENTITY.search_terms() == (
        "Nvidia",
        "GeForce",
        "Blackwell",
        "DGX",
        "CUDA",
        "AI GPU",
    )
    assert ENTITY.website_domains() == ("nvidia.com",)


def test_unconfigured_providers_fail_closed_without_credentials():
    trends = GoogleTrendsAdapter().collect(ENTITY, as_of=AS_OF)
    youtube = YouTubeDataAdapter().collect(ENTITY, as_of=AS_OF)
    similarweb = SimilarwebAdapter().collect(ENTITY, as_of=AS_OF)

    for result in (trends, youtube, similarweb):
        assert result.status == SourceStatus.SOURCE_UNAVAILABLE
        assert result.reason == "PROVIDER_ACCESS_NOT_CONFIGURED"
        assert result.observations == ()


def test_provider_cache_avoids_duplicate_same_day_fetches():
    calls = []

    def fetcher(entity, query_keys, as_of):
        calls.append((entity.entity_id, query_keys, as_of))
        return _history(BehavioralSource.YOUTUBE)

    adapter = YouTubeDataAdapter(fetcher=fetcher, max_queries_per_run=3)
    first = adapter.collect(ENTITY, as_of=AS_OF)
    second = adapter.collect(ENTITY, as_of=AS_OF + timedelta(hours=1))

    assert first.status == SourceStatus.COMPLETE
    assert first.cache_hit is False
    assert second.status == SourceStatus.COMPLETE
    assert second.cache_hit is True
    assert len(calls) == 1
    assert calls[0][1] == ("Nvidia", "GeForce", "Blackwell")


def test_source_signal_is_point_in_time_and_ignores_future_observation():
    baseline = derive_source_signal(
        _history(BehavioralSource.GOOGLE_TRENDS),
        source=BehavioralSource.GOOGLE_TRENDS,
        as_of=AS_OF,
    )
    with_future = derive_source_signal(
        _history(BehavioralSource.GOOGLE_TRENDS, future_level=1_000_000),
        source=BehavioralSource.GOOGLE_TRENDS,
        as_of=AS_OF,
    )

    assert baseline.status == SourceStatus.COMPLETE
    assert baseline.velocity_7d is not None and baseline.velocity_7d > 1.0
    assert baseline.acceleration is not None and baseline.acceleration > 0
    assert baseline.prototype_score is not None and baseline.prototype_score >= 60
    assert with_future == baseline


def test_sparse_history_is_data_error_not_zero_signal():
    rows = _history(BehavioralSource.YOUTUBE)[:10]
    signal = derive_source_signal(
        rows,
        source=BehavioralSource.YOUTUBE,
        as_of=AS_OF,
    )

    assert signal.status == SourceStatus.DATA_ERROR
    assert signal.reason == "INSUFFICIENT_HISTORY_FOR_VELOCITY"
    assert signal.prototype_score is None


def test_conflicting_duplicate_observations_fail_closed():
    timestamp = AS_OF - timedelta(days=1)
    first = BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id=ENTITY.entity_id,
        ticker=ENTITY.ticker,
        query_key="Blackwell",
        metric="views",
        observed_at=timestamp,
        source_timestamp=timestamp,
        raw_level=100.0,
        provenance="one",
    )
    second = BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id=ENTITY.entity_id,
        ticker=ENTITY.ticker,
        query_key="Blackwell",
        metric="views",
        observed_at=timestamp,
        source_timestamp=timestamp,
        raw_level=101.0,
        provenance="two",
    )

    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE_OBSERVATION"):
        derive_source_signal(
            (first, second),
            source=BehavioralSource.YOUTUBE,
            as_of=AS_OF,
        )


def test_one_source_cannot_create_behavioral_change_score():
    snapshot = build_behavioral_snapshot(
        ENTITY,
        (_complete_signal(BehavioralSource.YOUTUBE),),
        as_of=AS_OF,
    )

    assert snapshot.behavioral_change_score is None
    assert snapshot.cross_source_confirmation == 50.0
    assert snapshot.information_imbalance_score is None
    assert snapshot.information_imbalance_reason == "WALL_STREET_RECOGNITION_NOT_CONNECTED"
    assert snapshot.research_only is True
    assert snapshot.trading_authorized is False
    assert snapshot.live_trading_enabled is False


def test_two_persistent_independent_sources_create_research_score_only():
    snapshot = build_behavioral_snapshot(
        ENTITY,
        (
            _complete_signal(BehavioralSource.GOOGLE_TRENDS, score=85.0),
            _complete_signal(BehavioralSource.YOUTUBE, score=75.0),
            SourceSignal(
                source=BehavioralSource.SIMILARWEB,
                as_of=AS_OF,
                status=SourceStatus.SOURCE_UNAVAILABLE,
                reason="PROVIDER_ACCESS_NOT_CONFIGURED",
                observations_used=0,
                level_7d=None,
                level_28d=None,
                velocity_7d=None,
                prior_velocity_7d=None,
                acceleration=None,
                abnormality_z=None,
                persistence=None,
                prototype_score=None,
            ),
        ),
        as_of=AS_OF,
    )

    assert snapshot.cross_source_confirmation == 100.0
    assert snapshot.behavioral_change_score == 84.0
    assert snapshot.information_imbalance_score is None
    assert snapshot.research_only is True
    assert snapshot.trading_authorized is False
    assert snapshot.live_trading_enabled is False
