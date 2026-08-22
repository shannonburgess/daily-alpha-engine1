"""Deterministic cross-provider market-data reconciliation for Daily Alpha."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .contracts import EvidenceStatus, ReadinessStatus
from .data_providers import (
    DataDomain,
    DataProviderError,
    DataRequest,
    ProviderObservation,
    ProviderRegistry,
    ProviderRole,
)


class MarketDataError(ValueError):
    """Market data cannot be normalized or reconciled safely."""


_ROLE_PRIORITY = {
    ProviderRole.PRIMARY: 0,
    ProviderRole.SECONDARY: 1,
    ProviderRole.BROKER_REFERENCE: 2,
    ProviderRole.OPTIONAL: 3,
}


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataError("MARKET_STATE_NOT_CANONICAL_JSON") from exc


def _finite_positive(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"{field_name}_MUST_BE_NUMERIC") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise MarketDataError(f"{field_name}_MUST_BE_POSITIVE_FINITE")
    return parsed


def _finite_nonnegative(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"{field_name}_MUST_BE_NUMERIC") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise MarketDataError(f"{field_name}_MUST_BE_NONNEGATIVE_FINITE")
    return parsed


def _parse_aware_iso(value: Any, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise MarketDataError(f"{field_name}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MarketDataError(f"{field_name}_INVALID") from exc
    return _aware_utc(parsed, field_name)


@dataclass(frozen=True)
class MarketBar:
    security_id: str
    timeframe: str
    bar_start: datetime
    bar_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        timeframe = self.timeframe.strip().upper()
        if not security_id:
            raise MarketDataError("MARKET_BAR_SECURITY_ID_REQUIRED")
        if not timeframe:
            raise MarketDataError("MARKET_BAR_TIMEFRAME_REQUIRED")
        start = _aware_utc(self.bar_start, "MARKET_BAR_START")
        end = _aware_utc(self.bar_end, "MARKET_BAR_END")
        if end <= start:
            raise MarketDataError("MARKET_BAR_END_MUST_FOLLOW_START")
        open_price = _finite_positive(self.open, "MARKET_BAR_OPEN")
        high = _finite_positive(self.high, "MARKET_BAR_HIGH")
        low = _finite_positive(self.low, "MARKET_BAR_LOW")
        close = _finite_positive(self.close, "MARKET_BAR_CLOSE")
        volume = _finite_nonnegative(self.volume, "MARKET_BAR_VOLUME")
        if high < max(open_price, low, close):
            raise MarketDataError("MARKET_BAR_HIGH_INCONSISTENT")
        if low > min(open_price, high, close):
            raise MarketDataError("MARKET_BAR_LOW_INCONSISTENT")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "bar_start", start)
        object.__setattr__(self, "bar_end", end)
        object.__setattr__(self, "open", open_price)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)

    @classmethod
    def from_observation(cls, observation: ProviderObservation) -> MarketBar:
        if observation.domain is not DataDomain.MARKET_BARS:
            raise MarketDataError("MARKET_BAR_OBSERVATION_DOMAIN_INVALID")
        if not isinstance(observation.value, dict):
            raise MarketDataError("MARKET_BAR_VALUE_MUST_BE_OBJECT")
        security_id = _security_id_from_subject(observation.subject_key)
        value = observation.value
        return cls(
            security_id=security_id,
            timeframe=str(value.get("timeframe") or ""),
            bar_start=_parse_aware_iso(value.get("bar_start"), "MARKET_BAR_START"),
            bar_end=_parse_aware_iso(value.get("bar_end"), "MARKET_BAR_END"),
            open=value.get("open"),
            high=value.get("high"),
            low=value.get("low"),
            close=value.get("close"),
            volume=value.get("volume"),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "timeframe": self.timeframe,
            "bar_start": self.bar_start.isoformat(),
            "bar_end": self.bar_end.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class MarketQuote:
    security_id: str
    quote_time: datetime
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last: float | None = None

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        if not security_id:
            raise MarketDataError("MARKET_QUOTE_SECURITY_ID_REQUIRED")
        quote_time = _aware_utc(self.quote_time, "MARKET_QUOTE_TIME")
        bid = _finite_positive(self.bid, "MARKET_QUOTE_BID")
        ask = _finite_positive(self.ask, "MARKET_QUOTE_ASK")
        if ask < bid:
            raise MarketDataError("MARKET_QUOTE_CROSSED")
        bid_size = _finite_nonnegative(self.bid_size, "MARKET_QUOTE_BID_SIZE")
        ask_size = _finite_nonnegative(self.ask_size, "MARKET_QUOTE_ASK_SIZE")
        last = None if self.last is None else _finite_positive(self.last, "MARKET_QUOTE_LAST")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "quote_time", quote_time)
        object.__setattr__(self, "bid", bid)
        object.__setattr__(self, "ask", ask)
        object.__setattr__(self, "bid_size", bid_size)
        object.__setattr__(self, "ask_size", ask_size)
        object.__setattr__(self, "last", last)

    @classmethod
    def from_observation(cls, observation: ProviderObservation) -> MarketQuote:
        if observation.domain is not DataDomain.MARKET_QUOTES:
            raise MarketDataError("MARKET_QUOTE_OBSERVATION_DOMAIN_INVALID")
        if not isinstance(observation.value, dict):
            raise MarketDataError("MARKET_QUOTE_VALUE_MUST_BE_OBJECT")
        security_id = _security_id_from_subject(observation.subject_key)
        value = observation.value
        return cls(
            security_id=security_id,
            quote_time=_parse_aware_iso(value.get("quote_time"), "MARKET_QUOTE_TIME"),
            bid=value.get("bid"),
            ask=value.get("ask"),
            bid_size=value.get("bid_size", 0.0),
            ask_size=value.get("ask_size", 0.0),
            last=value.get("last"),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "quote_time": self.quote_time.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "last": self.last,
        }


@dataclass(frozen=True)
class MarketReconciliationPolicy:
    min_independent_groups: int = 2
    max_price_deviation_bps: float = 5.0
    max_volume_relative_deviation: float = 0.10
    max_quote_time_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.min_independent_groups <= 0:
            raise MarketDataError("MARKET_MIN_GROUPS_MUST_BE_POSITIVE")
        if self.max_price_deviation_bps < 0:
            raise MarketDataError("MARKET_PRICE_TOLERANCE_MUST_BE_NONNEGATIVE")
        if self.max_volume_relative_deviation < 0:
            raise MarketDataError("MARKET_VOLUME_TOLERANCE_MUST_BE_NONNEGATIVE")
        if self.max_quote_time_skew_seconds < 0:
            raise MarketDataError("MARKET_QUOTE_SKEW_MUST_BE_NONNEGATIVE")


@dataclass(frozen=True)
class CanonicalMarketState:
    security_id: str
    domain: DataDomain
    metric: str
    as_of: datetime
    status: ReadinessStatus
    canonical_provider_id: str | None
    canonical_independence_group: str | None
    canonical_value: dict[str, object] | None
    observation_ids: tuple[str, ...]
    selected_provider_ids: tuple[str, ...]
    independence_groups: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        metric = self.metric.strip().upper()
        boundary = _aware_utc(self.as_of, "MARKET_STATE_AS_OF")
        if not security_id:
            raise MarketDataError("MARKET_STATE_SECURITY_ID_REQUIRED")
        if not metric:
            raise MarketDataError("MARKET_STATE_METRIC_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise MarketDataError("MARKET_STATE_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED and self.canonical_value is not None:
            raise MarketDataError("BLOCKED_MARKET_STATE_CANNOT_HAVE_CANONICAL_VALUE")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "observation_ids", tuple(sorted(self.observation_ids)))
        object.__setattr__(self, "selected_provider_ids", tuple(sorted(self.selected_provider_ids)))
        object.__setattr__(self, "independence_groups", tuple(sorted(self.independence_groups)))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def state_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "domain": self.domain.value,
            "metric": self.metric,
            "as_of": self.as_of.isoformat(),
            "status": self.status.value,
            "canonical_provider_id": self.canonical_provider_id,
            "canonical_independence_group": self.canonical_independence_group,
            "canonical_value": self.canonical_value,
            "observation_ids": list(self.observation_ids),
            "selected_provider_ids": list(self.selected_provider_ids),
            "independence_groups": list(self.independence_groups),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class MarketDataReconciler:
    """Create canonical market state only after independent-source verification."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def reconcile_bar(
        self,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        *,
        policy: MarketReconciliationPolicy = MarketReconciliationPolicy(),
    ) -> CanonicalMarketState:
        if request.domain is not DataDomain.MARKET_BARS:
            raise MarketDataError("BAR_RECONCILIATION_REQUIRES_MARKET_BARS_REQUEST")
        selected, warnings, blockers = self._select_independent(request, observations, policy)
        bars: list[tuple[ProviderObservation, MarketBar]] = []
        for observation in selected:
            try:
                bars.append((observation, MarketBar.from_observation(observation)))
            except MarketDataError as exc:
                blockers.append(f"INVALID_MARKET_BAR:{observation.provider_id}:{exc}")

        if len({item[0].independence_group for item in bars}) < policy.min_independent_groups:
            blockers.append("INSUFFICIENT_VALID_MARKET_BAR_REDUNDANCY")

        reference_pair = self._reference_pair(bars)
        if reference_pair is not None:
            reference_observation, reference = reference_pair
            for observation, bar in bars:
                if observation.provider_id == reference_observation.provider_id:
                    continue
                blockers.extend(_bar_conflicts(reference, bar, observation.provider_id, policy))
        return self._state(
            request=request,
            observations=observations,
            selected=selected,
            reference_pair=reference_pair,
            warnings=warnings,
            blockers=blockers,
        )

    def reconcile_quote(
        self,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        *,
        policy: MarketReconciliationPolicy = MarketReconciliationPolicy(),
    ) -> CanonicalMarketState:
        if request.domain is not DataDomain.MARKET_QUOTES:
            raise MarketDataError("QUOTE_RECONCILIATION_REQUIRES_MARKET_QUOTES_REQUEST")
        selected, warnings, blockers = self._select_independent(request, observations, policy)
        quotes: list[tuple[ProviderObservation, MarketQuote]] = []
        for observation in selected:
            try:
                quotes.append((observation, MarketQuote.from_observation(observation)))
            except MarketDataError as exc:
                blockers.append(f"INVALID_MARKET_QUOTE:{observation.provider_id}:{exc}")

        if len({item[0].independence_group for item in quotes}) < policy.min_independent_groups:
            blockers.append("INSUFFICIENT_VALID_MARKET_QUOTE_REDUNDANCY")

        reference_pair = self._reference_pair(quotes)
        if reference_pair is not None:
            reference_observation, reference = reference_pair
            for observation, quote in quotes:
                if observation.provider_id == reference_observation.provider_id:
                    continue
                blockers.extend(_quote_conflicts(reference, quote, observation.provider_id, policy))
        return self._state(
            request=request,
            observations=observations,
            selected=selected,
            reference_pair=reference_pair,
            warnings=warnings,
            blockers=blockers,
        )

    def _select_independent(
        self,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        policy: MarketReconciliationPolicy,
    ) -> tuple[list[ProviderObservation], list[str], list[str]]:
        warnings: list[str] = []
        blockers: list[str] = []
        by_group: dict[str, list[ProviderObservation]] = {}
        for observation in observations:
            try:
                observation.validate_against(request)
                definition = self.registry.get(observation.provider_id)
            except (DataProviderError, MarketDataError) as exc:
                blockers.append(f"MARKET_OBSERVATION_CONTRACT_ERROR:{observation.provider_id}:{exc}")
                continue
            capability = definition.capability_for(request.domain)
            if capability is None:
                blockers.append(f"MARKET_PROVIDER_DOMAIN_UNREGISTERED:{observation.provider_id}")
                continue
            if definition.independence_group != observation.independence_group:
                blockers.append(f"MARKET_PROVIDER_GROUP_MISMATCH:{observation.provider_id}")
                continue
            if observation.status is not EvidenceStatus.COMPLETE:
                warnings.append(
                    f"MARKET_SOURCE_EXCLUDED:{observation.provider_id}:{observation.status.value}"
                )
                continue
            age = (request.as_of - observation.observed_at).total_seconds()
            if age > capability.max_freshness_seconds:
                warnings.append(f"MARKET_SOURCE_STALE:{observation.provider_id}")
                continue
            by_group.setdefault(observation.independence_group, []).append(observation)

        selected: list[ProviderObservation] = []
        for group in sorted(by_group):
            candidates = by_group[group]
            selected.append(max(candidates, key=self._observation_rank))
        if len(selected) < policy.min_independent_groups:
            blockers.append(
                f"INSUFFICIENT_INDEPENDENT_MARKET_SOURCES:{len(selected)}<"
                f"{policy.min_independent_groups}"
            )
        return selected, warnings, blockers

    def _observation_rank(self, observation: ProviderObservation) -> tuple[object, ...]:
        definition = self.registry.get(observation.provider_id)
        capability = definition.capability_for(observation.domain)
        if capability is None:
            raise MarketDataError("MARKET_PROVIDER_CAPABILITY_MISSING")
        return (
            -_ROLE_PRIORITY[capability.role],
            observation.confidence,
            observation.observed_at,
            observation.received_at,
            observation.provider_id,
        )

    def _reference_pair(self, pairs: list[tuple[ProviderObservation, Any]]) -> Any | None:
        if not pairs:
            return None
        return max(pairs, key=lambda item: self._observation_rank(item[0]))

    def _state(
        self,
        *,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        selected: list[ProviderObservation],
        reference_pair: Any | None,
        warnings: list[str],
        blockers: list[str],
    ) -> CanonicalMarketState:
        security_id = _security_id_from_subject(request.subject_key)
        if blockers:
            status = ReadinessStatus.BLOCKED
            canonical_provider_id = None
            canonical_group = None
            canonical_value = None
        else:
            status = ReadinessStatus.WARNING if warnings else ReadinessStatus.PASS
            if reference_pair is None:
                raise MarketDataError("MARKET_REFERENCE_REQUIRED_WITHOUT_BLOCKERS")
            reference_observation, reference_value = reference_pair
            canonical_provider_id = reference_observation.provider_id
            canonical_group = reference_observation.independence_group
            canonical_value = reference_value.to_payload()
        return CanonicalMarketState(
            security_id=security_id,
            domain=request.domain,
            metric=request.metric,
            as_of=request.as_of,
            status=status,
            canonical_provider_id=canonical_provider_id,
            canonical_independence_group=canonical_group,
            canonical_value=canonical_value,
            observation_ids=tuple(item.observation_id for item in observations),
            selected_provider_ids=tuple(item.provider_id for item in selected),
            independence_groups=tuple(item.independence_group for item in selected),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )


