"""Isolated PAPER execution adapter for Agentic Intraday V1.

This module is deliberately separate from SH24/SH25 swing execution. It consumes
only already-approved Agentic Intraday controller instructions and writes STOCK
PAPER state to a ledger whose account is exactly PAPER_AGENTIC_INTRADAY_V1.

V1 uses confirmed strategy signal prices as model-validation fills. No broker call,
option entry, live authorization, overnight entry, discretionary AI override, ADD,
or PARTIAL execution is enabled here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .agentic_intraday import (
    AGENTIC_INTRADAY_ACCOUNT,
    AGENTIC_INTRADAY_PILOT_SYMBOL,
    IntradayPhase,
    IntradaySignalEvent,
    IntradayState,
    intraday_bar_phase,
    must_flatten,
    required_entry_timeframe,
    validate_event_identity,
)
from .agentic_intraday_controller import (
    IntradayAgentDecision,
    IntradayAgentOperation,
    IntradayAgentSnapshot,
    acknowledge_exit,
    acknowledge_paper_open,
)
from .execution_receipts import PaperExecutionReceipt, build_paper_execution_receipt
from .ledger import PaperTrade
from .models import InstrumentSelected

INTRADAY_EXECUTION_SCHEMA = "2026-08-21-agentic-intraday-paper-v1"
INTRADAY_ENTRY_REASON = "AGENTIC_INTRADAY_STOCK_PRIMARY_MODEL_VALIDATION"


class IntradayPaperExecutionError(RuntimeError):
    """Fail-closed PAPER execution contract violation."""


@dataclass(frozen=True)
class IntradayPaperReceipt:
    """Flattened, intraday-specific audit receipt for one applied PAPER lifecycle event."""

    schema_version: str
    action: str
    signal_id: str
    trade_id: str
    account_id: str
    symbol: str
    instrument: str
    timeframe: str
    phase: str
    fill_price: float
    fill_quantity: int
    fill_notional: float
    remaining_quantity: int
    average_entry_after: float | None
    stock_stop_price: float | None
    initial_risk_basis: float | None
    realized_pnl_this_event: float | None
    cumulative_realized_pnl: float | None
    realized_r_this_event: float | None
    r_basis_status: str
    reason: str
    occurred_at: str
    model_validation_fill: bool = True
    paper_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntradayPaperExecutionResult:
    snapshot: IntradayAgentSnapshot
    trade: PaperTrade
    receipt: IntradayPaperReceipt
    idempotent: bool = False


class AgenticIntradayPaperExecutor:
    """Apply approved MU intraday instructions to an isolated STOCK PAPER ledger."""

    def __init__(self, ledger: Any) -> None:
        account_id = str(getattr(ledger, "account_id", "") or "").strip()
        if account_id != AGENTIC_INTRADAY_ACCOUNT:
            raise IntradayPaperExecutionError("INTRADAY_LEDGER_ACCOUNT_INVALID")
        self.ledger = ledger

    def execute_entry(
        self,
        decision: IntradayAgentDecision,
    ) -> IntradayPaperExecutionResult:
        """Persist one approved PAPER stock entry at the confirmed signal price."""
        if decision.operation != IntradayAgentOperation.PAPER_ENTRY_READY:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_INSTRUCTION_REQUIRED")
        event = decision.entry_event
        if event is None:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_EVENT_REQUIRED")
        self._validate_entry(decision.snapshot, event, decision.share_quantity)

        existing = self.ledger.find_open(AGENTIC_INTRADAY_PILOT_SYMBOL, InstrumentSelected.STOCK)
        if existing:
            if len(existing) != 1 or existing[0].signal_id != event.event_id:
                raise IntradayPaperExecutionError("INTRADAY_OPEN_POSITION_CONFLICT")
            trade = existing[0]
            opened = acknowledge_paper_open(decision.snapshot, event_id=event.event_id)
            receipt = self._entry_receipt(trade, event, reason="IDEMPOTENT_ENTRY_REPLAY")
            return IntradayPaperExecutionResult(
                snapshot=opened,
                trade=trade,
                receipt=receipt,
                idempotent=True,
            )

        stop = float(event.stock_stop_price or 0.0)
        quantity = int(decision.share_quantity)
        initial_risk = round((event.price - stop) * quantity, 2)
        if initial_risk <= 0:
            raise IntradayPaperExecutionError("INTRADAY_INITIAL_RISK_INVALID")

        trade = self.ledger.open_trade(
            signal_id=event.event_id,
            symbol=event.symbol,
            instrument=InstrumentSelected.STOCK,
            quantity=quantity,
            entry_price=event.price,
            entry_time=event.observed_at,
            fallback_reason=INTRADAY_ENTRY_REASON,
            target_quantity=quantity,
            runner_stage="STARTER",
            initial_risk_basis=initial_risk,
        )
        opened = acknowledge_paper_open(decision.snapshot, event_id=event.event_id)
        receipt = self._entry_receipt(trade, event, reason=INTRADAY_ENTRY_REASON)
        return IntradayPaperExecutionResult(
            snapshot=opened,
            trade=trade,
            receipt=receipt,
        )

    def execute_exit(
        self,
        snapshot: IntradayAgentSnapshot,
        *,
        fill_price: float,
        occurred_at: datetime,
        signal_id: str,
        reason: str,
    ) -> IntradayPaperExecutionResult:
        """Apply a deterministic PAPER exit supplied by the future position manager."""
        self._validate_open_snapshot(snapshot)
        self._validate_exit_inputs(fill_price, occurred_at, signal_id, reason)
        return self._close_open_trade(
            snapshot,
            fill_price=fill_price,
            occurred_at=occurred_at,
            signal_id=signal_id,
            reason=reason,
        )

    def execute_mandatory_flatten(
        self,
        decision: IntradayAgentDecision,
        *,
        fill_price: float,
        occurred_at: datetime,
        signal_id: str,
    ) -> IntradayPaperExecutionResult:
        """Close the MU PAPER position when the clock governor requires a flat book."""
        if decision.operation != IntradayAgentOperation.FLATTEN_REQUIRED:
            raise IntradayPaperExecutionError("INTRADAY_FLATTEN_INSTRUCTION_REQUIRED")
        self._validate_open_snapshot(decision.snapshot)
        self._validate_exit_inputs(
            fill_price,
            occurred_at,
            signal_id,
            decision.reason,
        )
        if not must_flatten(occurred_at, has_open_position=True):
            raise IntradayPaperExecutionError("INTRADAY_FLATTEN_NOT_DUE")
        return self._close_open_trade(
            decision.snapshot,
            fill_price=fill_price,
            occurred_at=occurred_at,
            signal_id=signal_id,
            reason=decision.reason,
        )

    def execute_add(self, *_: Any, **__: Any) -> None:
        """Fail closed until deterministic V1 winner-add rules are separately approved."""
        raise IntradayPaperExecutionError("INTRADAY_ADD_NOT_ENABLED_V1")

    def execute_partial(self, *_: Any, **__: Any) -> None:
        """Fail closed until deterministic V1 partial-profit rules are separately approved."""
        raise IntradayPaperExecutionError("INTRADAY_PARTIAL_NOT_ENABLED_V1")

    def _close_open_trade(
        self,
        snapshot: IntradayAgentSnapshot,
        *,
        fill_price: float,
        occurred_at: datetime,
        signal_id: str,
        reason: str,
    ) -> IntradayPaperExecutionResult:
        open_trades = self.ledger.find_open(
            AGENTIC_INTRADAY_PILOT_SYMBOL,
            InstrumentSelected.STOCK,
        )
        if len(open_trades) != 1:
            raise IntradayPaperExecutionError("INTRADAY_OPEN_TRADE_STATE_MISMATCH")
        before = open_trades[0]
        if snapshot.share_quantity != before.quantity:
            raise IntradayPaperExecutionError("INTRADAY_SNAPSHOT_LEDGER_QUANTITY_MISMATCH")

        closed = self.ledger.close_trade(
            before,
            exit_price=fill_price,
            exit_time=occurred_at,
            signal_id=signal_id,
        )
        base = build_paper_execution_receipt(
            action="EXIT",
            paper={"closed_trades": [closed.to_dict()], "signal_id": signal_id},
            before_trade=before.to_dict(),
            fill_price=fill_price,
            account_id=AGENTIC_INTRADAY_ACCOUNT,
            initial_risk_basis=before.initial_risk_basis,
            occurred_at=occurred_at,
        )
        exited = acknowledge_exit(snapshot)
        receipt = self._intraday_receipt(
            base,
            timeframe=snapshot.manager_timeframe or "5M",
            occurred_at=occurred_at,
            stop_price=snapshot.stock_stop_price,
            reason=reason,
        )
        return IntradayPaperExecutionResult(
            snapshot=exited,
            trade=closed,
            receipt=receipt,
        )

    @staticmethod
    def _validate_entry(
        snapshot: IntradayAgentSnapshot,
        event: IntradaySignalEvent,
        share_quantity: int,
    ) -> None:
        validate_event_identity(event)
        if snapshot.account_id != AGENTIC_INTRADAY_ACCOUNT:
            raise IntradayPaperExecutionError("INTRADAY_SNAPSHOT_ACCOUNT_INVALID")
        if snapshot.symbol.upper() != AGENTIC_INTRADAY_PILOT_SYMBOL:
            raise IntradayPaperExecutionError("INTRADAY_SNAPSHOT_SYMBOL_INVALID")
        if snapshot.state != IntradayState.RISK_APPROVED:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_SNAPSHOT_STATE_INVALID")
        if snapshot.pending_entry_event_id != event.event_id:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_EVENT_ID_MISMATCH")
        if event.instrument.upper() != "STOCK":
            raise IntradayPaperExecutionError("INTRADAY_SHARES_ONLY")
        if event.action.value != "ENTRY_LONG":
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_ACTION_INVALID")
        phase = intraday_bar_phase(event.observed_at, event.timeframe)
        required = required_entry_timeframe(phase)
        if phase not in {IntradayPhase.OPENING_2M, IntradayPhase.STANDARD_5M} or required is None:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_OUTSIDE_ENTRY_WINDOW")
        if event.timeframe.upper() != required:
            raise IntradayPaperExecutionError(f"INTRADAY_ENTRY_REQUIRES_{required}")
        if share_quantity <= 0 or snapshot.share_quantity != share_quantity:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_QUANTITY_MISMATCH")
        stop = event.stock_stop_price
        if stop is None or stop <= 0 or stop >= event.price:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_STOP_INVALID")
        if snapshot.entry_price != event.price or snapshot.stock_stop_price != stop:
            raise IntradayPaperExecutionError("INTRADAY_ENTRY_SNAPSHOT_PRICE_STOP_MISMATCH")
        if snapshot.trading_authorized is not False or snapshot.live_trading_enabled is not False:
            raise IntradayPaperExecutionError("INTRADAY_LIVE_EXECUTION_FORBIDDEN")

    @staticmethod
    def _validate_open_snapshot(snapshot: IntradayAgentSnapshot) -> None:
        if snapshot.account_id != AGENTIC_INTRADAY_ACCOUNT:
            raise IntradayPaperExecutionError("INTRADAY_SNAPSHOT_ACCOUNT_INVALID")
        if snapshot.symbol.upper() != AGENTIC_INTRADAY_PILOT_SYMBOL:
            raise IntradayPaperExecutionError("INTRADAY_SNAPSHOT_SYMBOL_INVALID")
        if snapshot.state not in {
            IntradayState.PAPER_OPEN,
            IntradayState.MANAGED_5M,
            IntradayState.PARTIAL,
        }:
            raise IntradayPaperExecutionError("INTRADAY_EXIT_SNAPSHOT_STATE_INVALID")
        if snapshot.share_quantity <= 0:
            raise IntradayPaperExecutionError("INTRADAY_EXIT_SNAPSHOT_QUANTITY_INVALID")
        if snapshot.trading_authorized is not False or snapshot.live_trading_enabled is not False:
            raise IntradayPaperExecutionError("INTRADAY_LIVE_EXECUTION_FORBIDDEN")

    @staticmethod
    def _validate_exit_inputs(
        fill_price: float,
        occurred_at: datetime,
        signal_id: str,
        reason: str,
    ) -> None:
        if fill_price <= 0:
            raise IntradayPaperExecutionError("INTRADAY_EXIT_FILL_PRICE_INVALID")
        if occurred_at.tzinfo is None:
            raise IntradayPaperExecutionError("INTRADAY_EXIT_TIMESTAMP_MUST_BE_AWARE")
        if not signal_id.strip():
            raise IntradayPaperExecutionError("INTRADAY_EXIT_SIGNAL_ID_REQUIRED")
        if not reason.strip():
            raise IntradayPaperExecutionError("INTRADAY_EXIT_REASON_REQUIRED")

    @staticmethod
    def _entry_receipt(
        trade: PaperTrade,
        event: IntradaySignalEvent,
        *,
        reason: str,
    ) -> IntradayPaperReceipt:
        base = build_paper_execution_receipt(
            action="ENTRY_LONG",
            paper={"trade": trade.to_dict()},
            fill_price=event.price,
            account_id=AGENTIC_INTRADAY_ACCOUNT,
            initial_risk_basis=trade.initial_risk_basis,
            occurred_at=event.observed_at,
        )
        return AgenticIntradayPaperExecutor._intraday_receipt(
            base,
            timeframe=event.timeframe,
            occurred_at=event.observed_at,
            stop_price=event.stock_stop_price,
            reason=reason,
        )

    @staticmethod
    def _intraday_receipt(
        base: PaperExecutionReceipt,
        *,
        timeframe: str,
        occurred_at: datetime,
        stop_price: float | None,
        reason: str,
    ) -> IntradayPaperReceipt:
        when = occurred_at.astimezone(UTC)
        return IntradayPaperReceipt(
            schema_version=INTRADAY_EXECUTION_SCHEMA,
            action=base.action,
            signal_id=base.signal_id,
            trade_id=base.trade_id,
            account_id=AGENTIC_INTRADAY_ACCOUNT,
            symbol=base.symbol,
            instrument=base.instrument,
            timeframe=timeframe.upper(),
            phase=intraday_bar_phase(occurred_at, timeframe).value,
            fill_price=base.fill_price,
            fill_quantity=base.fill_quantity,
            fill_notional=base.fill_notional,
            remaining_quantity=base.remaining_quantity,
            average_entry_after=base.average_entry_after,
            stock_stop_price=stop_price,
            initial_risk_basis=base.initial_risk_basis,
            realized_pnl_this_event=base.realized_pnl_this_event,
            cumulative_realized_pnl=base.cumulative_realized_pnl,
            realized_r_this_event=base.realized_r_this_event,
            r_basis_status=base.r_basis_status,
            reason=reason,
            occurred_at=when.isoformat(),
        )
