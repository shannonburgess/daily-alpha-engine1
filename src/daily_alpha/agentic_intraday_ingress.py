"""Fail-closed ingress/enrichment for the isolated MU Agentic Intraday V1 sensor.

This module authenticates TradingView sensor telemetry and converts only verified
2M/5M execution bars into the existing deterministic IntradayMomentumObservation.
It performs no trade decision, ledger mutation, AWS deployment, broker call, or
live authorization. SH24/SH25 swing ingress remains separate and untouched.
"""

from __future__ import annotations

import base64
import hmac
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .agentic_intraday import AGENTIC_INTRADAY_ACCOUNT, AGENTIC_INTRADAY_PILOT_SYMBOL
from .agentic_intraday_momentum import IntradayMomentumObservation

SENSOR_SCHEMA = "2026-08-21-agentic-intraday-sensor-v1"
SENSOR_SOURCE = "TRADINGVIEW_AGENTIC_INTRADAY"
SENSOR_INSTRUMENT = "STOCK"


class AgenticIntradayIngressError(ValueError):
    """Base fail-closed sensor ingress error."""


class AgenticIntradayIngressAuthError(AgenticIntradayIngressError):
    """Sensor webhook authentication failed."""


@dataclass(frozen=True)
class AgenticIntradaySensorRecord:
    schema_version: str
    source: str
    event_id: str
    event_type: str
    account_id: str
    symbol: str
    instrument: str
    timeframe: str
    phase: str
    bar_time: datetime
    received_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None
    ema9: float | None
    ema20: float | None
    relative_volume: float | None
    average_daily_share_volume_30: float | None
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
    sensor_only: bool
    paper_only: bool
    trading_authorized: bool
    live_trading_enabled: bool


@dataclass(frozen=True)
class AgenticIntraday15mContext:
    event_id: str
    observed_at: datetime
    approved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AgenticIntradayServerContext:
    """Server-owned context that Pine is not allowed to authorize."""

    daily_context_approved: bool
    sector_context_approved: bool
    scheduled_macro_blackout: bool
    earnings_event_risk: bool


_EVENT_CONTRACT: dict[str, tuple[str, str]] = {
    "CONTEXT_15M_BAR": ("15M", "ANY_REGULAR"),
    "EXECUTION_2M_BAR": ("2M", "OPENING_2M"),
    "EXECUTION_5M_BAR": ("5M", "STANDARD_5M"),
    "MANAGEMENT_5M_BAR": ("5M", "MANAGEMENT_ONLY"),
    "FLATTEN_5M_BAR": ("5M", "FLATTEN_ONLY"),
}
_REGULAR_PHASES = {"OPENING_2M", "STANDARD_5M", "MANAGEMENT_ONLY", "FLATTEN_ONLY"}
_TIMEFRAME_NORMALIZATION = {
    "2": "2M",
    "2M": "2M",
    "5": "5M",
    "5M": "5M",
    "15": "15M",
    "15M": "15M",
}


