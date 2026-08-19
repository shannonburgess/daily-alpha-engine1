"""Research-only behavioral-change foundation for Daily Alpha.

This module normalizes alternative behavioral observations into one point-in-time
schema. It is intentionally disconnected from execution. Provider adapters are
injected with fetchers so the repository can define and test contracts before any
credential is present.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Protocol


class BehavioralSource(StrEnum):
    GOOGLE_TRENDS = "GOOGLE_TRENDS"
    YOUTUBE = "YOUTUBE"
    SIMILARWEB = "SIMILARWEB"


class SourceStatus(StrEnum):
    COMPLETE = "COMPLETE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class BehavioralEntity:
    entity_id: str
    ticker: str
    version: str
    company_name: str = ""
    aliases: tuple[str, ...] = ()
    brands: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    apps: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("entity_id is required")
        if not self.ticker.strip():
            raise ValueError("ticker is required")
        if not self.version.strip():
            raise ValueError("version is required")

    def search_terms(self, *, limit: int = 8) -> tuple[str, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        values = (
            (self.company_name,)
            + self.aliases
            + self.brands
            + self.products
            + self.apps
            + self.technologies
        )
        return _dedupe_text(values)[:limit]

    def website_domains(self, *, limit: int = 4) -> tuple[str, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return _dedupe_text(self.domains)[:limit]


@dataclass(frozen=True)
class BehavioralObservation:
    source: BehavioralSource
    entity_id: str
    ticker: str
    query_key: str
    metric: str
    observed_at: datetime
    source_timestamp: datetime
    raw_level: float
    provenance: str

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.source_timestamp, "source_timestamp")
        if self.source_timestamp > self.observed_at:
            raise ValueError("source_timestamp cannot be after observed_at")
        if not self.entity_id.strip() or not self.ticker.strip():
            raise ValueError("entity_id and ticker are required")
        if not self.query_key.strip() or not self.metric.strip():
            raise ValueError("query_key and metric are required")
        if not self.provenance.strip():
            raise ValueError("provenance is required")
        if not math.isfinite(self.raw_level) or self.raw_level < 0:
            raise ValueError("raw_level must be finite and non-negative")

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.source.value,
            self.entity_id,
            self.query_key,
            self.metric,
            self.source_timestamp.astimezone(UTC).isoformat(),
        )


@dataclass(frozen=True)
class ProviderFetchResult:
    source: BehavioralSource
    status: SourceStatus
    observations: tuple[BehavioralObservation, ...] = ()
    reason: str = ""
    cache_hit: bool = False


class ProviderFetcher(Protocol):
    def __call__(
        self,
        entity: BehavioralEntity,
        query_keys: tuple[str, ...],
        as_of: datetime,
    ) -> Iterable[BehavioralObservation]: ...


@dataclass
class _ProviderAdapter:
    source: BehavioralSource
    fetcher: ProviderFetcher | None = None
    max_queries_per_run: int = 8
    _cache: dict[tuple[str, date], ProviderFetchResult] = field(
        default_factory=dict, init=False, repr=False
    )

    def collect(
        self,
        entity: BehavioralEntity,
        *,
        as_of: datetime,
    ) -> ProviderFetchResult:
        _require_aware(as_of, "as_of")
        if self.max_queries_per_run <= 0:
            raise ValueError("max_queries_per_run must be positive")
        cache_key = (entity.entity_id, as_of.astimezone(UTC).date())
        cached = self._cache.get(cache_key)
        if cached is not None:
            return ProviderFetchResult(
                source=cached.source,
                status=cached.status,
                observations=cached.observations,
                reason=cached.reason,
                cache_hit=True,
            )
        if self.fetcher is None:
            result = ProviderFetchResult(
                source=self.source,
                status=SourceStatus.SOURCE_UNAVAILABLE,
                reason="PROVIDER_ACCESS_NOT_CONFIGURED",
            )
            self._cache[cache_key] = result
            return result

        query_keys = self._query_keys(entity)
        if not query_keys:
            result = ProviderFetchResult(
                source=self.source,
                status=SourceStatus.DATA_ERROR,
                reason="ENTITY_HAS_NO_PROVIDER_QUERY_KEYS",
            )
            self._cache[cache_key] = result
            return result
        try:
            observations = tuple(self.fetcher(entity, query_keys, as_of))
            _validate_provider_observations(
                observations,
                source=self.source,
                entity=entity,
                as_of=as_of,
            )
        except Exception as exc:  # provider boundary must fail closed
            result = ProviderFetchResult(
                source=self.source,
                status=SourceStatus.DATA_ERROR,
                reason=f"{type(exc).__name__}:{exc}",
            )
            self._cache[cache_key] = result
            return result

        result = ProviderFetchResult(
            source=self.source,
            status=SourceStatus.COMPLETE,
            observations=observations,
        )
        self._cache[cache_key] = result
        return result

    def _query_keys(self, entity: BehavioralEntity) -> tuple[str, ...]:
        return entity.search_terms(limit=self.max_queries_per_run)


class GoogleTrendsAdapter(_ProviderAdapter):
    def __init__(
        self,
        fetcher: ProviderFetcher | None = None,
        *,
        max_queries_per_run: int = 8,
    ) -> None:
        super().__init__(
            source=BehavioralSource.GOOGLE_TRENDS,
            fetcher=fetcher,
            max_queries_per_run=max_queries_per_run,
        )


class YouTubeDataAdapter(_ProviderAdapter):
    def __init__(
        self,
        fetcher: ProviderFetcher | None = None,
        *,
        max_queries_per_run: int = 8,
    ) -> None:
        super().__init__(
            source=BehavioralSource.YOUTUBE,
            fetcher=fetcher,
            max_queries_per_run=max_queries_per_run,
        )


class SimilarwebAdapter(_ProviderAdapter):
    def __init__(
        self,
        fetcher: ProviderFetcher | None = None,
        *,
        max_queries_per_run: int = 4,
    ) -> None:
        super().__init__(
            source=BehavioralSource.SIMILARWEB,
            fetcher=fetcher,
            max_queries_per_run=max_queries_per_run,
        )

    def _query_keys(self, entity: BehavioralEntity) -> tuple[str, ...]:
        return entity.website_domains(limit=self.max_queries_per_run)


@dataclass(frozen=True)
class SourceSignal:
    source: BehavioralSource
    as_of: datetime
    status: SourceStatus
    reason: str
    observations_used: int
    level_7d: float | None
    level_28d: float | None
    velocity_7d: float | None
    prior_velocity_7d: float | None
    acceleration: float | None
    abnormality_z: float | None
    persistence: float | None
    prototype_score: float | None


@dataclass(frozen=True)
class BehavioralSnapshot:
    entity_id: str
    ticker: str
    as_of: datetime
    source_signals: tuple[SourceSignal, ...]
    cross_source_confirmation: float
    behavioral_change_score: float | None
    information_imbalance_score: float | None
    information_imbalance_reason: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def derive_source_signal(
    observations: Iterable[BehavioralObservation],
    *,
    source: BehavioralSource,
    as_of: datetime,
) -> SourceSignal:
    """Derive point-in-time velocity/acceleration without consuming future rows."""
    _require_aware(as_of, "as_of")
    rows = _dedupe_observations(
        row
        for row in observations
        if row.source == source and row.source_timestamp <= as_of
    )
    if not rows:
        return _unavailable_signal(source, as_of, "NO_POINT_IN_TIME_OBSERVATIONS")

    daily: dict[date, float] = {}
    for row in rows:
        day = row.source_timestamp.astimezone(UTC).date()
        daily[day] = daily.get(day, 0.0) + row.raw_level

    as_of_day = as_of.astimezone(UTC).date()
    current7 = _window_total(daily, as_of_day, 0, 6)
    prior7 = _window_total(daily, as_of_day, 7, 13)
    prior_prior7 = _window_total(daily, as_of_day, 14, 20)
    trailing28 = _window_values(daily, as_of_day, 0, 27)
    available_days = sum(
        (as_of_day - timedelta(days=offset)) in daily for offset in range(28)
    )
    if prior7 <= 0 or prior_prior7 <= 0 or available_days < 14:
        return SourceSignal(
            source=source,
            as_of=as_of,
            status=SourceStatus.DATA_ERROR,
            reason="INSUFFICIENT_HISTORY_FOR_VELOCITY",
            observations_used=len(rows),
            level_7d=current7,
            level_28d=sum(trailing28),
            velocity_7d=None,
            prior_velocity_7d=None,
            acceleration=None,
            abnormality_z=None,
            persistence=None,
            prototype_score=None,
        )

    velocity = current7 / prior7 - 1.0
    prior_velocity = prior7 / prior_prior7 - 1.0
    acceleration = velocity - prior_velocity
    latest = daily.get(as_of_day, 0.0)
    mean = statistics.fmean(trailing28)
    std = statistics.pstdev(trailing28)
    abnormality_z = 0.0 if std == 0 else (latest - mean) / std
    median = statistics.median(trailing28)
    current_values = _window_values(daily, as_of_day, 0, 6)
    persistence = sum(value > median for value in current_values) / 7.0
    score = _prototype_score(velocity, acceleration, abnormality_z, persistence)

    return SourceSignal(
        source=source,
        as_of=as_of,
        status=SourceStatus.COMPLETE,
        reason="",
        observations_used=len(rows),
        level_7d=current7,
        level_28d=sum(trailing28),
        velocity_7d=velocity,
        prior_velocity_7d=prior_velocity,
        acceleration=acceleration,
        abnormality_z=abnormality_z,
        persistence=persistence,
        prototype_score=score,
    )


def build_behavioral_snapshot(
    entity: BehavioralEntity,
    source_signals: Iterable[SourceSignal],
    *,
    as_of: datetime,
) -> BehavioralSnapshot:
    """Collapse provider evidence into one low-noise research-only state."""
    _require_aware(as_of, "as_of")
    signals = tuple(sorted(source_signals, key=lambda item: item.source.value))
    complete = tuple(
        signal
        for signal in signals
        if signal.status == SourceStatus.COMPLETE
        and signal.prototype_score is not None
        and signal.persistence is not None
    )
    confirming = tuple(
        signal
        for signal in complete
        if signal.prototype_score >= 60.0 and signal.persistence >= 0.5
    )
    confirmation = min(100.0, 100.0 * len(confirming) / 2.0)
    if len(complete) < 2:
        behavioral_score = None
    else:
        average_score = statistics.fmean(
            signal.prototype_score
            for signal in complete
            if signal.prototype_score is not None
        )
        behavioral_score = round(0.8 * average_score + 0.2 * confirmation, 2)

    return BehavioralSnapshot(
        entity_id=entity.entity_id,
        ticker=entity.ticker.upper(),
        as_of=as_of,
        source_signals=signals,
        cross_source_confirmation=round(confirmation, 2),
        behavioral_change_score=behavioral_score,
        information_imbalance_score=None,
        information_imbalance_reason="WALL_STREET_RECOGNITION_NOT_CONNECTED",
    )


def _validate_provider_observations(
    observations: tuple[BehavioralObservation, ...],
    *,
    source: BehavioralSource,
    entity: BehavioralEntity,
    as_of: datetime,
) -> None:
    for row in observations:
        if row.source != source:
            raise ValueError("provider returned mismatched source")
        if row.entity_id != entity.entity_id or row.ticker.upper() != entity.ticker.upper():
            raise ValueError("provider returned mismatched entity")
        if row.observed_at > as_of:
            raise ValueError("provider observation observed_at is after as_of")


def _dedupe_observations(
    observations: Iterable[BehavioralObservation],
) -> tuple[BehavioralObservation, ...]:
    unique: dict[tuple[str, str, str, str, str], BehavioralObservation] = {}
    for row in observations:
        prior = unique.get(row.identity)
        if prior is not None and prior.raw_level != row.raw_level:
            raise ValueError("CONFLICTING_DUPLICATE_OBSERVATION")
        unique[row.identity] = row
    return tuple(sorted(unique.values(), key=lambda row: row.source_timestamp))


def _window_values(
    daily: dict[date, float],
    as_of_day: date,
    start_days_ago: int,
    end_days_ago: int,
) -> list[float]:
    return [
        daily.get(as_of_day - timedelta(days=offset), 0.0)
        for offset in range(start_days_ago, end_days_ago + 1)
    ]


def _window_total(
    daily: dict[date, float],
    as_of_day: date,
    start_days_ago: int,
    end_days_ago: int,
) -> float:
    return sum(_window_values(daily, as_of_day, start_days_ago, end_days_ago))


def _prototype_score(
    velocity: float,
    acceleration: float,
    abnormality_z: float,
    persistence: float,
) -> float:
    velocity_score = _linear_score(velocity, low=-0.25, high=0.75)
    acceleration_score = _linear_score(acceleration, low=-0.25, high=0.5)
    abnormality_score = _linear_score(abnormality_z, low=-1.0, high=3.0)
    persistence_score = max(0.0, min(100.0, persistence * 100.0))
    return round(
        0.4 * velocity_score
        + 0.3 * acceleration_score
        + 0.2 * abnormality_score
        + 0.1 * persistence_score,
        2,
    )


def _linear_score(value: float, *, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("high must be greater than low")
    return max(0.0, min(100.0, 100.0 * (value - low) / (high - low)))


def _unavailable_signal(
    source: BehavioralSource,
    as_of: datetime,
    reason: str,
) -> SourceSignal:
    return SourceSignal(
        source=source,
        as_of=as_of,
        status=SourceStatus.SOURCE_UNAVAILABLE,
        reason=reason,
        observations_used=0,
        level_7d=None,
        level_28d=None,
        velocity_7d=None,
        prior_velocity_7d=None,
        acceleration=None,
        abnormality_z=None,
        persistence=None,
        prototype_score=None,
    )


def _dedupe_text(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value or "").strip().split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
