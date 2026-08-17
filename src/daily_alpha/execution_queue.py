"""Next-session execution rules for confirmed Daily Alpha v2.4 close signals.

The close scanner stages actions only. This module decides whether a staged action
may be converted into a fresh execution-time scanner signal during the next regular
session. It never executes a trade itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .execution_universe import ScannerState

PENDING_STATUS = "PENDING_NEXT_SESSION"
EXECUTE_STATUS = "EXECUTE_NEXT_SESSION"
CANCEL_STATUS = "CANCELLED_NEXT_SESSION"
WAIT_STATUS = "WAIT_NEXT_SESSION"


@dataclass(frozen=True)
class NextSessionDecision:
    status: str
    reason: str
    signal: dict[str, Any] | None

    @property
    def should_execute(self) -> bool:
        return self.status == EXECUTE_STATUS and self.signal is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_pending_action(
    *,
    symbol: str,
    action: str,
    reason: str,
    signal: dict[str, Any],
    market_date: str,
    created_at: datetime,
    state_before: ScannerState | None,
    state_after: ScannerState | None,
) -> dict[str, Any]:
    timestamp = _aware(created_at)
    return {
        "schema_version": "2026-08-17-pending-v1",
        "status": PENDING_STATUS,
        "created_at": timestamp.isoformat(),
        "market_date": market_date,
        "symbol": symbol.upper(),
        "action": action.upper(),
        "reason": reason,
        "signal": dict(signal),
        "state_before": state_before.to_dict() if state_before else None,
        "state_after": state_after.to_dict() if state_after else None,
        "attempt_count": 0,
    }


def prepare_next_session_signal(
    pending: dict[str, Any],
    *,
    stock_price: float,
    now: datetime,
) -> NextSessionDecision:
    timestamp = _aware(now)
    if stock_price <= 0:
        raise ValueError("Next-session stock price must be positive")
    if str(pending.get("status", "")) not in {PENDING_STATUS, "RETRY_DATA_ERROR"}:
        return NextSessionDecision(WAIT_STATUS, "PENDING_ACTION_NOT_EXECUTABLE", None)

    market_date = str(pending.get("market_date", ""))
    if not market_date:
        raise ValueError("Pending action market_date is required")
    local_date = timestamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if market_date >= local_date:
        return NextSessionDecision(WAIT_STATUS, "NOT_NEXT_TRADING_SESSION_YET", None)

    action = str(pending.get("action", "")).upper()
    signal = dict(pending.get("signal") or {})
    if action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
        raise ValueError("Pending action is unsupported")
    if str(signal.get("action", "")).upper() != action:
        raise ValueError("Pending action/signal mismatch")

    before = _state(pending.get("state_before"))
    after = _state(pending.get("state_after"))

    if action == "ENTRY_LONG":
        if after is None:
            raise ValueError("Pending ENTRY_LONG requires proposed scanner state")
        stop = float(signal.get("stock_stop_price", 0) or 0)
        if stock_price <= max(stop, after.entry_breakout_level):
            return NextSessionDecision(
                CANCEL_STATUS,
                "CANCEL_BREAKOUT_NO_LONGER_VALID",
                None,
            )
        add1_level = after.runner_base_entry + after.runner_base_atr
        if stock_price >= add1_level:
            return NextSessionDecision(
                CANCEL_STATUS,
                "CANCEL_CHASE_ALREADY_AT_ADD1_LEVEL",
                None,
            )

    if action == "ADD":
        if before is None:
            raise ValueError("Pending ADD requires prior scanner state")
        stage = str(signal.get("runner_stage", "")).upper()
        multiple = {"ADD_1_ATR": 1.0, "ADD_2_ATR": 2.0}.get(stage)
        if multiple is None:
            raise ValueError("Pending ADD runner stage is invalid")
        trigger = before.runner_base_entry + multiple * before.runner_base_atr
        if stock_price < trigger:
            return NextSessionDecision(
                CANCEL_STATUS,
                "CANCEL_RUNNER_TRIGGER_NOT_PRESENT_AT_EXECUTION",
                None,
            )

    if action == "PARTIAL":
        if before is None:
            raise ValueError("Pending PARTIAL requires prior scanner state")
        trigger = before.runner_base_entry + 3.0 * before.runner_base_atr
        if stock_price < trigger:
            return NextSessionDecision(
                CANCEL_STATUS,
                "CANCEL_HARVEST_TRIGGER_NOT_PRESENT_AT_EXECUTION",
                None,
            )

    origin_signal_id = str(signal.get("signal_id", ""))
    origin_price = float(signal.get("price", 0) or 0)
    origin_bar_time = str(signal.get("bar_time", ""))
    signal.update(
        {
            "signal_id": (
                f"{origin_signal_id}-EXEC-"
                f"{timestamp.strftime('%Y%m%dT%H%M%S')}"
            ),
            "price": float(stock_price),
            "bar_time": timestamp.isoformat(),
            "origin_signal_id": origin_signal_id,
            "origin_signal_price": origin_price,
            "origin_signal_bar_time": origin_bar_time,
            "origin_market_date": market_date,
            "execution_timing": "NEXT_REGULAR_SESSION",
        }
    )
    return NextSessionDecision(EXECUTE_STATUS, "NEXT_SESSION_REVALIDATED", signal)


def _state(value: Any) -> ScannerState | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise TypeError("Pending scanner state must be an object")
    return ScannerState.from_dict(value)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
