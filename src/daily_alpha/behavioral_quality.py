"""Research-only source freshness and extreme-event controls for Behavioral Change.

These diagnostics are deliberately separate from factor scoring. They provide a
point-in-time, provider-neutral quality contract so stale evidence or one extreme
observation cannot silently become a promotion signal.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from .behavioral_change import BehavioralObservation, BehavioralSource, SourceStatus


@dataclass(frozen=True)
class BehavioralQualityAssessment:
    source: BehavioralSource
    entity_id: str
    ticker: str
    metric: str
    as_of: datetime
    status: SourceStatus
    reason: str
    observations_used: int
    newest_source_timestamp: datetime | None
    freshness_age_hours: float | None
    freshness_limit_hours: float
    fresh: bool
    daily_points: int
    latest_raw_level: float | None
    winsorized_latest_level: float | None
    winsor_lower_bound: float | None
    winsor_upper_bound: float | None
    extreme_event_flag: bool | None
    extreme_event_reason: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def assess_behavioral_quality(
    observations: Iterable[BehavioralObservation],
    *,
    source: BehavioralSource,
    entity_id: str,
    ticker: str,
    metric: str,
    as_of: datetime,
    freshness_limit_hours: float,
    min_prior_daily_points: int = 14,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
) -> BehavioralQualityAssessment:
    """Assess source freshness and one-day extreme-event risk without lookahead.

    Only observations known at ``as_of`` are consumed.  Extreme-event bounds are
    derived from prior daily levels only; the current day is never allowed to set
    its own winsorization boundary.  The result is research evidence and is not
    connected to trade authorization or production ranking.
    """
    _require_aware(as_of, "as_of")
    if not math.isfinite(freshness_limit_hours) or freshness_limit_hours <= 0:
        raise ValueError("freshness_limit_hours must be finite and positive")
    if min_prior_daily_points < 3:
        raise ValueError("min_prior_daily_points must be at least 3")
    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise ValueError("quantile bounds must satisfy 0 <= lower < upper <= 1")

    entity = entity_id.strip()
    symbol = ticker.strip().upper()
    metric_name = metric.strip()
    if not entity or not symbol or not metric_name:
        raise ValueError("entity_id, ticker and metric are required")

    cutoff = as_of.astimezone(UTC)
    rows = [
        row
        for row in observations
        if row.source == source
        and row.entity_id == entity
        and row.ticker.upper() == symbol
        and row.metric == metric_name
        and row.source_timestamp <= cutoff
        and row.observed_at <= cutoff
    ]
    rows, conflict = _dedupe(rows)
    if conflict:
        return _unavailable(
            source=source,
            entity_id=entity,
            ticker=symbol,
            metric=metric_name,
            as_of=cutoff,
            freshness_limit_hours=freshness_limit_hours,
            status=SourceStatus.DATA_ERROR,
            reason="CONFLICTING_DUPLICATE_BEHAVIORAL_OBSERVATION",
            observations_used=len(rows),
        )
    if not rows:
        return _unavailable(
            source=source,
            entity_id=entity,
            ticker=symbol,
            metric=metric_name,
            as_of=cutoff,
            freshness_limit_hours=freshness_limit_hours,
            status=SourceStatus.SOURCE_UNAVAILABLE,
            reason="NO_POINT_IN_TIME_OBSERVATIONS",
            observations_used=0,
        )

    newest = max(row.source_timestamp for row in rows).astimezone(UTC)
    freshness_age = (cutoff - newest).total_seconds() / 3600.0
    if freshness_age < 0:
        return _unavailable(
            source=source,
            entity_id=entity,
            ticker=symbol,
            metric=metric_name,
            as_of=cutoff,
            freshness_limit_hours=freshness_limit_hours,
            status=SourceStatus.DATA_ERROR,
            reason="SOURCE_TIMESTAMP_AFTER_AS_OF",
            observations_used=len(rows),
        )

    daily = _daily_levels(rows)
    latest_day = max(daily)
    latest_level = daily[latest_day]
    prior_levels = [value for day, value in sorted(daily.items()) if day < latest_day]

    if freshness_age > freshness_limit_hours:
        return BehavioralQualityAssessment(
            source=source,
            entity_id=entity,
            ticker=symbol,
            metric=metric_name,
            as_of=cutoff,
            status=SourceStatus.SOURCE_UNAVAILABLE,
            reason="STALE_SOURCE_EVIDENCE",
            observations_used=len(rows),
            newest_source_timestamp=newest,
            freshness_age_hours=round(freshness_age, 6),
            freshness_limit_hours=freshness_limit_hours,
            fresh=False,
            daily_points=len(daily),
            latest_raw_level=latest_level,
            winsorized_latest_level=None,
            winsor_lower_bound=None,
            winsor_upper_bound=None,
            extreme_event_flag=None,
            extreme_event_reason="STALE_SOURCE_NOT_EVALUATED_FOR_EXTREME_EVENT",
        )

    if len(prior_levels) < min_prior_daily_points:
        return BehavioralQualityAssessment(
            source=source,
            entity_id=entity,
            ticker=symbol,
            metric=metric_name,
            as_of=cutoff,
            status=SourceStatus.COMPLETE,
            reason="",
            observations_used=len(rows),
            newest_source_timestamp=newest,
            freshness_age_hours=round(freshness_age, 6),
            freshness_limit_hours=freshness_limit_hours,
            fresh=True,
            daily_points=len(daily),
            latest_raw_level=latest_level,
            winsorized_latest_level=None,
            winsor_lower_bound=None,
            winsor_upper_bound=None,
            extreme_event_flag=None,
            extreme_event_reason="INSUFFICIENT_PRIOR_HISTORY_FOR_EXTREME_EVENT_CONTROL",
        )

    lower = _quantile(prior_levels, lower_quantile)
    upper = _quantile(prior_levels, upper_quantile)
    winsorized = min(max(latest_level, lower), upper)
    extreme = latest_level < lower or latest_level > upper
    return BehavioralQualityAssessment(
        source=source,
        entity_id=entity,
        ticker=symbol,
        metric=metric_name,
        as_of=cutoff,
        status=SourceStatus.COMPLETE,
        reason="",
        observations_used=len(rows),
        newest_source_timestamp=newest,
        freshness_age_hours=round(freshness_age, 6),
        freshness_limit_hours=freshness_limit_hours,
        fresh=True,
        daily_points=len(daily),
        latest_raw_level=latest_level,
        winsorized_latest_level=winsorized,
        winsor_lower_bound=lower,
        winsor_upper_bound=upper,
        extreme_event_flag=extreme,
        extreme_event_reason="" if not extreme else "LATEST_LEVEL_OUTSIDE_PRIOR_WINSOR_BOUNDS",
    )


def _dedupe(
    observations: Iterable[BehavioralObservation],
) -> tuple[list[BehavioralObservation], bool]:
    unique: dict[tuple[str, str, str, str, str], BehavioralObservation] = {}
    conflict = False
    for row in observations:
        prior = unique.get(row.identity)
        if prior is not None and prior.raw_level != row.raw_level:
            conflict = True
            continue
        unique[row.identity] = row
    return list(unique.values()), conflict


def _daily_levels(observations: Iterable[BehavioralObservation]) -> dict[date, float]:
    daily: dict[date, float] = {}
    for row in observations:
        day = row.source_timestamp.astimezone(UTC).date()
        daily[day] = daily.get(day, 0.0) + row.raw_level
    return daily


def _quantile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index])


def _unavailable(
    *,
    source: BehavioralSource,
    entity_id: str,
    ticker: str,
    metric: str,
    as_of: datetime,
    freshness_limit_hours: float,
    status: SourceStatus,
    reason: str,
    observations_used: int,
) -> BehavioralQualityAssessment:
    return BehavioralQualityAssessment(
        source=source,
        entity_id=entity_id,
        ticker=ticker,
        metric=metric,
        as_of=as_of,
        status=status,
        reason=reason,
        observations_used=observations_used,
        newest_source_timestamp=None,
        freshness_age_hours=None,
        freshness_limit_hours=freshness_limit_hours,
        fresh=False,
        daily_points=0,
        latest_raw_level=None,
        winsorized_latest_level=None,
        winsor_lower_bound=None,
        winsor_upper_bound=None,
        extreme_event_flag=None,
        extreme_event_reason="NOT_EVALUATED",
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
