"""Auditable paper execution receipts for Daily Alpha lifecycle events.

Receipts describe what the paper engine actually applied, not what the signal
intended. They are derived from the durable trade state plus the exact execution
price supplied by the paper executor. Live execution is never authorized here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class PaperExecutionReceipt:
    schema_version: str
    action: str
    signal_id: str
    trade_id: str
    account_id: str | None
    symbol: str
    instrument: str
    option_expiration: str | None
    option_strike: float | None
    option_type: str | None
    fill_price: float
    fill_quantity: int
    fill_notional: float
    remaining_quantity: int
    remaining_cost_basis: float
    average_entry_after: float | None
    realized_pnl_this_event: float | None
    cumulative_realized_pnl: float | None
    initial_risk_basis: float | None
    realized_r_this_event: float | None
    r_basis_status: str
    runner_stage_after: str | None
    occurred_at: str
    paper_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_paper_execution_receipt(
    *,
    action: str,
    paper: dict[str, Any],
    fill_price: float,
    before_trade: dict[str, Any] | None = None,
    account_id: str | None = None,
    initial_risk_basis: float | None = None,
    occurred_at: datetime | None = None,
) -> PaperExecutionReceipt:
    """Build one normalized receipt from an executed paper lifecycle event."""
    normalized_action = action.strip().upper()
    if normalized_action not in {"ENTRY_LONG", "ADD", "PARTIAL", "EXIT"}:
        raise ValueError("EXECUTION_RECEIPT_ACTION_INVALID")
    if fill_price <= 0:
        raise ValueError("EXECUTION_RECEIPT_FILL_PRICE_INVALID")

    after_trade = _paper_trade(paper, normalized_action)
    before = dict(before_trade or {})
    symbol = str(after_trade.get("symbol", "")).strip().upper()
    instrument = str(after_trade.get("instrument", "")).strip().upper()
    signal_id = _signal_id(paper, after_trade, normalized_action)
    trade_id = str(after_trade.get("trade_id", "")).strip()
    if not symbol or instrument not in {"OPTION", "STOCK"} or not trade_id:
        raise ValueError("EXECUTION_RECEIPT_TRADE_IDENTITY_INVALID")

    multiplier = 100 if instrument == "OPTION" else 1
    after_quantity = int(after_trade.get("quantity", 0) or 0)
    before_quantity = int(before.get("quantity", 0) or 0)

    if normalized_action == "ENTRY_LONG":
        fill_quantity = after_quantity
        remaining_quantity = after_quantity
    elif normalized_action == "ADD":
        fill_quantity = after_quantity - before_quantity
        remaining_quantity = after_quantity
    elif normalized_action == "PARTIAL":
        fill_quantity = before_quantity - after_quantity
        remaining_quantity = after_quantity
    else:
        fill_quantity = before_quantity or after_quantity
        remaining_quantity = 0

    if fill_quantity <= 0:
        raise ValueError("EXECUTION_RECEIPT_FILL_QUANTITY_INVALID")

    average_entry = _optional_float(after_trade.get("entry_price"))
    remaining_cost_basis = (
        remaining_quantity * (average_entry or 0.0) * multiplier
        if remaining_quantity > 0
        else 0.0
    )
    fill_notional = fill_quantity * float(fill_price) * multiplier

    before_realized = _optional_float(before.get("realized_pnl")) or 0.0
    cumulative_realized = _optional_float(after_trade.get("realized_pnl"))
    realized_this_event = None
    if normalized_action in {"PARTIAL", "EXIT"} and cumulative_realized is not None:
        realized_this_event = round(cumulative_realized - before_realized, 2)

    initial_risk = _optional_float(initial_risk_basis)
    realized_r = None
    if realized_this_event is not None and initial_risk is not None and initial_risk > 0:
        realized_r = round(realized_this_event / initial_risk, 6)
        r_basis_status = "AVAILABLE"
    elif realized_this_event is None:
        r_basis_status = "NO_REALIZED_PNL_YET"
    else:
        r_basis_status = "INITIAL_RISK_NOT_PERSISTED"

    when = occurred_at or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    return PaperExecutionReceipt(
        schema_version="2026-08-19-paper-receipt-v1",
        action=normalized_action,
        signal_id=signal_id,
        trade_id=trade_id,
        account_id=account_id or paper.get("account_id"),
        symbol=symbol,
        instrument=instrument,
        option_expiration=_optional_text(after_trade.get("option_expiration")),
        option_strike=_optional_float(after_trade.get("option_strike")),
        option_type=_optional_text(after_trade.get("option_type")),
        fill_price=round(float(fill_price), 8),
        fill_quantity=fill_quantity,
        fill_notional=round(fill_notional, 2),
        remaining_quantity=remaining_quantity,
        remaining_cost_basis=round(remaining_cost_basis, 2),
        average_entry_after=average_entry,
        realized_pnl_this_event=realized_this_event,
        cumulative_realized_pnl=cumulative_realized,
        initial_risk_basis=initial_risk,
        realized_r_this_event=realized_r,
        r_basis_status=r_basis_status,
        runner_stage_after=_optional_text(after_trade.get("runner_stage")),
        occurred_at=when.astimezone(UTC).isoformat(),
    )


def _paper_trade(paper: dict[str, Any], action: str) -> dict[str, Any]:
    if action == "ENTRY_LONG":
        value = paper.get("trade")
    elif action in {"ADD", "PARTIAL"}:
        values = paper.get("updated_trades")
        value = values[0] if isinstance(values, list) and len(values) == 1 else None
    else:
        values = paper.get("closed_trades")
        value = values[0] if isinstance(values, list) and len(values) == 1 else None
    if not isinstance(value, dict):
        raise TypeError("EXECUTION_RECEIPT_TRADE_RESULT_INVALID")
    return dict(value)


def _signal_id(paper: dict[str, Any], trade: dict[str, Any], action: str) -> str:
    if action == "ENTRY_LONG":
        value = trade.get("signal_id")
    elif action == "ADD":
        stage = str(paper.get("runner_stage", "")).upper()
        value = (
            trade.get("add1_signal_id")
            if stage == "ADD_1_ATR"
            else trade.get("add2_signal_id")
        )
    elif action == "PARTIAL":
        value = trade.get("harvest_signal_id")
    else:
        value = paper.get("signal_id") or trade.get("signal_id")
    text = str(value or "").strip()
    if not text:
        # Existing CLOSE paper results do not yet persist the exit signal id in the
        # returned trade object. The receipt remains attributable to the trade even
        # when this legacy field is unavailable.
        return "UNAVAILABLE_LEGACY_SIGNAL_ID"
    return text


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
