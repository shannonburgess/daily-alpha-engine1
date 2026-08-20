"""Research-only orthogonality diagnostics for Behavioral Change factors.

Behavioral evidence must not silently duplicate the existing Daily Alpha core factors.
This module measures point-in-time cross-sectional rank correlation against the four
explicit core families called out by the research contract. The result is diagnostic
only and cannot promote, rank, size, or authorize a trade.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class CoreFactorFamily(StrEnum):
    OVTLYR = "OVTLYR"
    EARNINGS_REVISIONS = "EARNINGS_REVISIONS"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    SECTOR_ROTATION = "SECTOR_ROTATION"


@dataclass(frozen=True)
class BehavioralFactorPoint:
    ticker: str
    as_of: datetime
    source_timestamp: datetime
    behavioral_change_score: float
    provenance: str

    def __post_init__(self) -> None:
        _validate_point(
            ticker=self.ticker,
            as_of=self.as_of,
            source_timestamp=self.source_timestamp,
            value=self.behavioral_change_score,
            provenance=self.provenance,
        )

    @property
    def identity(self) -> tuple[str, str]:
        return self.ticker.upper(), self.as_of.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class CoreFactorPoint:
    ticker: str
    family: CoreFactorFamily
    as_of: datetime
    source_timestamp: datetime
    value: float
    provenance: str

    def __post_init__(self) -> None:
        _validate_point(
            ticker=self.ticker,
            as_of=self.as_of,
            source_timestamp=self.source_timestamp,
            value=self.value,
            provenance=self.provenance,
        )

    @property
    def identity(self) -> tuple[str, str, str]:
        return (
            self.family.value,
            self.ticker.upper(),
            self.as_of.astimezone(UTC).isoformat(),
        )


@dataclass(frozen=True)
class OrthogonalityDiagnostic:
    family: CoreFactorFamily
    evaluation_cutoff: datetime
    paired_observations: int
    spearman_rank_correlation: float | None
    absolute_rank_correlation: float | None
    redundancy_threshold: float
    redundancy_risk: bool | None
    status: str
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def behavioral_core_orthogonality(
    behavioral_points: Iterable[BehavioralFactorPoint],
    core_points: Iterable[CoreFactorPoint],
    *,
    evaluation_cutoff: datetime,
    min_paired_observations: int = 8,
    redundancy_threshold: float = 0.80,
) -> tuple[OrthogonalityDiagnostic, ...]:
    """Measure same-time cross-sectional Behavioral overlap with core factor families.

    Only evidence whose point-in-time ``as_of`` is at or before ``evaluation_cutoff``
    participates. Behavioral and core points must join on the exact ticker and ``as_of``
    timestamp; the function never carries values forward or reconstructs missing history.
    Conflicting duplicate identities fail closed.
    """
    _require_aware(evaluation_cutoff, "evaluation_cutoff")
    if min_paired_observations < 3:
        raise ValueError("min_paired_observations must be at least 3")
    if not 0.0 < redundancy_threshold <= 1.0:
        raise ValueError("redundancy_threshold must be in (0, 1]")

    cutoff = evaluation_cutoff.astimezone(UTC)
    behavioral = _dedupe_behavioral(
        point for point in behavioral_points if point.as_of.astimezone(UTC) <= cutoff
    )
    core = _dedupe_core(
        point for point in core_points if point.as_of.astimezone(UTC) <= cutoff
    )

    results: list[OrthogonalityDiagnostic] = []
    for family in CoreFactorFamily:
        family_points = {
            (point.ticker.upper(), point.as_of.astimezone(UTC).isoformat()): point
            for point in core.values()
            if point.family == family
        }
        pairs = [
            (point.behavioral_change_score, family_points[identity].value)
            for identity, point in behavioral.items()
            if identity in family_points
        ]
        results.append(
            _diagnostic_for_family(
                family,
                pairs,
                evaluation_cutoff=cutoff,
                min_paired_observations=min_paired_observations,
                redundancy_threshold=redundancy_threshold,
            )
        )
    return tuple(results)


def _diagnostic_for_family(
    family: CoreFactorFamily,
    pairs: list[tuple[float, float]],
    *,
    evaluation_cutoff: datetime,
    min_paired_observations: int,
    redundancy_threshold: float,
) -> OrthogonalityDiagnostic:
    sample_size = len(pairs)
    if sample_size < min_paired_observations:
        return OrthogonalityDiagnostic(
            family=family,
            evaluation_cutoff=evaluation_cutoff,
            paired_observations=sample_size,
            spearman_rank_correlation=None,
            absolute_rank_correlation=None,
            redundancy_threshold=redundancy_threshold,
            redundancy_risk=None,
            status="INSUFFICIENT_POINT_IN_TIME_OVERLAP",
        )

    behavioral_values = [pair[0] for pair in pairs]
    core_values = [pair[1] for pair in pairs]
    behavioral_ranks = _average_ranks(behavioral_values)
    core_ranks = _average_ranks(core_values)
    correlation = _pearson(behavioral_ranks, core_ranks)
    if correlation is None:
        return OrthogonalityDiagnostic(
            family=family,
            evaluation_cutoff=evaluation_cutoff,
            paired_observations=sample_size,
            spearman_rank_correlation=None,
            absolute_rank_correlation=None,
            redundancy_threshold=redundancy_threshold,
            redundancy_risk=None,
            status="ZERO_VARIANCE_POINT_IN_TIME_SAMPLE",
        )

    correlation = round(correlation, 6)
    absolute = round(abs(correlation), 6)
    redundant = absolute >= redundancy_threshold
    return OrthogonalityDiagnostic(
        family=family,
        evaluation_cutoff=evaluation_cutoff,
        paired_observations=sample_size,
        spearman_rank_correlation=correlation,
        absolute_rank_correlation=absolute,
        redundancy_threshold=redundancy_threshold,
        redundancy_risk=redundant,
        status="REDUNDANCY_RISK" if redundant else "ORTHOGONALITY_NOT_REJECTED",
    )


def _dedupe_behavioral(
    points: Iterable[BehavioralFactorPoint],
) -> dict[tuple[str, str], BehavioralFactorPoint]:
    result: dict[tuple[str, str], BehavioralFactorPoint] = {}
    for point in points:
        prior = result.get(point.identity)
        if prior is not None and prior != point:
            raise ValueError("CONFLICTING_DUPLICATE_BEHAVIORAL_FACTOR_POINT")
        result[point.identity] = point
    return result


def _dedupe_core(points: Iterable[CoreFactorPoint]) -> dict[tuple[str, str, str], CoreFactorPoint]:
    result: dict[tuple[str, str, str], CoreFactorPoint] = {}
    for point in points:
        prior = result.get(point.identity)
        if prior is not None and prior != point:
            raise ValueError("CONFLICTING_DUPLICATE_CORE_FACTOR_POINT")
        result[point.identity] = point
    return result


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position + 1
        value = values[order[position]]
        while end < len(order) and values[order[end]] == value:
            end += 1
        average_rank = (position + 1 + end) / 2.0
        for ordered_index in order[position:end]:
            ranks[ordered_index] = average_rank
        position = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        raise ValueError("rank vectors must be non-empty and the same length")
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    left_norm = math.sqrt(sum(value * value for value in left_delta))
    right_norm = math.sqrt(sum(value * value for value in right_delta))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return sum(a * b for a, b in zip(left_delta, right_delta, strict=True)) / (
        left_norm * right_norm
    )


def _validate_point(
    *,
    ticker: str,
    as_of: datetime,
    source_timestamp: datetime,
    value: float,
    provenance: str,
) -> None:
    _require_aware(as_of, "as_of")
    _require_aware(source_timestamp, "source_timestamp")
    if source_timestamp > as_of:
        raise ValueError("source_timestamp cannot be after as_of")
    if not ticker.strip():
        raise ValueError("ticker is required")
    if not provenance.strip():
        raise ValueError("provenance is required")
    if not math.isfinite(value):
        raise ValueError("factor value must be finite")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