def build_agentic_sensor_record(
    event: dict[str, Any],
    *,
    expected_secret: str,
    received_at: datetime | None = None,
    max_age_minutes: int = 15,
) -> AgenticIntradaySensorRecord:
    """Authenticate and normalize one TradingView raw sensor message."""
    if not expected_secret:
        raise AgenticIntradayIngressError("INTRADAY_WEBHOOK_SECRET_NOT_CONFIGURED")
    if max_age_minutes <= 0:
        raise AgenticIntradayIngressError("INTRADAY_MAX_AGE_INVALID")

    payload = _decode_event_body(event)
    supplied_secret = str(payload.pop("webhook_secret", ""))
    if not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
        raise AgenticIntradayIngressAuthError("INTRADAY_WEBHOOK_AUTH_FAILED")

    now = received_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise AgenticIntradayIngressError("INTRADAY_RECEIVED_AT_MUST_BE_AWARE")
    now = now.astimezone(UTC)

    schema_version = _required_text(payload, "schema_version")
    source = _required_text(payload, "source")
    event_id = _required_text(payload, "event_id")
    event_type = _required_text(payload, "event_type").upper()
    account_id = _required_text(payload, "account_id")
    symbol = _required_text(payload, "symbol").upper()
    instrument = _required_text(payload, "instrument").upper()
    timeframe = _normalize_timeframe(_required_text(payload, "timeframe"))
    phase = _required_text(payload, "phase").upper()
    bar_time = _parse_time(_required_text(payload, "bar_time"), field="bar_time")

    _validate_identity(
        schema_version=schema_version,
        source=source,
        account_id=account_id,
        symbol=symbol,
        instrument=instrument,
        event_type=event_type,
        timeframe=timeframe,
        phase=phase,
    )
    _validate_age(bar_time=bar_time, received_at=now, max_age_minutes=max_age_minutes)

    open_price = _required_float(payload, "open", positive=True)
    high = _required_float(payload, "high", positive=True)
    low = _required_float(payload, "low", positive=True)
    close = _required_float(payload, "close", positive=True)
    volume = _required_float(payload, "volume", non_negative=True)
    if high < low or not low <= open_price <= high or not low <= close <= high:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_OHLC_INVALID")

    record = AgenticIntradaySensorRecord(
        schema_version=schema_version,
        source=source,
        event_id=event_id,
        event_type=event_type,
        account_id=account_id,
        symbol=symbol,
        instrument=instrument,
        timeframe=timeframe,
        phase=phase,
        bar_time=bar_time,
        received_at=now,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=_optional_float(payload.get("vwap"), positive=True),
        ema9=_optional_float(payload.get("ema9"), positive=True),
        ema20=_optional_float(payload.get("ema20"), positive=True),
        relative_volume=_optional_float(payload.get("relative_volume"), non_negative=True),
        average_daily_share_volume_30=_optional_float(
            payload.get("average_daily_share_volume_30"), non_negative=True
        ),
        relative_strength_qqq_pct=_optional_float(payload.get("relative_strength_qqq_pct")),
        relative_strength_smh_pct=_optional_float(payload.get("relative_strength_smh_pct")),
        session_bar_count=_optional_int(payload.get("session_bar_count"), non_negative=True),
        session_high_prior=_optional_float(payload.get("session_high_prior"), positive=True),
        session_low_prior=_optional_float(payload.get("session_low_prior"), positive=True),
        high_3_prior=_optional_float(payload.get("high_3_prior"), positive=True),
        high_5_prior=_optional_float(payload.get("high_5_prior"), positive=True),
        high_10_prior=_optional_float(payload.get("high_10_prior"), positive=True),
        low_3_prior=_optional_float(payload.get("low_3_prior"), positive=True),
        low_5_prior=_optional_float(payload.get("low_5_prior"), positive=True),
        sensor_only=_required_bool(payload, "sensor_only"),
        paper_only=_required_bool(payload, "paper_only"),
        trading_authorized=_required_bool(payload, "trading_authorized"),
        live_trading_enabled=_required_bool(payload, "live_trading_enabled"),
    )
    _validate_safety(record)
    return record


def derive_agentic_15m_context(record: AgenticIntradaySensorRecord) -> AgenticIntraday15mContext:
    """Derive the bounded MU 15M price/trend context from raw sensor evidence."""
    if record.event_type != "CONTEXT_15M_BAR" or record.timeframe != "15M":
        raise AgenticIntradayIngressError("INTRADAY_15M_CONTEXT_RECORD_REQUIRED")

    reasons: list[str] = []
    if record.vwap is None:
        reasons.append("CONTEXT_15M_VWAP_MISSING")
    elif record.close <= record.vwap:
        reasons.append("CONTEXT_15M_PRICE_NOT_ABOVE_VWAP")
    if record.ema9 is None or record.ema20 is None:
        reasons.append("CONTEXT_15M_EMA_MISSING")
    elif record.ema9 <= record.ema20:
        reasons.append("CONTEXT_15M_EMA_NOT_ALIGNED")
    if record.relative_strength_smh_pct is None:
        reasons.append("CONTEXT_15M_RELATIVE_STRENGTH_MISSING")
    elif record.relative_strength_smh_pct <= 0:
        reasons.append("CONTEXT_15M_RELATIVE_STRENGTH_NOT_POSITIVE")

    return AgenticIntraday15mContext(
        event_id=record.event_id,
        observed_at=record.bar_time,
        approved=not reasons,
        reasons=tuple(reasons),
    )


