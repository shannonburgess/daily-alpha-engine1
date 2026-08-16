"""Secure, paper-only TradingView/Pine webhook ingress normalization.

This module authenticates and validates webhook payloads before they are placed on
a durable queue. It never evaluates a trade, invokes a broker, or enables live
execution. The shared secret is removed before the normalized record is returned.
"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .signals import PineSignal, SignalError, parse_pine_signal


class PineIngressError(ValueError):
    """Base class for fail-closed webhook ingress errors."""


class PineIngressAuthError(PineIngressError):
    """Webhook authentication failed."""


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
    try:
        signal = parse_pine_signal(
            payload,
            received_at=now,
            max_age_minutes=max_age_minutes,
        )
    except SignalError:
        raise

    return _record_from_signal(signal)


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


def _record_from_signal(signal: PineSignal) -> PineIngressRecord:
    return PineIngressRecord(
        schema_version="2026-08-16-v1",
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
    )
