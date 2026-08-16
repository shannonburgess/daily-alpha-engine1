"""Authenticated, idempotent TradingView webhook boundary."""

from __future__ import annotations

import json
from collections.abc import MutableSet
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Any

from .signals import PineSignal, SignalError, parse_pine_signal


class WebhookError(ValueError):
    """Webhook request cannot be trusted or processed."""


@dataclass(frozen=True)
class WebhookReceipt:
    accepted: bool
    duplicate: bool
    reason: str
    signal: PineSignal | None = None


class SignalWebhook:
    """Validate alerts only; this boundary never places or simulates an order."""

    def __init__(self, *, secret: str, claimed_signal_ids: MutableSet[str]) -> None:
        if not secret:
            raise ValueError("TRADINGVIEW_WEBHOOK_SECRET is required")
        self._secret = secret
        self._claimed = claimed_signal_ids

    def receive(
        self,
        body: str | dict[str, Any],
        *,
        received_at: datetime | None = None,
    ) -> WebhookReceipt:
        payload = self._decode(body)
        supplied = str(payload.pop("webhook_secret", ""))
        if not supplied or not compare_digest(supplied, self._secret):
            raise WebhookError("UNAUTHORIZED_WEBHOOK")
        signal_id = str(payload.get("signal_id", "")).strip()
        if not signal_id:
            raise WebhookError("SIGNAL_ID_REQUIRED")
        if signal_id in self._claimed:
            return WebhookReceipt(False, True, "DUPLICATE_SIGNAL")
        try:
            signal = parse_pine_signal(
                payload,
                received_at=received_at or datetime.now(UTC),
            )
        except SignalError as exc:
            raise WebhookError(f"INVALID_SIGNAL:{exc}") from exc
        self._claimed.add(signal.signal_id)
        return WebhookReceipt(True, False, "SIGNAL_ACCEPTED", signal)

    @staticmethod
    def _decode(body: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(body, dict):
            return dict(body)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise WebhookError("INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise WebhookError("JSON_OBJECT_REQUIRED")
        return payload