def build_agentic_momentum_observation(
    record: AgenticIntradaySensorRecord,
    *,
    context_15m: AgenticIntraday15mContext,
    server_context: AgenticIntradayServerContext,
    max_context_age_minutes: int = 45,
    opening_range_bars: int = 3,
) -> IntradayMomentumObservation:
    """Enrich a verified 2M/5M sensor bar into the Stage-2 observation contract."""
    if max_context_age_minutes <= 0 or opening_range_bars <= 0:
        raise AgenticIntradayIngressError("INTRADAY_ENRICHMENT_POLICY_INVALID")
    if record.event_type not in {"EXECUTION_2M_BAR", "EXECUTION_5M_BAR"}:
        raise AgenticIntradayIngressError("INTRADAY_EXECUTION_SENSOR_RECORD_REQUIRED")
    _validate_context_chronology(
        context_15m=context_15m,
        execution_time=record.bar_time,
        max_age_minutes=max_context_age_minutes,
    )

    required = {
        "vwap": record.vwap,
        "relative_volume": record.relative_volume,
        "relative_strength_smh_pct": record.relative_strength_smh_pct,
        "average_daily_share_volume_30": record.average_daily_share_volume_30,
    }
    missing = tuple(name for name, value in required.items() if value is None)
    if missing:
        raise AgenticIntradayIngressError(
            "INTRADAY_SENSOR_ENRICHMENT_MISSING:" + ",".join(missing)
        )

    opening_range_established = False
    opening_range_high = None
    continuation_high = None
    ema9 = None
    ema20 = None

    if record.event_type == "EXECUTION_2M_BAR":
        if record.timeframe != "2M" or record.phase != "OPENING_2M":
            raise AgenticIntradayIngressError("INTRADAY_2M_PHASE_CONTRACT_INVALID")
        opening_range_established = (
            record.session_bar_count is not None
            and record.session_bar_count >= opening_range_bars
            and record.session_high_prior is not None
        )
        opening_range_high = record.session_high_prior
    else:
        if record.timeframe != "5M" or record.phase != "STANDARD_5M":
            raise AgenticIntradayIngressError("INTRADAY_5M_PHASE_CONTRACT_INVALID")
        continuation_high = record.high_3_prior
        ema9 = record.ema9
        ema20 = record.ema20

    return IntradayMomentumObservation(
        observation_id=record.event_id,
        timeframe=record.timeframe,
        observed_at=record.bar_time,
        close=record.close,
        high=record.high,
        low=record.low,
        vwap=float(record.vwap),
        relative_volume=float(record.relative_volume),
        relative_strength_pct=float(record.relative_strength_smh_pct),
        daily_context_approved=server_context.daily_context_approved,
        context_15m_approved=context_15m.approved,
        sector_context_approved=server_context.sector_context_approved,
        average_daily_share_volume=float(record.average_daily_share_volume_30),
        opening_range_established=opening_range_established,
        opening_range_high=opening_range_high,
        continuation_high=continuation_high,
        ema9=ema9,
        ema20=ema20,
        scheduled_macro_blackout=server_context.scheduled_macro_blackout,
        earnings_event_risk=server_context.earnings_event_risk,
        account_id=record.account_id,
        symbol=record.symbol,
    )


def _validate_identity(
    *,
    schema_version: str,
    source: str,
    account_id: str,
    symbol: str,
    instrument: str,
    event_type: str,
    timeframe: str,
    phase: str,
) -> None:
    if schema_version != SENSOR_SCHEMA:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_SCHEMA_INVALID")
    if source != SENSOR_SOURCE:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_SOURCE_INVALID")
    if account_id != AGENTIC_INTRADAY_ACCOUNT:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_ACCOUNT_INVALID")
    if symbol != AGENTIC_INTRADAY_PILOT_SYMBOL:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_SYMBOL_INVALID")
    if instrument != SENSOR_INSTRUMENT:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_STOCK_ONLY")
    contract = _EVENT_CONTRACT.get(event_type)
    if contract is None:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_EVENT_TYPE_INVALID")
    expected_timeframe, expected_phase = contract
    if timeframe != expected_timeframe:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_TIMEFRAME_MISMATCH")
    if expected_phase == "ANY_REGULAR":
        if phase not in _REGULAR_PHASES:
            raise AgenticIntradayIngressError("INTRADAY_SENSOR_CONTEXT_PHASE_INVALID")
    elif phase != expected_phase:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_PHASE_MISMATCH")


