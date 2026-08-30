"""Point-in-time Wall Street recognition and information-imbalance research contracts.

Behavioral Change is intentionally separated from conventional market recognition.
This module provides a provider-neutral normalization boundary for analyst/consensus
recognition evidence and computes an Information Imbalance score only when both the
Behavioral Change composite and independent recognition evidence are complete.

The outputs are research-only. They cannot authorize ranking promotion, paper/live
execution, or bypass any Daily Alpha execution gate.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .behavioral_change import BehavioralSnapshot


class RecognitionFamily(StrEnum):
    """Wall Street recognition families kept separate from core market factors."""

    ANALYST_REVISIONS = "ANALYST_REVISIONS"
    CONSENSUS_ESTIMATES = "CONSENSUS_ESTIMATES"
    PRICE_TARGET_REVISIONS = "PRICE_TARGET_REVISIONS"


class RecognitionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class WallStreetRecognitionObservation:
    """One provider-normalized recognition observation known at a fixed timestamp."""

    ticker: str
    family: RecognitionFamily
    provider_id: str
    as_of: datetime
    source_timestamp: datetime
    score: float
    provenance: str
    version: str

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        _require_aware(self.source_timestamp, "source_timestamp")
        if self.source_timestamp > self.as_of:
            raise ValueError("source_timestamp cannot be after as_of")
        if not self.ticker.strip():
            raise ValueError("ticker is required")
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.provenance.strip():
            raise ValueError("provenance is required")
        if not self.version.strip():
            raise ValueError("version is required")
        if not math.isfinite(self.score) or not 0.0 <= self.score <= 100.0:
            raise ValueError("score must be finite and in [0, 100]")

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.ticker.upper(),
            self.family.value,
            self.provider_id,
            self.as_of.astimezone(UTC).isoformat(),
        )


@dataclass(frozen=True)
class WallStreetRecognitionSnapshot:
    ticker: str
    as_of: datetime
    status: RecognitionStatus
    reason: str
    family_scores: tuple[tuple[str, float], ...]
    independent_families: int
    provider_observations: int
    wall_street_recognition_score: float | None
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class InformationImbalanceResult:
    ticker: str
    as_of: datetime
    behavioral_change_score: float | None
    wall_street_recognition_score: float | None
    information_imbalance_score: float | None
    unrecognized_fraction: float | None
    reason: str
    formula_version: str = "BEHAVIOR_X_UNRECOGNIZED_V1"
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def build_wall_street_recognition_snapshot(
    observations: Iterable[WallStreetRecognitionObservation],
    *,
    ticker: str,
    as_of: datetime,
    min_independent_families: int = 2,
) -> WallStreetRecognitionSnapshot:
    """Aggregate exact-time recognition evidence without carrying history forward.

    The caller must supply provider-normalized daily observations whose ``as_of``
    exactly matches the requested snapshot boundary. Evidence from another timestamp
    is not silently carried forward. Multiple providers inside one family are averaged
    first so provider count cannot overweight a recognition family.
    """
    _require_aware(as_of, "as_of")
    if not ticker.strip():
        raise ValueError("ticker is required")
    if min_independent_families < 2:
        raise ValueError("min_independent_families must be at least 2")

    target_ticker = ticker.upper()
    target_as_of = as_of.astimezone(UTC)
    rows = _dedupe_observations(observations)

    relevant: list[WallStreetRecognitionObservation] = []
    for row in rows:
        if row.ticker.upper() != target_ticker:
            raise ValueError("recognition observation ticker mismatch")
        if row.as_of.astimezone(UTC) > target_as_of:
            raise ValueError("recognition observation is after snapshot as_of")
        if row.as_of.astimezone(UTC) != target_as_of:
            continue
        relevant.append(row)

    by_family: dict[RecognitionFamily, list[float]] = {}
    for row in relevant:
        by_family.setdefault(row.family, []).append(row.score)

    family_scores = tuple(
        sorted(
            (family.value, round(statistics.fmean(scores), 4))
            for family, scores in by_family.items()
        )
    )
    independent_families = len(family_scores)
    if independent_families < min_independent_families:
        return WallStreetRecognitionSnapshot(
            ticker=target_ticker,
            as_of=target_as_of,
            status=RecognitionStatus.SOURCE_UNAVAILABLE,
            reason="INSUFFICIENT_INDEPENDENT_RECOGNITION_FAMILIES",
            family_scores=family_scores,
            independent_families=independent_families,
            provider_observations=len(relevant),
            wall_street_recognition_score=None,
        )

    score = round(statistics.fmean(value for _, value in family_scores), 2)
    return WallStreetRecognitionSnapshot(
        ticker=target_ticker,
        as_of=target_as_of,
        status=RecognitionStatus.COMPLETE,
        reason="",
        family_scores=family_scores,
        independent_families=independent_families,
        provider_observations=len(relevant),
        wall_street_recognition_score=score,
    )


def build_information_imbalance(
    behavioral_snapshot: BehavioralSnapshot,
    recognition_snapshot: WallStreetRecognitionSnapshot | None,
) -> InformationImbalanceResult:
    """Measure strong Behavioral Change that conventional recognition has not absorbed.

    V1 deliberately uses a transparent bounded formula rather than tuned weights:
    ``BehavioralChange * (1 - WallStreetRecognition / 100)``. A score is unavailable
    unless the Behavioral composite already exists and recognition is COMPLETE.
    """
    _require_aware(behavioral_snapshot.as_of, "behavioral_snapshot.as_of")
    ticker = behavioral_snapshot.ticker.upper()
    as_of = behavioral_snapshot.as_of.astimezone(UTC)

    if behavioral_snapshot.trading_authorized is not False:
        raise ValueError("behavioral snapshot trading_authorized must remain false")
    if behavioral_snapshot.live_trading_enabled is not False:
        raise ValueError("behavioral snapshot live_trading_enabled must remain false")

    behavioral_score = behavioral_snapshot.behavioral_change_score
    if behavioral_score is None:
        return InformationImbalanceResult(
            ticker=ticker,
            as_of=as_of,
            behavioral_change_score=None,
            wall_street_recognition_score=None,
            information_imbalance_score=None,
            unrecognized_fraction=None,
            reason="BEHAVIORAL_CHANGE_SCORE_UNAVAILABLE",
        )
    if not math.isfinite(behavioral_score) or not 0.0 <= behavioral_score <= 100.0:
        raise ValueError("behavioral_change_score must be finite and in [0, 100]")

    if recognition_snapshot is None:
        return InformationImbalanceResult(
            ticker=ticker,
            as_of=as_of,
            behavioral_change_score=behavioral_score,
            wall_street_recognition_score=None,
            information_imbalance_score=None,
            unrecognized_fraction=None,
            reason="WALL_STREET_RECOGNITION_NOT_CONNECTED",
        )
    _validate_recognition_snapshot(recognition_snapshot, ticker=ticker, as_of=as_of)

    recognition_score = recognition_snapshot.wall_street_recognition_score
    if recognition_snapshot.status != RecognitionStatus.COMPLETE or recognition_score is None:
        return InformationImbalanceResult(
            ticker=ticker,
            as_of=as_of,
            behavioral_change_score=behavioral_score,
            wall_street_recognition_score=None,
            information_imbalance_score=None,
            unrecognized_fraction=None,
            reason=recognition_snapshot.reason or recognition_snapshot.status.value,
        )

    unrecognized_fraction = round(1.0 - recognition_score / 100.0, 6)
    imbalance = round(behavioral_score * unrecognized_fraction, 2)
    return InformationImbalanceResult(
        ticker=ticker,
        as_of=as_of,
        behavioral_change_score=behavioral_score,
        wall_street_recognition_score=recognition_score,
        information_imbalance_score=imbalance,
        unrecognized_fraction=unrecognized_fraction,
        reason="",
    )


def _dedupe_observations(
    observations: Iterable[WallStreetRecognitionObservation],
) -> tuple[WallStreetRecognitionObservation, ...]:
    unique: dict[tuple[str, str, str, str], WallStreetRecognitionObservation] = {}
    for row in observations:
        prior = unique.get(row.identity)
        if prior is not None and prior != row:
            raise ValueError("CONFLICTING_DUPLICATE_RECOGNITION_OBSERVATION")
        unique[row.identity] = row
    return tuple(sorted(unique.values(), key=lambda row: row.identity))


def _validate_recognition_snapshot(
    snapshot: WallStreetRecognitionSnapshot,
    *,
    ticker: str,
    as_of: datetime,
) -> None:
    _require_aware(snapshot.as_of, "recognition_snapshot.as_of")
    if snapshot.ticker.upper() != ticker:
        raise ValueError("recognition snapshot ticker mismatch")
    if snapshot.as_of.astimezone(UTC) != as_of:
        raise ValueError("recognition snapshot as_of mismatch")
    if snapshot.promotion_authorized is not False:
        raise ValueError("recognition snapshot promotion_authorized must remain false")
    if snapshot.trading_authorized is not False:
        raise ValueError("recognition snapshot trading_authorized must remain false")
    if snapshot.live_trading_enabled is not False:
        raise ValueError("recognition snapshot live_trading_enabled must remain false")
    score = snapshot.wall_street_recognition_score
    if score is not None and (not math.isfinite(score) or not 0.0 <= score <= 100.0):
        raise ValueError("wall_street_recognition_score must be finite and in [0, 100]")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