def _security_id_from_subject(subject_key: str) -> str:
    prefix = "SECURITY:"
    if not subject_key.startswith(prefix):
        raise MarketDataError("MARKET_DATA_REQUIRES_SECURITY_SUBJECT")
    security_id = subject_key[len(prefix) :].strip().upper()
    if not security_id:
        raise MarketDataError("MARKET_DATA_SECURITY_ID_REQUIRED")
    return security_id


def _price_deviation_bps(reference: float, candidate: float) -> float:
    return abs(candidate - reference) / max(abs(reference), 1e-12) * 10_000.0


def _relative_deviation(reference: float, candidate: float) -> float:
    return abs(candidate - reference) / max(abs(reference), 1.0)


def _bar_conflicts(
    reference: MarketBar,
    candidate: MarketBar,
    provider_id: str,
    policy: MarketReconciliationPolicy,
) -> list[str]:
    conflicts: list[str] = []
    if candidate.security_id != reference.security_id:
        conflicts.append(f"MARKET_BAR_SECURITY_CONFLICT:{provider_id}")
    if candidate.timeframe != reference.timeframe:
        conflicts.append(f"MARKET_BAR_TIMEFRAME_CONFLICT:{provider_id}")
    if candidate.bar_start != reference.bar_start or candidate.bar_end != reference.bar_end:
        conflicts.append(f"MARKET_BAR_TIME_ALIGNMENT_CONFLICT:{provider_id}")
    for field_name in ("open", "high", "low", "close"):
        reference_value = getattr(reference, field_name)
        candidate_value = getattr(candidate, field_name)
        if _price_deviation_bps(reference_value, candidate_value) > policy.max_price_deviation_bps:
            conflicts.append(f"MARKET_BAR_PRICE_CONFLICT:{provider_id}:{field_name.upper()}")
    if (
        _relative_deviation(reference.volume, candidate.volume)
        > policy.max_volume_relative_deviation
    ):
        conflicts.append(f"MARKET_BAR_VOLUME_CONFLICT:{provider_id}")
    return conflicts


def _quote_conflicts(
    reference: MarketQuote,
    candidate: MarketQuote,
    provider_id: str,
    policy: MarketReconciliationPolicy,
) -> list[str]:
    conflicts: list[str] = []
    if candidate.security_id != reference.security_id:
        conflicts.append(f"MARKET_QUOTE_SECURITY_CONFLICT:{provider_id}")
    skew = abs((candidate.quote_time - reference.quote_time).total_seconds())
    if skew > policy.max_quote_time_skew_seconds:
        conflicts.append(f"MARKET_QUOTE_TIME_SKEW_CONFLICT:{provider_id}")
    for field_name in ("bid", "ask"):
        reference_value = getattr(reference, field_name)
        candidate_value = getattr(candidate, field_name)
        if _price_deviation_bps(reference_value, candidate_value) > policy.max_price_deviation_bps:
            conflicts.append(f"MARKET_QUOTE_PRICE_CONFLICT:{provider_id}:{field_name.upper()}")
    if reference.last is not None and candidate.last is not None:
        if _price_deviation_bps(reference.last, candidate.last) > policy.max_price_deviation_bps:
            conflicts.append(f"MARKET_QUOTE_PRICE_CONFLICT:{provider_id}:LAST")
    return conflicts
