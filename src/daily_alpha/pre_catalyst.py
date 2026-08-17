"""Point-in-time research model for public pre-catalyst drift.

The central invariant is no lookahead: a scheduled event may only enter Daily Alpha
research on or after ``event_known_date``, the first date the event was publicly
known. This module is research-only and cannot authorize a paper or live trade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class CatalystType(StrEnum):
    INVESTOR_DAY = "INVESTOR_DAY"
    CONFERENCE = "CONFERENCE"
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    ANALYST_EVENT = "ANALYST_EVENT"
    REGULATORY_MILESTONE = "REGULATORY_MILESTONE"
    OTHER_PUBLIC_EVENT = "OTHER_PUBLIC_EVENT"


class PreCatalystClass(StrEnum):
    NOT_PUBLICLY_KNOWN = "NOT_PUBLICLY_KNOWN"
    OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
    PRE_CATALYST_WATCH = "PRE_CATALYST_WATCH"
    PRE_CATALYST_RUN = "PRE_CATALYST_RUN"


@dataclass(frozen=True)
class PublicCatalyst:
    ticker: str
    event_type: CatalystType
    event_date: date
    event_known_date: date
    source_id: str


@dataclass(frozen=True)
class PreCatalystObservation:
    as_of_date: date
    sessions_until_event: int
    excess_return_10d_pct: float
    relative_strength_acceleration: float
    relative_volume: float
    distance_to_20d_high_pct: float
    bullish_trend_state: bool
    options_positioning_score: float = 0.0


@dataclass(frozen=True)
class PreCatalystResult:
    classification: PreCatalystClass
    score: float
    event_visible: bool
    research_eligible: bool
    reason_codes: tuple[str, ...]


def classify_pre_catalyst(
    event: PublicCatalyst,
    observation: PreCatalystObservation,
    *,
    min_sessions: int = 1,
    max_sessions: int = 20,
    run_score: float = 70.0,
) -> PreCatalystResult:
    """Classify a public catalyst using only information knowable as of the observation."""
    _validate_event(event)
    _validate_observation(observation)
    if min_sessions < 1 or max_sessions < min_sessions:
        raise ValueError("session window must satisfy 1 <= min <= max")
    if not 0.0 <= run_score <= 100.0:
        raise ValueError("run_score must be between 0 and 100")

    if observation.as_of_date < event.event_known_date:
        return PreCatalystResult(
            classification=PreCatalystClass.NOT_PUBLICLY_KNOWN,
            score=0.0,
            event_visible=False,
            research_eligible=False,
            reason_codes=("EVENT_NOT_YET_PUBLIC",),
        )

    if observation.as_of_date >= event.event_date or not (
        min_sessions <= observation.sessions_until_event <= max_sessions
    ):
        return PreCatalystResult(
            classification=PreCatalystClass.OUTSIDE_WINDOW,
            score=0.0,
            event_visible=True,
            research_eligible=False,
            reason_codes=("OUTSIDE_PRE_CATALYST_WINDOW",),
        )

    score, reasons = _anticipation_score(observation)
    classification = (
        PreCatalystClass.PRE_CATALYST_RUN
        if score >= run_score
        else PreCatalystClass.PRE_CATALYST_WATCH
    )
    return PreCatalystResult(
        classification=classification,
        score=score,
        event_visible=True,
        research_eligible=True,
        reason_codes=tuple(reasons),
    )


def _anticipation_score(observation: PreCatalystObservation) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if observation.excess_return_10d_pct > 0:
        score += min(observation.excess_return_10d_pct * 2.0, 20.0)
        reasons.append("POSITIVE_10D_EXCESS_RETURN")
    if observation.relative_strength_acceleration > 0:
        score += min(observation.relative_strength_acceleration * 20.0, 20.0)
        reasons.append("RELATIVE_STRENGTH_ACCELERATING")
    if observation.relative_volume >= 1.25:
        score += min((observation.relative_volume - 1.0) * 20.0, 15.0)
        reasons.append("VOLUME_ACCUMULATION")
    if observation.distance_to_20d_high_pct <= 2.0:
        score += 15.0
        reasons.append("NEAR_20D_HIGH")
    if observation.bullish_trend_state:
        score += 15.0
        reasons.append("BULLISH_TREND_STATE")
    if observation.options_positioning_score > 0:
        score += min(observation.options_positioning_score, 15.0)
        reasons.append("BULLISH_OPTIONS_POSITIONING")

    return round(min(score, 100.0), 2), reasons


def _validate_event(event: PublicCatalyst) -> None:
    if not event.ticker.strip():
        raise ValueError("ticker is required")
    if event.event_known_date > event.event_date:
        raise ValueError("event_known_date cannot be after event_date")
    if not event.source_id.strip():
        raise ValueError("source_id is required for point-in-time auditability")


def _validate_observation(observation: PreCatalystObservation) -> None:
    if observation.sessions_until_event < 0:
        raise ValueError("sessions_until_event must be non-negative")
    if observation.relative_volume < 0:
        raise ValueError("relative_volume must be non-negative")
    if not 0.0 <= observation.options_positioning_score <= 100.0:
        raise ValueError("options_positioning_score must be between 0 and 100")
