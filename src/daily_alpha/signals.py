"""Validated TradingView/Pine signal events for the Daily Alpha pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class SignalError(ValueError):
    """Raised when a signal payload is incomplete, invalid, or stale."""


class SignalAction(StrEnum):
    ENTRY_LONG = "ENTRY_LONG"
    EXIT = "EXIT"


@dataclass(frozen=True)
class PineSignal:
    signal_id: str
    symbol: str
    action: SignalAction
    strategy: str
    strategy_version: str
    timeframe: str
    price: float
    bar_time: datetime
    received_at: datetime

    @property
    def is_entry(self) -> bool:
        return self.action == SignalAction.ENTRY_LONG

    @property
    def is_exit(self) -> bool:
        return self.action == SignalAction.EXIT


def parse_pine_signal(
    payload: str | dict[str, Any],
    *,
    received_at: datetime | None = None,
    max_age_minutes: int = 30,
) -> PineSignal:
    """Parse the JSON produced by the approved TradingView Pine alert."""
    data = _decode(payload)
    now = _aware(received_at or datetime.now(UTC))

    symbol = str(data.get("symbol", "")).strip().upper()
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        raise SignalError("Signal contains an invalid symbol")

    try:
        action = SignalAction(str(data.get("action", "")).strip().upper())
    except ValueError as exc:
        raise SignalError("action must be ENTRY_LONG or EXIT") from exc

    strategy = str(data.get("strategy", "")).strip()
    strategy_version = str(data.get("strategy_version", "")).strip()
    timeframe = str(data.get("timeframe", "")).strip()
    if not strategy or not strategy_version or not timeframe:
        raise SignalError("strategy, strategy_version, and timeframe are required")

    price = _positive_float(data.get("price"), "price")
    bar_time = _timestamp(data.get("bar_time"))
    age_minutes = (now - bar_time).total_seconds() / 60
    if age_minutes < -1:
        raise SignalError("Signal bar_time is in the future")
    if age_minutes > max_age_minutes:
        raise SignalError(
            f"Signal is stale: {age_minutes:.1f} minutes old (limit {max_age_minutes})"
        )

    signal_id = str(data.get("signal_id", "")).strip() or str(uuid4())
    return PineSignal(
        signal_id=signal_id,
        symbol=symbol,
        action=action,
        strategy=strategy,
        strategy_version=strategy_version,
        timeframe=timeframe,
        price=price,
        bar_time=bar_time,
        received_at=now,
    )


def _decode(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SignalError("Signal payload is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SignalError("Signal JSON must be an object")
    return decoded


def _timestamp(value: Any) -> datetime:
    if not value:
        raise SignalError("bar_time is required")
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise SignalError("bar_time must be an ISO-8601 timestamp") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _positive_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SignalError(f"{name} must be numeric") from exc
    if number <= 0:
        raise SignalError(f"{name} must be positive")
    return number
