from datetime import UTC, datetime, timedelta

from daily_alpha.behavioral_change import BehavioralObservation, BehavioralSource, SourceStatus
from daily_alpha.behavioral_engagement_baselines import derive_youtube_engagement_baseline

METRIC = "VIDEO_VIEW_TOTAL_SELECTED_SET"


def _row(day, value, *, metric=METRIC):
    return BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        query_key="ENTITY_UNIQUE_VIDEO_SET",
        metric=metric,
        observed_at=day,
        source_timestamp=day,
        raw_level=float(value),
        provenance="test",
    )


def _history(as_of):
    return [
        _row(as_of - timedelta(days=offset), 100 + (27 - offset) * 10)
        for offset in range(28)
    ]


def test_complete_metric_specific_baseline_derives_without_trading_authority():
    as_of = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)
    signal = derive_youtube_engagement_baseline(
        _history(as_of),
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )

    assert signal.status == SourceStatus.COMPLETE
    assert signal.complete_daily_points == 28
    assert signal.acceleration_log is not None
    assert signal.abnormality_z is not None
    assert signal.persistence is not None
    assert signal.research_only is True
    assert signal.trading_authorized is False
    assert signal.live_trading_enabled is False


def test_missing_day_fails_closed_instead_of_imputing_zero():
    as_of = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)
    rows = _history(as_of)
    rows.pop(10)

    signal = derive_youtube_engagement_baseline(
        rows,
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )

    assert signal.status == SourceStatus.DATA_ERROR
    assert signal.reason == "INSUFFICIENT_COMPLETE_DAILY_ENGAGEMENT_BASELINE"
    assert signal.complete_daily_points == 27
    assert signal.acceleration_log is None


def test_future_observation_is_ignored_at_point_in_time_cutoff():
    as_of = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)
    rows = _history(as_of)
    rows.append(_row(as_of + timedelta(days=1), 9_999_999))

    with_future = derive_youtube_engagement_baseline(
        rows,
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )
    baseline = derive_youtube_engagement_baseline(
        _history(as_of),
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )

    assert with_future == baseline


def test_metric_families_are_never_mixed():
    as_of = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)
    rows = _history(as_of)
    rows.extend(
        _row(
            as_of - timedelta(days=offset),
            1_000_000,
            metric="VIDEO_LIKE_TOTAL_SELECTED_SET",
        )
        for offset in range(28)
    )

    signal = derive_youtube_engagement_baseline(
        rows,
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )

    assert signal.status == SourceStatus.COMPLETE
    assert signal.observations_used == 28


def test_conflicting_same_day_metric_observation_fails_closed():
    as_of = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)
    rows = _history(as_of)
    rows.append(_row(as_of, 999_999))

    signal = derive_youtube_engagement_baseline(
        rows,
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )

    assert signal.status == SourceStatus.DATA_ERROR
    assert signal.reason == "CONFLICTING_DAILY_ENGAGEMENT_OBSERVATION"
    assert signal.acceleration_log is None


def test_zero_variance_history_fails_closed_for_z_score():
    as_of = datetime(2026, 8, 19, 23, 0, tzinfo=UTC)
    rows = [_row(as_of - timedelta(days=offset), 100) for offset in range(28)]

    signal = derive_youtube_engagement_baseline(
        rows,
        entity_id="NVDA",
        ticker="NVDA",
        metric=METRIC,
        as_of=as_of,
    )

    assert signal.status == SourceStatus.DATA_ERROR
    assert signal.reason == "ZERO_VARIANCE_ENGAGEMENT_BASELINE"
    assert signal.abnormality_z is None
