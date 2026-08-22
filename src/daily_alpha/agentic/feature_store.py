"""Deterministic feature registry, computation, and point-in-time store.

Raw provider payloads do not belong in investment agents. Features are computed from
canonical state using versioned definitions and immutable input lineage so every
historical feature can be reproduced exactly.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus
from .market_reconciliation import CanonicalMarketState, MarketBar


class FeatureStoreError(ValueError):
    """Feature definition, computation, or storage invariant failed."""


class FeatureConflictError(FeatureStoreError):
    """An immutable logical feature observation was rewritten."""


class FeatureSourceFamily(StrEnum):
    MARKET = "MARKET"
    EVENT = "EVENT"
    RESEARCH = "RESEARCH"
    PORTFOLIO = "PORTFOLIO"
    CROSS_DOMAIN = "CROSS_DOMAIN"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureStoreError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise FeatureStoreError("FEATURE_VALUE_NOT_CANONICAL_JSON") from exc


def _normalize_parameters(
    parameters: tuple[tuple[str, str], ...] | dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    items = parameters.items() if isinstance(parameters, dict) else parameters
    normalized = tuple(
        sorted((str(key).strip(), _canonical_json(value)) for key, value in items)
    )
    if any(not key for key, _ in normalized):
        raise FeatureStoreError("FEATURE_PARAMETER_KEY_REQUIRED")
    if len({key for key, _ in normalized}) != len(normalized):
        raise FeatureStoreError("FEATURE_PARAMETER_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True)
class FeatureDefinition:
    feature_key: str
    version: str
    calculator_id: str
    source_family: FeatureSourceFamily
    lookback_bars: int
    output_unit: str
    required_for_core: bool = True
    parameters: tuple[tuple[str, str], ...] | dict[str, Any] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        feature_key = self.feature_key.strip().upper()
        version = self.version.strip()
        calculator_id = self.calculator_id.strip().upper()
        output_unit = self.output_unit.strip().upper()
        if not feature_key:
            raise FeatureStoreError("FEATURE_KEY_REQUIRED")
        if not version:
            raise FeatureStoreError("FEATURE_VERSION_REQUIRED")
        if not calculator_id:
            raise FeatureStoreError("FEATURE_CALCULATOR_REQUIRED")
        if self.lookback_bars <= 0:
            raise FeatureStoreError("FEATURE_LOOKBACK_MUST_BE_POSITIVE")
        if not output_unit:
            raise FeatureStoreError("FEATURE_OUTPUT_UNIT_REQUIRED")
        object.__setattr__(self, "feature_key", feature_key)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "calculator_id", calculator_id)
        object.__setattr__(self, "output_unit", output_unit)
        object.__setattr__(self, "parameters", _normalize_parameters(self.parameters))

    @property
    def definition_id(self) -> str:
        payload = {
            "feature_key": self.feature_key,
            "version": self.version,
            "calculator_id": self.calculator_id,
            "source_family": self.source_family.value,
            "lookback_bars": self.lookback_bars,
            "output_unit": self.output_unit,
            "required_for_core": self.required_for_core,
            "parameters": list(self.parameters),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class FeatureRegistry:
    """Versioned registry that prevents silent feature-definition changes."""

    def __init__(self, definitions: tuple[FeatureDefinition, ...] = ()) -> None:
        self._by_key_version: dict[tuple[str, str], FeatureDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: FeatureDefinition) -> None:
        key = (definition.feature_key, definition.version)
        existing = self._by_key_version.get(key)
        if existing is None:
            self._by_key_version[key] = definition
            return
        if existing != definition:
            raise FeatureStoreError(
                f"FEATURE_DEFINITION_CONFLICT:{definition.feature_key}:{definition.version}"
            )

    def get(self, feature_key: str, version: str) -> FeatureDefinition:
        key = (feature_key.strip().upper(), version.strip())
        try:
            return self._by_key_version[key]
        except KeyError as exc:
            raise FeatureStoreError(f"FEATURE_DEFINITION_NOT_FOUND:{key[0]}:{key[1]}") from exc

    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return tuple(self._by_key_version[key] for key in sorted(self._by_key_version))

    @property
    def registry_id(self) -> str:
        payload = [
            {
                "feature_key": definition.feature_key,
                "version": definition.version,
                "definition_id": definition.definition_id,
            }
            for definition in self.definitions()
        ]
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureValue:
    security_id: str
    feature_key: str
    as_of: datetime
    definition_id: str
    definition_version: str
    output_unit: str
    status: ReadinessStatus
    value: Any | None
    input_state_ids: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        feature_key = self.feature_key.strip().upper()
        definition_id = self.definition_id.strip().lower()
        version = self.definition_version.strip()
        output_unit = self.output_unit.strip().upper()
        boundary = _aware_utc(self.as_of, "FEATURE_AS_OF")
        if not security_id:
            raise FeatureStoreError("FEATURE_SECURITY_ID_REQUIRED")
        if not feature_key:
            raise FeatureStoreError("FEATURE_VALUE_KEY_REQUIRED")
        if not definition_id:
            raise FeatureStoreError("FEATURE_DEFINITION_ID_REQUIRED")
        if not version:
            raise FeatureStoreError("FEATURE_DEFINITION_VERSION_REQUIRED")
        if not output_unit:
            raise FeatureStoreError("FEATURE_VALUE_OUTPUT_UNIT_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise FeatureStoreError("FEATURE_VALUE_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED:
            if self.value is not None:
                raise FeatureStoreError("BLOCKED_FEATURE_CANNOT_HAVE_VALUE")
            if not self.blockers:
                raise FeatureStoreError("BLOCKED_FEATURE_REQUIRES_BLOCKER")
        elif self.value is None:
            raise FeatureStoreError("NONBLOCKED_FEATURE_REQUIRES_VALUE")
        if self.value is not None:
            _canonical_json(self.value)
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "feature_key", feature_key)
        object.__setattr__(self, "definition_id", definition_id)
        object.__setattr__(self, "definition_version", version)
        object.__setattr__(self, "output_unit", output_unit)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "input_state_ids", tuple(sorted(set(self.input_state_ids))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def logical_key(self) -> tuple[str, str, datetime, str]:
        return self.security_id, self.feature_key, self.as_of, self.definition_id

    @property
    def feature_value_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "feature_key": self.feature_key,
            "as_of": self.as_of.isoformat(),
            "definition_id": self.definition_id,
            "definition_version": self.definition_version,
            "output_unit": self.output_unit,
            "status": self.status.value,
            "value": self.value,
            "input_state_ids": list(self.input_state_ids),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureBundle:
    security_id: str
    as_of: datetime
    registry_id: str
    features: tuple[FeatureValue, ...]
    market_state_ids: tuple[str, ...]
    excluded_market_state_ids: tuple[str, ...]
    status: ReadinessStatus
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        boundary = _aware_utc(self.as_of, "FEATURE_BUNDLE_AS_OF")
        registry_id = self.registry_id.strip().lower()
        if not security_id:
            raise FeatureStoreError("FEATURE_BUNDLE_SECURITY_ID_REQUIRED")
        if not registry_id:
            raise FeatureStoreError("FEATURE_BUNDLE_REGISTRY_ID_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise FeatureStoreError("FEATURE_BUNDLE_MUST_REMAIN_RESEARCH_ONLY")
        ordered_features = tuple(
            sorted(self.features, key=lambda item: (item.feature_key, item.definition_id))
        )
        if any(item.security_id != security_id or item.as_of != boundary for item in ordered_features):
            raise FeatureStoreError("FEATURE_BUNDLE_MEMBER_MISMATCH")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "registry_id", registry_id)
        object.__setattr__(self, "features", ordered_features)
        object.__setattr__(self, "market_state_ids", tuple(sorted(set(self.market_state_ids))))
        object.__setattr__(
            self,
            "excluded_market_state_ids",
            tuple(sorted(set(self.excluded_market_state_ids))),
        )

    @property
    def bundle_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "as_of": self.as_of.isoformat(),
            "registry_id": self.registry_id,
            "features": [item.feature_value_id for item in self.features],
            "market_state_ids": list(self.market_state_ids),
            "excluded_market_state_ids": list(self.excluded_market_state_ids),
            "status": self.status.value,
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class InMemoryFeatureStore:
    """Immutable point-in-time feature store reference implementation."""

    def __init__(self) -> None:
        self._by_id: dict[str, FeatureValue] = {}
        self._logical_ids: dict[tuple[str, str, datetime, str], str] = {}
        self._security_ids: dict[str, set[str]] = defaultdict(set)

    def put(self, value: FeatureValue) -> str:
        value_id = value.feature_value_id
        existing_id = self._logical_ids.get(value.logical_key)
        if existing_id is not None and existing_id != value_id:
            raise FeatureConflictError(
                f"FEATURE_IMMUTABILITY_VIOLATION:{value.security_id}:{value.feature_key}"
            )
        self._by_id.setdefault(value_id, value)
        self._logical_ids.setdefault(value.logical_key, value_id)
        self._security_ids[value.security_id].add(value_id)
        return value_id

    def put_bundle(self, bundle: FeatureBundle) -> tuple[str, ...]:
        return tuple(self.put(value) for value in bundle.features)

    def get(self, feature_value_id: str) -> FeatureValue:
        try:
            return self._by_id[feature_value_id]
        except KeyError as exc:
            raise FeatureStoreError(f"FEATURE_VALUE_NOT_FOUND:{feature_value_id}") from exc

    def latest(
        self,
        *,
        security_id: str,
        feature_key: str,
        as_of: datetime,
    ) -> FeatureValue | None:
        security = security_id.strip().upper()
        feature = feature_key.strip().upper()
        boundary = _aware_utc(as_of, "FEATURE_QUERY_AS_OF")
        candidates = [
            self._by_id[value_id]
            for value_id in self._security_ids.get(security, set())
            if self._by_id[value_id].feature_key == feature
            and self._by_id[value_id].as_of <= boundary
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.as_of, item.definition_version, item.feature_value_id),
        )


def default_daily_feature_definitions() -> tuple[FeatureDefinition, ...]:
    version = "DAILY_FEATURES_V1"
    return (
        FeatureDefinition(
            "RETURN_1D", version, "RETURN", FeatureSourceFamily.MARKET, 2, "RATIO",
            parameters={"periods": 1},
        ),
        FeatureDefinition(
            "RETURN_5D", version, "RETURN", FeatureSourceFamily.MARKET, 6, "RATIO",
            parameters={"periods": 5},
        ),
        FeatureDefinition(
            "RETURN_20D", version, "RETURN", FeatureSourceFamily.MARKET, 21, "RATIO",
            parameters={"periods": 20},
        ),
        FeatureDefinition(
            "SMA_10D", version, "SMA", FeatureSourceFamily.MARKET, 10, "PRICE",
            parameters={"periods": 10},
        ),
        FeatureDefinition(
            "SMA_20D", version, "SMA", FeatureSourceFamily.MARKET, 20, "PRICE",
            parameters={"periods": 20},
        ),
        FeatureDefinition(
            "SMA_50D", version, "SMA", FeatureSourceFamily.MARKET, 50, "PRICE",
            parameters={"periods": 50},
        ),
        FeatureDefinition(
            "ATR_14D", version, "ATR", FeatureSourceFamily.MARKET, 15, "PRICE",
            parameters={"periods": 14},
        ),
        FeatureDefinition(
            "REALIZED_VOL_20D", version, "REALIZED_VOL", FeatureSourceFamily.MARKET, 21,
            "ANNUALIZED_VOL", parameters={"periods": 20, "annualization": 252},
        ),
        FeatureDefinition(
            "AVG_VOLUME_20D", version, "AVG_VOLUME", FeatureSourceFamily.MARKET, 20,
            "SHARES", parameters={"periods": 20},
        ),
        FeatureDefinition(
            "HIGH_POSITION_252D", version, "HIGH_POSITION", FeatureSourceFamily.MARKET, 252,
            "RATIO", required_for_core=False, parameters={"periods": 252},
        ),
    )


class DailyBarFeatureEngine:
    """Reference deterministic daily-bar feature calculator."""

    def __init__(self, registry: FeatureRegistry | None = None) -> None:
        self.registry = registry or FeatureRegistry(default_daily_feature_definitions())

    def compute(
        self,
        market_states: tuple[CanonicalMarketState, ...],
        *,
        as_of: datetime,
        security_id: str | None = None,
    ) -> FeatureBundle:
        boundary = _aware_utc(as_of, "FEATURE_COMPUTE_AS_OF")
        resolved_security, bars, accepted_states, excluded_states = self._daily_bars(
            market_states,
            as_of=boundary,
            security_id=security_id,
        )
        values = tuple(
            self._compute_definition(
                definition,
                bars=bars,
                state_by_bar_end=accepted_states,
                security_id=resolved_security,
                as_of=boundary,
            )
            for definition in self.registry.definitions()
            if definition.source_family is FeatureSourceFamily.MARKET
        )
        required_blocked = {
            definition.feature_key
            for definition in self.registry.definitions()
            if definition.required_for_core
            and any(
                value.feature_key == definition.feature_key
                and value.status is ReadinessStatus.BLOCKED
                for value in values
            )
        }
        any_degraded = bool(excluded_states) or any(
            value.status is not ReadinessStatus.PASS for value in values
        )
        if required_blocked:
            status = ReadinessStatus.BLOCKED
        elif any_degraded:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return FeatureBundle(
            security_id=resolved_security,
            as_of=boundary,
            registry_id=self.registry.registry_id,
            features=values,
            market_state_ids=tuple(state.state_id for state in accepted_states.values()),
            excluded_market_state_ids=tuple(excluded_states),
            status=status,
        )

    def _daily_bars(
        self,
        market_states: tuple[CanonicalMarketState, ...],
        *,
        as_of: datetime,
        security_id: str | None,
    ) -> tuple[str, list[MarketBar], dict[datetime, CanonicalMarketState], list[str]]:
        requested_security = security_id.strip().upper() if security_id else None
        inferred = {state.security_id for state in market_states}
        if requested_security is None:
            if len(inferred) != 1:
                raise FeatureStoreError("FEATURE_ENGINE_REQUIRES_ONE_SECURITY")
            requested_security = next(iter(inferred))
        if not requested_security:
            raise FeatureStoreError("FEATURE_ENGINE_SECURITY_ID_REQUIRED")

        by_end: dict[datetime, tuple[MarketBar, CanonicalMarketState]] = {}
        excluded: list[str] = []
        for state in market_states:
            if state.security_id != requested_security:
                raise FeatureStoreError("FEATURE_ENGINE_SECURITY_MISMATCH")
            if state.as_of > as_of:
                raise FeatureStoreError("FUTURE_MARKET_STATE_NOT_ALLOWED_IN_FEATURE")
            if state.status is ReadinessStatus.BLOCKED or state.canonical_value is None:
                excluded.append(state.state_id)
                continue
            if state.metric != "OHLCV_1D":
                excluded.append(state.state_id)
                continue
            bar = _market_bar_from_state(state)
            if bar.timeframe != "1D":
                excluded.append(state.state_id)
                continue
            if bar.bar_end > as_of:
                raise FeatureStoreError("FUTURE_MARKET_BAR_NOT_ALLOWED_IN_FEATURE")
            current = by_end.get(bar.bar_end)
            if current is not None:
                current_bar, current_state = current
                if current_bar.to_payload() != bar.to_payload():
                    raise FeatureStoreError(
                        f"CONFLICTING_CANONICAL_BAR:{requested_security}:{bar.bar_end.isoformat()}"
                    )
                if (state.as_of, state.state_id) <= (current_state.as_of, current_state.state_id):
                    continue
            by_end[bar.bar_end] = (bar, state)

        ordered = sorted(by_end.values(), key=lambda item: item[0].bar_end)
        bars = [item[0] for item in ordered]
        state_by_end = {item[0].bar_end: item[1] for item in ordered}
        return requested_security, bars, state_by_end, excluded

    def _compute_definition(
        self,
        definition: FeatureDefinition,
        *,
        bars: list[MarketBar],
        state_by_bar_end: dict[datetime, CanonicalMarketState],
        security_id: str,
        as_of: datetime,
    ) -> FeatureValue:
        if len(bars) < definition.lookback_bars:
            return FeatureValue(
                security_id=security_id,
                feature_key=definition.feature_key,
                as_of=as_of,
                definition_id=definition.definition_id,
                definition_version=definition.version,
                output_unit=definition.output_unit,
                status=ReadinessStatus.BLOCKED,
                value=None,
                input_state_ids=(),
                blockers=(
                    f"INSUFFICIENT_DAILY_BARS:{len(bars)}<{definition.lookback_bars}",
                ),
            )

        inputs = bars[-definition.lookback_bars :]
        input_states = [state_by_bar_end[bar.bar_end] for bar in inputs]
        warnings = tuple(
            f"DEGRADED_MARKET_INPUT:{state.state_id}"
            for state in input_states
            if state.status is ReadinessStatus.WARNING
        )
        value = self._calculate(definition, inputs)
        status = ReadinessStatus.WARNING if warnings else ReadinessStatus.PASS
        return FeatureValue(
            security_id=security_id,
            feature_key=definition.feature_key,
            as_of=as_of,
            definition_id=definition.definition_id,
            definition_version=definition.version,
            output_unit=definition.output_unit,
            status=status,
            value=value,
            input_state_ids=tuple(state.state_id for state in input_states),
            warnings=warnings,
        )

    def _calculate(self, definition: FeatureDefinition, bars: list[MarketBar]) -> float:
        calculator = definition.calculator_id
        parameters = {key: json.loads(value) for key, value in definition.parameters}
        if calculator == "RETURN":
            periods = int(parameters["periods"])
            return bars[-1].close / bars[-(periods + 1)].close - 1.0
        if calculator == "SMA":
            periods = int(parameters["periods"])
            closes = [bar.close for bar in bars[-periods:]]
            return sum(closes) / periods
        if calculator == "ATR":
            periods = int(parameters["periods"])
            relevant = bars[-(periods + 1) :]
            true_ranges = []
            for index in range(1, len(relevant)):
                current = relevant[index]
                previous_close = relevant[index - 1].close
                true_ranges.append(
                    max(
                        current.high - current.low,
                        abs(current.high - previous_close),
                        abs(current.low - previous_close),
                    )
                )
            return sum(true_ranges) / periods
        if calculator == "REALIZED_VOL":
            periods = int(parameters["periods"])
            annualization = float(parameters["annualization"])
            closes = [bar.close for bar in bars[-(periods + 1) :]]
            log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
            return statistics.pstdev(log_returns) * math.sqrt(annualization)
        if calculator == "AVG_VOLUME":
            periods = int(parameters["periods"])
            return sum(bar.volume for bar in bars[-periods:]) / periods
        if calculator == "HIGH_POSITION":
            periods = int(parameters["periods"])
            relevant = bars[-periods:]
            highest = max(bar.high for bar in relevant)
            return relevant[-1].close / highest
        raise FeatureStoreError(f"FEATURE_CALCULATOR_NOT_IMPLEMENTED:{calculator}")


def _market_bar_from_state(state: CanonicalMarketState) -> MarketBar:
    value = state.canonical_value
    if not isinstance(value, dict):
        raise FeatureStoreError("CANONICAL_MARKET_STATE_VALUE_REQUIRED")
    try:
        bar_start = datetime.fromisoformat(str(value["bar_start"]))
        bar_end = datetime.fromisoformat(str(value["bar_end"]))
        return MarketBar(
            security_id=state.security_id,
            timeframe=str(value["timeframe"]),
            bar_start=bar_start,
            bar_end=bar_end,
            open=float(value["open"]),
            high=float(value["high"]),
            low=float(value["low"]),
            close=float(value["close"]),
            volume=float(value["volume"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FeatureStoreError("CANONICAL_MARKET_BAR_PAYLOAD_INVALID") from exc
