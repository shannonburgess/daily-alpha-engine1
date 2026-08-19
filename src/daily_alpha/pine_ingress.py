"""Secure, paper-only TradingView/Pine webhook ingress normalization.

This module authenticates and validates webhook payloads before they are placed on
a durable queue. It never evaluates a trade, invokes a broker, or enables live
execution. The shared secret is removed before the normalized record is returned.
"""

from __future__ import annotations

import base64
import hmac
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .signals import PineSignal, SignalAction, parse_pine_signal


class PineIngressError(ValueError):
    """Base class for fail-closed webhook ingress errors."""


class PineIngressAuthError(PineIngressError):
    """Webhook authentication failed."""


ENTRY_TYPES = {"NORMAL_BREAKOUT", "ARMED_BREAKOUT_CONFIRM", "EARNINGS_GAP_GO"}
EARNINGS_GAP_CLASSES = {
    "NONE",
    "EARNINGS_GAP_GO",
    "EARNINGS_GAP_GO_EARLY",
    "EARNINGS_GAP_CRAP",
    "EARNINGS_WAIT",
}
SHADOW_MODEL_IDS = {"PAPER_SHADOW_V24", "PAPER_SHADOW_V25"}


@dataclass(frozen=True)
class PineIngressRecord:
    schema_version: str
    source: str
    signal_id: str
    symbol: str
    action: str
    strategy: str
    strategy_version: str
    timeframe: str
    price: float
    bar_time: str
    received_at: str
    position_fraction: float | None = None
    runner_stage: str | None = None
    model_id: str | None = None
    stock_stop_price: float | None = None
    average_daily_dollar_volume: float | None = None
    entry_type: str | None = None
    earnings_gap_class: str | None = None
    earnings_gap_pct: float | None = None
    earnings_gap_atr: float | None = None
    earnings_close_location: float | None = None
    earnings_gap_retention: float | None = None
    earnings_relative_volume: float | None = None
    trading_authorized: bool = False
    paper_execution_triggered: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_pine_ingress_record(
    event: dict[str, Any],
    *,
    expected_secret: str,
    received_at: datetime | None = None,
    max_age_minutes: int = 30,
) -> PineIngressRecord:
    """Authenticate an API Gateway-style event and normalize one Pine signal."""
    if not expected_secret:
        raise PineIngressError("PINE_WEBHOOK_SECRET_NOT_CONFIGURED")
    if max_age_minutes <= 0:
        raise PineIngressError("max_age_minutes must be positive")

    payload = _decode_event_body(event)
    supplied_secret = str(payload.pop("webhook_secret", ""))
    if not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
        raise PineIngressAuthError("WEBHOOK_AUTH_FAILED")

    now = received_at or datetime.now(UTC)
    signal = parse_pine_signal(
        payload,
        received_at=now,
        max_age_minutes=max_age_minutes,
    )
    return _record_from_signal(signal, payload)


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
                raise PineIngressError("WEBHOOK_BODY_BASE64_INVALID") from exc
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PineIngressError("WEBHOOK_BODY_JSON_INVALID") from exc
        if not isinstance(decoded, dict):
            raise PineIngressError("WEBHOOK_BODY_MUST_BE_OBJECT")
        payload = decoded
    else:
        raise PineIngressError("WEBHOOK_BODY_REQUIRED")

    # Limit attack surface and accidental oversized TradingView alert payloads.
    if len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 16_384:
        raise PineIngressError("WEBHOOK_BODY_TOO_LARGE")
    return payload


