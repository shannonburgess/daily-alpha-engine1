"""Point-in-time validation helpers for Behavioral Change research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .behavioral_change import (
    BehavioralEntity,
    BehavioralSnapshot,
    BehavioralSource,
    SourceSignal,
    SourceStatus,
    build_behavioral_snapshot,
)


@dataclass(frozen=True)
class SourceAblationResult:
    omitted_source: BehavioralSource
    complete_sources_before: int
    complete_sources_after: int
    full_score: float | None
    ablated_score: float | None
    score_delta: float | None
    status: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class RecognitionEvent:
    ticker: str
    event_type: str
    first_known_at: datetime
    provenance: str

    def __post_init__(self) -> None:
        _require_aware(self.first_known_at, "first_known_at")
        if not self.ticker.strip() or not self.event_type.strip():
            raise ValueError("ticker and event_type are required")
        if not self.provenance.strip():
            raise ValueError("provenance is required")


@dataclass(frozen=True)
class LeadLagObservation:
    ticker: str
    behavioral_as_of: datetime
    recognition_type: str
    recognition_known_at: datetime
    lead_days: float
    relationship: str
    provenance: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def source_ablation(snapshot: BehavioralSnapshot) -> tuple[SourceAblationResult, ...]:
    """Recompute the composite after omitting each complete source in turn."""
    _require_aware(snapshot.as_of, "snapshot.as_of")
    complete = tuple(
        signal
        for signal in snapshot.source_signals
        if signal.status == SourceStatus.COMPLETE
        and signal.prototype_score is not None
        and signal.persistence is not None
    )
    entity = BehavioralEntity(
        entity_id=snapshot.entity_id,
        ticker=snapshot.ticker,
        version="SOURCE_ABLATION_RESEARCH_ONLY",
    )
    results: list[SourceAblationResult] = []
    for signal in complete:
        remaining = tuple(
            candidate
            for candidate in snapshot.source_signals
            if candidate.source != signal.source
        )
        ablated = build_behavioral_snapshot(entity, remaining, as_of=snapshot.as_of)
        score_delta = None
        if (
            snapshot.behavioral_change_score is not None
            and ablated.behavioral_change_score is not None
        ):
            score_delta = round(
                snapshot.behavioral_change_score - ablated.behavioral_change_score,
                2,
            )
        results.append(
            SourceAblationResult(
                omitted_source=signal.source,
                complete_sources_before=len(complete),
                complete_sources_after=sum(
                    candidate.status == SourceStatus.COMPLETE
                    and candidate.prototype_score is not None
                    and candidate.persistence is not None
                    for candidate in remaining
                ),
                full_score=snapshot.behavioral_change_score,
                ablated_score=ablated.behavioral_change_score,
                score_delta=score_delta,
                status=(
                    "COMPLETE"
                    if ablated.behavioral_change_score is not None
                    else "INSUFFICIENT_INDEPENDENT_SOURCES_AFTER_ABLATION"
                ),
            )
        )
    return tuple(results)


def lead_lag_observations(
    snapshot: BehavioralSnapshot,
    events: tuple[RecognitionEvent, ...],
    *,
    evaluation_cutoff: datetime,
) -> tuple[LeadLagObservation, ...]:
    """Bind only recognition evidence known by an explicit evaluation cutoff."""
    _require_aware(snapshot.as_of, "snapshot.as_of")
    _require_aware(evaluation_cutoff, "evaluation_cutoff")
    cutoff = evaluation_cutoff.astimezone(UTC)
    if snapshot.as_of.astimezone(UTC) > cutoff:
        raise ValueError("BEHAVIORAL_SNAPSHOT_AFTER_EVALUATION_CUTOFF")

    rows: list[LeadLagObservation] = []
    for event in events:
        if event.ticker.upper() != snapshot.ticker.upper():
            raise ValueError("BEHAVIORAL_RECOGNITION_TICKER_MISMATCH")
        known_at = event.first_known_at.astimezone(UTC)
        if known_at > cutoff:
            continue
        delta_days = (known_at - snapshot.as_of.astimezone(UTC)).total_seconds() / 86400.0
        if delta_days > 0:
            relationship = "BEHAVIOR_LEADS_RECOGNITION"
        elif delta_days < 0:
            relationship = "RECOGNITION_PRECEDES_BEHAVIOR"
        else:
            relationship = "SAME_TIME"
        rows.append(
            LeadLagObservation(
                ticker=snapshot.ticker.upper(),
                behavioral_as_of=snapshot.as_of.astimezone(UTC),
                recognition_type=event.event_type,
                recognition_known_at=known_at,
                lead_days=round(delta_days, 6),
                relationship=relationship,
                provenance=event.provenance,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.recognition_known_at, row.recognition_type)))


def complete_source_count(signals: tuple[SourceSignal, ...]) -> int:
    """Count only complete source signals that can participate in a composite."""
    return sum(
        signal.status == SourceStatus.COMPLETE
        and signal.prototype_score is not None
        and signal.persistence is not None
        for signal in signals
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
