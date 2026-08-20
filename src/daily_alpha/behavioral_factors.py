"""Named research-factor contract for Behavioral Change evidence.

These outputs are descriptive research factors only. They cannot authorize a trade and
must remain downstream of point-in-time source normalization and upstream of the
normal Daily Alpha execution gates.
"""

from __future__ import annotations

from dataclasses import dataclass

from .behavioral_change import BehavioralSnapshot, BehavioralSource, SourceSignal, SourceStatus


@dataclass(frozen=True)
class BehavioralResearchFactors:
    search_acceleration_score: float | None
    video_attention_acceleration_score: float | None
    web_traffic_acceleration_score: float | None
    cross_source_confirmation: float
    persistence_score: float | None
    behavioral_change_score: float | None
    information_imbalance_score: float | None
    source_raw_acceleration: tuple[tuple[str, float | None], ...]
    unavailable_reasons: tuple[tuple[str, str], ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def build_behavioral_research_factors(
    snapshot: BehavioralSnapshot,
) -> BehavioralResearchFactors:
    """Project a canonical snapshot into explicitly named research-only factors."""
    signals = {signal.source: signal for signal in snapshot.source_signals}
    reasons: dict[str, str] = {}

    search = _source_acceleration_factor(
        signals.get(BehavioralSource.GOOGLE_TRENDS),
        factor_name="SEARCH_ACCELERATION_SCORE",
        reasons=reasons,
    )
    video = _source_acceleration_factor(
        signals.get(BehavioralSource.YOUTUBE),
        factor_name="VIDEO_ATTENTION_ACCELERATION_SCORE",
        reasons=reasons,
    )
    web = _source_acceleration_factor(
        signals.get(BehavioralSource.SIMILARWEB),
        factor_name="WEB_TRAFFIC_ACCELERATION_SCORE",
        reasons=reasons,
    )

    complete_persistence = [
        signal.persistence
        for signal in snapshot.source_signals
        if signal.status == SourceStatus.COMPLETE and signal.persistence is not None
    ]
    persistence_score = (
        round(100.0 * sum(complete_persistence) / len(complete_persistence), 2)
        if complete_persistence
        else None
    )
    if persistence_score is None:
        reasons["PERSISTENCE_SCORE"] = "NO_COMPLETE_SOURCE_PERSISTENCE"

    if snapshot.behavioral_change_score is None:
        reasons["BEHAVIORAL_CHANGE_SCORE"] = "INSUFFICIENT_INDEPENDENT_COMPLETE_SOURCES"
    if snapshot.information_imbalance_score is None:
        reasons["INFORMATION_IMBALANCE_SCORE"] = snapshot.information_imbalance_reason

    raw_acceleration = tuple(
        sorted(
            (
                signal.source.value,
                signal.acceleration if signal.status == SourceStatus.COMPLETE else None,
            )
            for signal in snapshot.source_signals
        )
    )

    return BehavioralResearchFactors(
        search_acceleration_score=search,
        video_attention_acceleration_score=video,
        web_traffic_acceleration_score=web,
        cross_source_confirmation=snapshot.cross_source_confirmation,
        persistence_score=persistence_score,
        behavioral_change_score=snapshot.behavioral_change_score,
        information_imbalance_score=snapshot.information_imbalance_score,
        source_raw_acceleration=raw_acceleration,
        unavailable_reasons=tuple(sorted(reasons.items())),
    )


def _source_acceleration_factor(
    signal: SourceSignal | None,
    *,
    factor_name: str,
    reasons: dict[str, str],
) -> float | None:
    if signal is None:
        reasons[factor_name] = "SOURCE_NOT_PRESENT"
        return None
    if signal.status != SourceStatus.COMPLETE or signal.acceleration is None:
        reasons[factor_name] = signal.reason or signal.status.value
        return None
    return _bounded_acceleration_score(signal.acceleration)


def _bounded_acceleration_score(value: float) -> float:
    """Use the same frozen acceleration bounds as the prototype source scorer."""
    low = -0.25
    high = 0.50
    return round(max(0.0, min(100.0, 100.0 * (value - low) / (high - low))), 2)