def _validate_safety(record: AgenticIntradaySensorRecord) -> None:
    if record.sensor_only is not True or record.paper_only is not True:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_PAPER_BOUNDARY_INVALID")
    if record.trading_authorized is not False:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_LIVE_AUTHORIZATION_FORBIDDEN")
    if record.live_trading_enabled is not False:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_LIVE_TRADING_FORBIDDEN")


def _validate_age(*, bar_time: datetime, received_at: datetime, max_age_minutes: int) -> None:
    delta = received_at - bar_time
    if delta.total_seconds() < -60:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_BAR_TIME_IN_FUTURE")
    if delta.total_seconds() > max_age_minutes * 60:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_EVENT_STALE")


def _validate_context_chronology(
    *,
    context_15m: AgenticIntraday15mContext,
    execution_time: datetime,
    max_age_minutes: int,
) -> None:
    delta = execution_time - context_15m.observed_at
    if delta.total_seconds() < 0:
        raise AgenticIntradayIngressError("INTRADAY_15M_CONTEXT_FROM_FUTURE")
    if delta.total_seconds() > max_age_minutes * 60:
        raise AgenticIntradayIngressError("INTRADAY_15M_CONTEXT_STALE")


def _decode_event_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if isinstance(body, dict):
        payload = dict(body)
    elif isinstance(body, str):
        text = body
        if event.get("isBase64Encoded") is True:
            try:
                text = base64.b64decode(text, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise AgenticIntradayIngressError("INTRADAY_WEBHOOK_BODY_BASE64_INVALID") from exc
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AgenticIntradayIngressError("INTRADAY_WEBHOOK_BODY_JSON_INVALID") from exc
        if not isinstance(decoded, dict):
            raise AgenticIntradayIngressError("INTRADAY_WEBHOOK_BODY_MUST_BE_OBJECT")
        payload = decoded
    else:
        raise AgenticIntradayIngressError("INTRADAY_WEBHOOK_BODY_REQUIRED")

    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > 16_384:
        raise AgenticIntradayIngressError("INTRADAY_WEBHOOK_BODY_TOO_LARGE")
    return payload


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field, "")).strip()
    if not value:
        raise AgenticIntradayIngressError(f"INTRADAY_SENSOR_{field.upper()}_REQUIRED")
    return value


def _required_float(
    payload: dict[str, Any],
    field: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    value = _optional_float(payload.get(field), positive=positive, non_negative=non_negative)
    if value is None:
        raise AgenticIntradayIngressError(f"INTRADAY_SENSOR_{field.upper()}_REQUIRED")
    return value


def _optional_float(
    value: Any,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_NUMERIC_INVALID") from exc
    if not math.isfinite(number):
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_NUMERIC_INVALID")
    if positive and number <= 0:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_NUMERIC_MUST_BE_POSITIVE")
    if non_negative and number < 0:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_NUMERIC_MUST_BE_NON_NEGATIVE")
    return number


def _optional_int(value: Any, *, non_negative: bool = False) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_INTEGER_INVALID")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_INTEGER_INVALID") from exc
    if non_negative and number < 0:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_INTEGER_MUST_BE_NON_NEGATIVE")
    return number


def _required_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise AgenticIntradayIngressError(f"INTRADAY_SENSOR_{field.upper()}_BOOLEAN_REQUIRED")
    return value


def _parse_time(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AgenticIntradayIngressError(f"INTRADAY_SENSOR_{field.upper()}_INVALID") from exc
    if parsed.tzinfo is None:
        raise AgenticIntradayIngressError(f"INTRADAY_SENSOR_{field.upper()}_MUST_BE_AWARE")
    return parsed.astimezone(UTC)


def _normalize_timeframe(value: str) -> str:
    normalized = _TIMEFRAME_NORMALIZATION.get(value.strip().upper())
    if normalized is None:
        raise AgenticIntradayIngressError("INTRADAY_SENSOR_TIMEFRAME_INVALID")
    return normalized
