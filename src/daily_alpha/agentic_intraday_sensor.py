"""Validate and enrich Agentic Intraday V1 TradingView sensor events.

TradingView is a raw market-data sensor only. This bridge validates the hard MU /
PAPER identity, converts Pine telemetry into typed records, evaluates the frozen-
candidate 15-minute technical context, and combines execution bars with server-side
Daily Alpha, sector, event-risk and canonical liquidity evidence.

No broker/live route or ledger mutation is present here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from .agentic_intraday import (
    AGENTIC_INTRADAY_ACCOUNT,
    AGENTIC_INTRADAY_PILOT_SYMBOL,
    IntradayPhase,
    intraday_bar_phase,
)
from .agentic_intraday_momentum import IntradayMomentumObservation

SENSOR_SCHEMA = "2026-08-21-agentic-intraday-sensor-v1"
SENSOR_SOURCE = "TRADINGVIEW_AGENTIC_INTRADAY"


class IntradaySensorError(ValueError):
    """Fail-closed sensor or enrichment contract error."""


class IntradaySensorEventType(StrEnum):
    CONTEXT_15M_BAR = "CONTEXT_15M_BAR"
    EXECUTION_2M_BAR = "EXECUTION_2M_BAR"
    EXECUTION_5M_BAR = "EXECUTION_5M_BAR"
    MANAGEMENT_5M_BAR = "MANAGEMENT_5M_BAR"
    FLATTEN_5M_BAR = "FLATTEN_5M_BAR"


@dataclass(frozen=True)
class IntradaySensorBar:
    event_id: str
    event_type: IntradaySensorEventType
    timeframe: str
    phase: IntradayPhase
    observed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    ema9: float | None
    ema20: float | None
    relative_volume: float | None
    sensor_average_daily_share_volume_30: float | None
    relative_strength_qqq_pct: float | None
    relative_strength_smh_pct: float | None
    session_bar_count: int | None
    session_high_prior: float | None
    session_low_prior: float | None
    high_3_prior: float | None
    high_5_prior: float | None
    high_10_prior: float | None
    low_3_prior: float | None
    low_5_prior: float | None
    account_id: str = AGENTIC_INTRADAY_ACCOUNT
    symbol: str = AGENTIC_INTRADAY_PILOT_SYMBOL
    instrument: str = "STOCK"
    source: str = SENSOR_SOURCE
    schema_version: str = SENSOR_SCHEMA
    sensor_only: bool = True
    paper_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class Intraday15mContextDecision:
    approved: bool
    reasons: tuple[str, ...]
    observed_at: datetime


@dataclass(frozen=True)
class IntradayServerContext:
    """Server-authoritative context joined to one execution sensor bar."""

    daily_context_approved: bool
    sector_context_approved: bool
    context_15m_approved: bool
    canonical_average_daily_share_volume: float | None
    scheduled_macro_blackout: bool = False
    earnings_event_risk: bool = False


@dataclass(frozen=True)
class IntradayObservationBridgePolicy:
    """Explicit candidate mapping rules to freeze before forward testing."""

    opening_range_minutes: int = 6
    continuation_lookback_bars: int = 3
    relative_strength_source: str = "QQQ"

    def __post_init__(self) -> None:
        if self.opening_range_minutes not in {6, 10, 20}:
            raise ValueError("INTRADAY_OPENING_RANGE_MINUTES_UNSUPPORTED")
        if self.continuation_lookback_bars not in {3, 5, 10}:
            raise ValueError("INTRADAY_CONTINUATION_LOOKBACK_UNSUPPORTED")
        if self.relative_strength_source.upper() not in {"QQQ", "SMH"}:
            raise ValueError("INTRADAY_RELATIVE_STRENGTH_SOURCE_INVALID")


def parse_intraday_sensor_payload(payload: Mapping[str, Any]) -> IntradaySensorBar:
    """Parse one already-authenticated TradingView sensor JSON object."""
    schema = _text(payload, "schema_version")
    source = _text(payload, "source")
    event_id = _text(payload, "event_id")
    account_id = _text(payload, "account_id")
    symbol = _text(payload, "symbol").upper()
    instrument = _text(payload, "instrument").upper()
    event_type_text = _text(payload, "event_type")
    phase_text = _text(payload, "phase")
    timeframe_raw = _text(payload, "timeframe").upper()

    if schema != SENSOR_SCHEMA:
        raise IntradaySensorError("INTRADAY_SENSOR_SCHEMA_INVALID")
    if source != SENSOR_SOURCE:
        raise IntradaySensorError("INTRADAY_SENSOR_SOURCE_INVALID")
    if account_id != AGENTIC_INTRADAY_ACCOUNT:
        raise IntradaySensorError("INTRADAY_SENSOR_ACCOUNT_INVALID")
    if symbol != AGENTIC_INTRADAY_PILOT_SYMBOL:
        raise IntradaySensorError("INTRADAY_SENSOR_SYMBOL_INVALID")
    if instrument != "STOCK":
        raise IntradaySensorError("INTRADAY_SENSOR_SHARES_ONLY")
    if payload.get("sensor_only") is not True or payload.get("paper_only") is not True:
        raise IntradaySensorError("INTRADAY_SENSOR_PAPER_IDENTITY_INVALID")
    if payload.get("trading_authorized") is not False:
        raise IntradaySensorError("INTRADAY_SENSOR_LIVE_AUTHORIZATION_FORBIDDEN")
    if payload.get("live_trading_enabled") is not False:
        raise IntradaySensorError("INTRADAY_SENSOR_LIVE_TRADING_FORBIDDEN")

    try:
        event_type = IntradaySensorEventType(event_type_text)
        declared_phase = IntradayPhase(phase_text)
    except ValueError as exc:
        raise IntradaySensorError("INTRADAY_SENSOR_EVENT_OR_PHASE_INVALID") from exc

    timeframe = {"2": "2M", "5": "5M", "15": "15M"}.get(timeframe_raw)
    if timeframe is None:
        raise IntradaySensorError("INTRADAY_SENSOR_TIMEFRAME_INVALID")

    observed_at = _timestamp(payload, "bar_time")
    if event_type == IntradaySensorEventType.CONTEXT_15M_BAR:
        # Pine session state is based on the context bar's open, while bar_time is
        # the close. A 09:45-10:00 15M bar can therefore declare OPENING_2M even
        # though its close timestamp is 10:00. Context only needs to be regular-session.
        if declared_phase == IntradayPhase.CLOSED:
            raise IntradaySensorError("INTRADAY_15M_CONTEXT_OUTSIDE_SESSION")
    else:
        actual_phase = intraday_bar_phase(observed_at, timeframe)
        if declared_phase != actual_phase:
            raise IntradaySensorError("INTRADAY_SENSOR_PHASE_TIMESTAMP_MISMATCH")
    _validate_event_type_contract(event_type, timeframe, declared_phase)

    open_price = _required_number(payload, "open")
    high = _required_number(payload, "high")
    low = _required_number(payload, "low")
    close = _required_number(payload, "close")
    volume = _required_number(payload, "volume")
    vwap = _required_number(payload, "vwap")
    if min(open_price, high, low, close, vwap) <= 0:
        raise IntradaySensorError("INTRADAY_SENSOR_PRICE_INVALID")
    if high < low or not low <= close <= high or not low <= open_price <= high:
        raise IntradaySensorError("INTRADAY_SENSOR_BAR_RANGE_INVALID")
    if volume < 0:
        raise IntradaySensorError("INTRADAY_SENSOR_VOLUME_INVALID")

    bar = IntradaySensorBar(
        event_id=event_id,
        event_type=event_type,
        timeframe=timeframe,
        phase=declared_phase,
        observed_at=observed_at,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=vwap,
        ema9=_optional_number(payload.get("ema9")),
        ema20=_optional_number(payload.get("ema20")),
        relative_volume=_optional_number(payload.get("relative_volume")),
        sensor_average_daily_share_volume_30=_optional_number(
            payload.get("average_daily_share_volume_30")
        ),
        relative_strength_qqq_pct=_optional_number(payload.get("relative_strength_qqq_pct")),
        relative_strength_smh_pct=_optional_number(payload.get("relative_strength_smh_pct")),
        session_bar_count=_optional_int(payload.get("session_bar_count")),
        session_high_prior=_optional_number(payload.get("session_high_prior")),
        session_low_prior=_optional_number(payload.get("session_low_prior")),
        high_3_prior=_optional_number(payload.get("high_3_prior")),
        high_5_prior=_optional_number(payload.get("high_5_prior")),
        high_10_prior=_optional_number(payload.get("high_10_prior")),
        low_3_prior=_optional_number(payload.get("low_3_prior")),
        low_5_prior=_optional_number(payload.get("low_5_prior")),
    )
    _validate_optional_sensor_values(bar)
    return bar


def evaluate_15m_technical_context(bar: IntradaySensorBar) -> Intraday15mContextDecision:
    """Evaluate the candidate V1 15M technical context from a confirmed context bar."""
    if bar.event_type != IntradaySensorEventType.CONTEXT_15M_BAR or bar.timeframe != "15M":
        raise IntradaySensorError("INTRADAY_15M_CONTEXT_EVENT_REQUIRED")
    reasons: list[str] = []
    if bar.close <= bar.vwap:
        reasons.append("CONTEXT_15M_PRICE_NOT_ABOVE_VWAP")
    if bar.ema9 is None or bar.ema20 is None:
        reasons.append("CONTEXT_15M_EMA_MISSING")
    elif bar.ema9 <= bar.ema20:
        reasons.append("CONTEXT_15M_EMA_NOT_ALIGNED")
    if bar.relative_strength_qqq_pct is None:
        reasons.append("CONTEXT_15M_RELATIVE_STRENGTH_MISSING")
    elif bar.relative_strength_qqq_pct <= 0:
        reasons.append("CONTEXT_15M_RELATIVE_STRENGTH_NOT_POSITIVE")
    return Intraday15mContextDecision(
        approved=not reasons,
        reasons=tuple(reasons),
        observed_at=bar.observed_at,
    )


def build_momentum_observation(
    bar: IntradaySensorBar,
    context: IntradayServerContext,
    policy: IntradayObservationBridgePolicy | None = None,
) -> IntradayMomentumObservation:
    """Join raw execution telemetry with server-side policy/context evidence."""
    rules = policy or IntradayObservationBridgePolicy()
    if bar.event_type not in {
        IntradaySensorEventType.EXECUTION_2M_BAR,
        IntradaySensorEventType.EXECUTION_5M_BAR,
    }:
        raise IntradaySensorError("INTRADAY_EXECUTION_SENSOR_BAR_REQUIRED")
    if bar.relative_volume is None:
        raise IntradaySensorError("INTRADAY_RELATIVE_VOLUME_REQUIRED")

    canonical_volume = context.canonical_average_daily_share_volume
    if canonical_volume is None or not math.isfinite(canonical_volume) or canonical_volume < 0:
        raise IntradaySensorError("INTRADAY_CANONICAL_LIQUIDITY_REQUIRED")

    relative_strength = (
        bar.relative_strength_qqq_pct
        if rules.relative_strength_source.upper() == "QQQ"
        else bar.relative_strength_smh_pct
    )
    if relative_strength is None:
        raise IntradaySensorError("INTRADAY_RELATIVE_STRENGTH_REQUIRED")

    opening_range_established = False
    opening_range_high: float | None = None
    continuation_high: float | None = None
    if bar.event_type == IntradaySensorEventType.EXECUTION_2M_BAR:
        opening_bars = rules.opening_range_minutes // 2
        opening_range_established = (
            bar.session_bar_count is not None and bar.session_bar_count >= opening_bars
        )
        if opening_range_established:
            opening_range_high = _prior_high(bar, opening_bars)
    else:
        continuation_high = _prior_high(bar, rules.continuation_lookback_bars)

    return IntradayMomentumObservation(
        observation_id=bar.event_id,
        timeframe=bar.timeframe,
        observed_at=bar.observed_at,
        close=bar.close,
        high=bar.high,
        low=bar.low,
        vwap=bar.vwap,
        relative_volume=bar.relative_volume,
        relative_strength_pct=relative_strength,
        daily_context_approved=context.daily_context_approved,
        context_15m_approved=context.context_15m_approved,
        sector_context_approved=context.sector_context_approved,
        average_daily_share_volume=canonical_volume,
        opening_range_established=opening_range_established,
        opening_range_high=opening_range_high,
        continuation_high=continuation_high,
        ema9=bar.ema9,
        ema20=bar.ema20,
        scheduled_macro_blackout=context.scheduled_macro_blackout,
        earnings_event_risk=context.earnings_event_risk,
        account_id=bar.account_id,
        symbol=bar.symbol,
    )


def _validate_event_type_contract(
    event_type: IntradaySensorEventType,
    timeframe: str,
    phase: IntradayPhase,
) -> None:
    expected: dict[IntradaySensorEventType, tuple[str, IntradayPhase | None]] = {
        IntradaySensorEventType.CONTEXT_15M_BAR: ("15M", None),
        IntradaySensorEventType.EXECUTION_2M_BAR: ("2M", IntradayPhase.OPENING_2M),
        IntradaySensorEventType.EXECUTION_5M_BAR: ("5M", IntradayPhase.STANDARD_5M),
        IntradaySensorEventType.MANAGEMENT_5M_BAR: ("5M", IntradayPhase.MANAGEMENT_ONLY),
        IntradaySensorEventType.FLATTEN_5M_BAR: ("5M", IntradayPhase.FLATTEN_ONLY),
    }
    required_timeframe, required_phase = expected[event_type]
    if timeframe != required_timeframe:
        raise IntradaySensorError("INTRADAY_SENSOR_EVENT_TIMEFRAME_MISMATCH")
    if required_phase is not None and phase != required_phase:
        raise IntradaySensorError("INTRADAY_SENSOR_EVENT_PHASE_MISMATCH")
    if event_type == IntradaySensorEventType.CONTEXT_15M_BAR and phase == IntradayPhase.CLOSED:
        raise IntradaySensorError("INTRADAY_15M_CONTEXT_OUTSIDE_SESSION")


def _validate_optional_sensor_values(bar: IntradaySensorBar) -> None:
    numeric = (
        bar.ema9,
        bar.ema20,
        bar.relative_volume,
        bar.sensor_average_daily_share_volume_30,
        bar.relative_strength_qqq_pct,
        bar.relative_strength_smh_pct,
        bar.session_high_prior,
        bar.session_low_prior,
        bar.high_3_prior,
        bar.high_5_prior,
        bar.high_10_prior,
        bar.low_3_prior,
        bar.low_5_prior,
    )
    if any(value is not None and not math.isfinite(value) for value in numeric):
        raise IntradaySensorError("INTRADAY_SENSOR_OPTIONAL_NUMERIC_INVALID")
    if bar.relative_volume is not None and bar.relative_volume < 0:
        raise IntradaySensorError("INTRADAY_SENSOR_RELATIVE_VOLUME_INVALID")
    if (
        bar.sensor_average_daily_share_volume_30 is not None
        and bar.sensor_average_daily_share_volume_30 < 0
    ):
        raise IntradaySensorError("INTRADAY_SENSOR_DAILY_VOLUME_INVALID")
    if bar.session_bar_count is not None and bar.session_bar_count < 0:
        raise IntradaySensorError("INTRADAY_SENSOR_SESSION_BAR_COUNT_INVALID")


def _prior_high(bar: IntradaySensorBar, bars: int) -> float | None:
    return {
        3: bar.high_3_prior,
        5: bar.high_5_prior,
        10: bar.high_10_prior,
    }[bars]


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "") or "").strip()
    if not value:
        raise IntradaySensorError(f"INTRADAY_SENSOR_{key.upper()}_REQUIRED")
    return value


def _timestamp(payload: Mapping[str, Any], key: str) -> datetime:
    value = _text(payload, key)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntradaySensorError("INTRADAY_SENSOR_TIMESTAMP_INVALID") from exc
    if result.tzinfo is None:
        raise IntradaySensorError("INTRADAY_SENSOR_TIMESTAMP_MUST_BE_AWARE")
    return result


def _required_number(payload: Mapping[str, Any], key: str) -> float:
    value = _optional_number(payload.get(key))
    if value is None:
        raise IntradaySensorError(f"INTRADAY_SENSOR_{key.upper()}_REQUIRED")
    return value


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise IntradaySensorError("INTRADAY_SENSOR_NUMERIC_INVALID") from exc
    if not math.isfinite(result):
        raise IntradaySensorError("INTRADAY_SENSOR_NUMERIC_INVALID")
    return result


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise IntradaySensorError("INTRADAY_SENSOR_INTEGER_INVALID")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise IntradaySensorError("INTRADAY_SENSOR_INTEGER_INVALID") from exc
    return result
