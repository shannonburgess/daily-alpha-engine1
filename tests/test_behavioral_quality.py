from __future__ import annotations

from datetime import UTC, datetime, timedelta

from daily_alpha.behavioral_change import (
    BehavioralObservation,
    BehavioralSource,
    SourceStatus,
)
from daily_alpha.behavioral_quality import assess_behavioral_quality


def _row(*, as_of: datetime, days_ago: int, level: float) -> BehavioralObservation:
    timestamp = as_of - timedelta(days=days_ago)
    return BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        query_key="NVIDIA",
        metric="NEW_VIDEO_COUNT_24H",
        observed_at=timestamp,
        source_timestamp=timestamp,
        raw_level=level,
        provenance="youtube:test",
    )


def test_stale_source_fails_closed_without_extreme_event_inference() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    rows = [_row(as_of=as_of, days_ago=3, level=12.0)]

    result = assess_behavioral_quality(
        rows,
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        metric="NEW_VIDEO_COUNT_24H",
        as_of=as_of,
        freshness_limit_hours=24.0,
    )

    assert result.status == SourceStatus.SOURCE_UNAVAILABLE
    assert result.reason == "STALE_SOURCE_EVIDENCE"
    assert result.fresh is False
    assert result.extreme_event_flag is None
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_insufficient_history_stays_visible_without_fabricated_winsor_bounds() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    rows = [_row(as_of=as_of, days_ago=i, level=10.0 + i) for i in range(8)]

    result = assess_behavioral_quality(
        rows,
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        metric="NEW_VIDEO_COUNT_24H",
        as_of=as_of,
        freshness_limit_hours=24.0,
        min_prior_daily_points=14,
    )

    assert result.status == SourceStatus.COMPLETE
    assert result.fresh is True
    assert result.extreme_event_flag is None
    assert result.winsorized_latest_level is None
    assert result.extreme_event_reason == (
        "INSUFFICIENT_PRIOR_HISTORY_FOR_EXTREME_EVENT_CONTROL"
    )


def test_extreme_latest_level_is_flagged_against_prior_only_bounds() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    rows = [_row(as_of=as_of, days_ago=0, level=1_000.0)]
    rows.extend(
        _row(as_of=as_of, days_ago=i, level=10.0 + (i % 4))
        for i in range(1, 22)
    )

    result = assess_behavioral_quality(
        rows,
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        metric="NEW_VIDEO_COUNT_24H",
        as_of=as_of,
        freshness_limit_hours=24.0,
    )

    assert result.status == SourceStatus.COMPLETE
    assert result.extreme_event_flag is True
    assert result.latest_raw_level == 1_000.0
    assert result.winsor_upper_bound is not None
    assert result.winsorized_latest_level == result.winsor_upper_bound
    assert result.winsorized_latest_level < result.latest_raw_level
    assert result.extreme_event_reason == "LATEST_LEVEL_OUTSIDE_PRIOR_WINSOR_BOUNDS"


def test_future_rows_are_excluded_from_point_in_time_quality() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    rows = [_row(as_of=as_of, days_ago=i, level=10.0) for i in range(16)]
    future = BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        query_key="NVIDIA",
        metric="NEW_VIDEO_COUNT_24H",
        observed_at=as_of + timedelta(hours=1),
        source_timestamp=as_of + timedelta(hours=1),
        raw_level=99_999.0,
        provenance="youtube:future-test",
    )
    rows.append(future)

    result = assess_behavioral_quality(
        rows,
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        metric="NEW_VIDEO_COUNT_24H",
        as_of=as_of,
        freshness_limit_hours=24.0,
    )

    assert result.status == SourceStatus.COMPLETE
    assert result.latest_raw_level == 10.0
    assert result.observations_used == 16
    assert result.extreme_event_flag is False


def test_conflicting_duplicate_identity_fails_closed() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    first = _row(as_of=as_of, days_ago=0, level=10.0)
    second = BehavioralObservation(
        source=first.source,
        entity_id=first.entity_id,
        ticker=first.ticker,
        query_key=first.query_key,
        metric=first.metric,
        observed_at=first.observed_at,
        source_timestamp=first.source_timestamp,
        raw_level=11.0,
        provenance=first.provenance,
    )

    result = assess_behavioral_quality(
        [first, second],
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        metric="NEW_VIDEO_COUNT_24H",
        as_of=as_of,
        freshness_limit_hours=24.0,
    )

    assert result.status == SourceStatus.DATA_ERROR
    assert result.reason == "CONFLICTING_DUPLICATE_BEHAVIORAL_OBSERVATION"
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False
