"""Point-in-time company-specific baselines for YouTube engagement metrics.

Views, likes and comments are deliberately normalized independently.  This module
only prepares research evidence; it does not feed engagement into the canonical
VIDEO_ATTENTION_ACCELERATION_SCORE and cannot authorize trading.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .behavioral_change import BehavioralObservation, BehavioralSource, SourceStatus

YOUTUBE_ENGAGEMENT_METRICS = frozenset(
    {
        "VIDEO_VIEW_TOTAL_SELECTED_SET",
        "VIDEO_LIKE_TOTAL_SELECTED_SET",
        "VIDEO_COMMENT_TOTAL_SELECTED_SET",
    }
)
BASELINE_DAYS = 28


@dataclass(frozen=True)
class EngagementBaselineSignal:
    entity_id: str
    ticker: str
    metric: str
    as_of: datetime
    status: SourceStatus
    reason: str
    observations_used: int
    complete_daily_points: int
    level_7d_log_mean: float | None
    level_28d_log_mean: float | None
    velocity_7d_log: float | None
    prior_velocity_7d_log: float | None
    acceleration_log: float | None
    abnormality_z: float | None
    persistence: float | None
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def derive_youtube_engagement_baseline(
    observations: Iterable[BehavioralObservation],
    *,
    entity_id: str,
    ticker: str,
    metric: str,
    as_of: datetime,
) -> EngagementBaselineSignal:
    """Derive one engagement baseline from 28 complete point-in-time daily levels.

    Missing dates are never converted to zero.  Daily engagement totals are log1p
    transformed before velocity/acceleration calculations so company scale does not
    dominate the normalization.  Each metric family is handled independently.
    """
    _require_aware(as_of)
    if metric not in YOUTUBE_ENGAGEMENT_METRICS:
        raise ValueError("unsupported YouTube engagement metric")
    entity = entity_id.strip()
    symbol = ticker.strip().upper()
    if not entity or not symbol:
        raise ValueError("entity_id and ticker are required")

    cutoff = as_of.astimezone(UTC)
    matching = [
        row
        for row in observations
        if row.source == BehavioralSource.YOUTUBE
        and row.entity_id == entity
        and row.ticker.upper() == symbol
        and row.metric == metric
        and row.source_timestamp <= cutoff
        and row.observed_at <= cutoff
    ]
    daily, conflict = _daily_levels(matching)
    if conflict:
        return _unavailable(
            entity,
            symbol,
            metric,
            cutoff,
            SourceStatus.DATA_ERROR,
            "CONFLICTING_DAILY_ENGAGEMENT_OBSERVATION",
            len(matching),
            len(daily),
        )

    as_of_day = cutoff.date()
    required_days = tuple(
        as_of_day - timedelta(days=offset) for offset in range(BASELINE_DAYS)
    )
    complete = sum(day in daily for day in required_days)
    if complete != BASELINE_DAYS:
        return _unavailable(
            entity,
            symbol,
            metric,
            cutoff,
            SourceStatus.DATA_ERROR,
            "INSUFFICIENT_COMPLETE_DAILY_ENGAGEMENT_BASELINE",
            len(matching),
            complete,
        )

    log_levels = {day: math.log1p(daily[day]) for day in required_days}
    current7 = [log_levels[as_of_day - timedelta(days=i)] for i in range(7)]
    prior7 = [log_levels[as_of_day - timedelta(days=i)] for i in range(7, 14)]
    prior_prior7 = [
        log_levels[as_of_day - timedelta(days=i)] for i in range(14, 21)
    ]
    all28 = [log_levels[day] for day in required_days]
    current_mean = statistics.fmean(current7)
    prior_mean = statistics.fmean(prior7)
    prior_prior_mean = statistics.fmean(prior_prior7)
    velocity = current_mean - prior_mean
    prior_velocity = prior_mean - prior_prior_mean
    acceleration = velocity - prior_velocity

    prior27 = [
        log_levels[as_of_day - timedelta(days=i)] for i in range(1, BASELINE_DAYS)
    ]
    baseline_mean = statistics.fmean(prior27)
    baseline_std = statistics.pstdev(prior27)
    if baseline_std == 0:
        return _unavailable(
            entity,
            symbol,
            metric,
            cutoff,
            SourceStatus.DATA_ERROR,
            "ZERO_VARIANCE_ENGAGEMENT_BASELINE",
            len(matching),
            complete,
        )
    abnormality = (log_levels[as_of_day] - baseline_mean) / baseline_std
    prior_median = statistics.median(
        [log_levels[as_of_day - timedelta(days=i)] for i in range(7, BASELINE_DAYS)]
    )
    persistence = sum(value > prior_median for value in current7) / 7.0

    return EngagementBaselineSignal(
        entity_id=entity,
        ticker=symbol,
        metric=metric,
        as_of=cutoff,
        status=SourceStatus.COMPLETE,
        reason="",
        observations_used=len(matching),
        complete_daily_points=complete,
        level_7d_log_mean=current_mean,
        level_28d_log_mean=statistics.fmean(all28),
        velocity_7d_log=velocity,
        prior_velocity_7d_log=prior_velocity,
        acceleration_log=acceleration,
        abnormality_z=abnormality,
        persistence=persistence,
    )


def _daily_levels(
    observations: Iterable[BehavioralObservation],
) -> tuple[dict[date, float], bool]:
    daily: dict[date, float] = {}
    conflict = False
    for row in sorted(observations, key=lambda item: item.source_timestamp):
        day = row.source_timestamp.astimezone(UTC).date()
        prior = daily.get(day)
        if prior is not None and prior != row.raw_level:
            conflict = True
            continue
        daily[day] = row.raw_level
    return daily, conflict


def _unavailable(
    entity_id: str,
    ticker: str,
    metric: str,
    as_of: datetime,
    status: SourceStatus,
    reason: str,
    observations_used: int,
    complete_daily_points: int,
) -> EngagementBaselineSignal:
    return EngagementBaselineSignal(
        entity_id=entity_id,
        ticker=ticker,
        metric=metric,
        as_of=as_of,
        status=status,
        reason=reason,
        observations_used=observations_used,
        complete_daily_points=complete_daily_points,
        level_7d_log_mean=None,
        level_28d_log_mean=None,
        velocity_7d_log=None,
        prior_velocity_7d_log=None,
        acceleration_log=None,
        abnormality_z=None,
        persistence=None,
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