def _record_from_signal(
    signal: PineSignal,
    payload: dict[str, Any],
) -> PineIngressRecord:
    stock_stop_price = None
    average_daily_dollar_volume = None
    entry_type = _optional_tag(payload.get("entry_type"), "entry_type", ENTRY_TYPES)
    earnings_gap_class = _optional_tag(
        payload.get("earnings_gap_class"),
        "earnings_gap_class",
        EARNINGS_GAP_CLASSES,
    )
    model_id = _optional_model_id(payload.get("model_id"), signal.strategy_version)
    earnings_gap_pct = None
    earnings_gap_atr = None
    earnings_close_location = None
    earnings_gap_retention = None
    earnings_relative_volume = None

    if signal.action == SignalAction.ENTRY_LONG:
        stop_value = payload.get("stock_stop_price")
        if stop_value not in (None, ""):
            try:
                stock_stop_price = float(stop_value)
            except (TypeError, ValueError) as exc:
                raise PineIngressError("stock_stop_price must be numeric") from exc
            if stock_stop_price <= 0 or stock_stop_price >= signal.price:
                raise PineIngressError("stock_stop_price must be positive and below price")

        adv_value = payload.get("average_daily_dollar_volume")
        if adv_value not in (None, ""):
            try:
                average_daily_dollar_volume = float(adv_value)
            except (TypeError, ValueError) as exc:
                raise PineIngressError(
                    "average_daily_dollar_volume must be numeric"
                ) from exc
            if average_daily_dollar_volume < 0:
                raise PineIngressError(
                    "average_daily_dollar_volume must be non-negative"
                )

        if signal.strategy_version in {"2.4", "2.5"} and entry_type is None:
            raise PineIngressError(
                f"entry_type is required for strategy {signal.strategy_version} entries"
            )

        earnings_gap_pct = _optional_float(payload.get("earnings_gap_pct"), "earnings_gap_pct")
        earnings_gap_atr = _optional_float(payload.get("earnings_gap_atr"), "earnings_gap_atr")
        earnings_close_location = _optional_float(
            payload.get("earnings_close_location"), "earnings_close_location"
        )
        earnings_gap_retention = _optional_float(
            payload.get("earnings_gap_retention"), "earnings_gap_retention"
        )
        earnings_relative_volume = _optional_float(
            payload.get("earnings_relative_volume"), "earnings_relative_volume"
        )

        if entry_type == "EARNINGS_GAP_GO":
            if earnings_gap_class != "EARNINGS_GAP_GO":
                raise PineIngressError(
                    "EARNINGS_GAP_GO entry requires matching earnings_gap_class"
                )
            required_metrics = {
                "earnings_gap_pct": earnings_gap_pct,
                "earnings_gap_atr": earnings_gap_atr,
                "earnings_close_location": earnings_close_location,
                "earnings_gap_retention": earnings_gap_retention,
                "earnings_relative_volume": earnings_relative_volume,
            }
            if any(value is None for value in required_metrics.values()):
                raise PineIngressError(
                    "EARNINGS_GAP_GO entry requires complete earnings metrics"
                )

    schema_version = (
        "2026-08-18-v5"
        if signal.strategy_version == "2.5" or model_id is not None
        else "2026-08-16-v4"
    )
    return PineIngressRecord(
        schema_version=schema_version,
        source="TRADINGVIEW_PINE",
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        action=signal.action.value,
        strategy=signal.strategy,
        strategy_version=signal.strategy_version,
        timeframe=signal.timeframe,
        price=signal.price,
        bar_time=signal.bar_time.isoformat(),
        received_at=signal.received_at.isoformat(),
        position_fraction=signal.position_fraction,
        runner_stage=signal.runner_stage,
        model_id=model_id,
        stock_stop_price=stock_stop_price,
        average_daily_dollar_volume=average_daily_dollar_volume,
        entry_type=entry_type,
        earnings_gap_class=earnings_gap_class,
        earnings_gap_pct=earnings_gap_pct,
        earnings_gap_atr=earnings_gap_atr,
        earnings_close_location=earnings_close_location,
        earnings_gap_retention=earnings_gap_retention,
        earnings_relative_volume=earnings_relative_volume,
    )


def _optional_model_id(value: Any, strategy_version: str) -> str | None:
    if value in (None, ""):
        if strategy_version == "2.5":
            raise PineIngressError("model_id PAPER_SHADOW_V25 is required for strategy 2.5")
        return None
    model_id = str(value).strip().upper()
    if model_id not in SHADOW_MODEL_IDS:
        raise PineIngressError("model_id is invalid")
    expected = {
        "2.4": "PAPER_SHADOW_V24",
        "2.5": "PAPER_SHADOW_V25",
    }.get(strategy_version)
    if expected is not None and model_id != expected:
        raise PineIngressError(
            f"model_id {model_id} does not match strategy version {strategy_version}"
        )
    return model_id


def _optional_tag(value: Any, name: str, allowed: set[str]) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if text not in allowed:
        raise PineIngressError(f"{name} is invalid")
    return text


def _optional_float(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PineIngressError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise PineIngressError(f"{name} must be finite")
    return number
