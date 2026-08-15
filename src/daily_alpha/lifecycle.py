"""Auditable trade lifecycle and instrument-aware management rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .models import InstrumentSelected


class TradeState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ENTERED = "ENTERED"
    MANAGED = "MANAGED"
    EXITED = "EXITED"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    DATA_ERROR = "DATA_ERROR"


class ExitReason(StrEnum):
    STOP = "STOP"
    TARGET = "TARGET"
    TIME_STOP = "TIME_STOP"
    PINE_EXIT = "PINE_EXIT"
    TURTLE_EXIT = "TURTLE_EXIT"
    EXPIRATION_RISK = "EXPIRATION_RISK"
    ASSIGNMENT_RISK = "ASSIGNMENT_RISK"
    MANUAL_PAPER_EXIT = "MANUAL_PAPER_EXIT"
    TRAILING_STOP = "TRAILING_STOP"
    GAP_STOP = "GAP_STOP"
    EXERCISE_RISK = "EXERCISE_RISK"


class ManagementAction(StrEnum):
    HOLD = "HOLD"
    EXIT = "EXIT"
    ALERT = "ALERT"
    DATA_ERROR = "DATA_ERROR"
    SCALE_OUT = "SCALE_OUT"


ALLOWED_TRANSITIONS: dict[TradeState, frozenset[TradeState]] = {
    TradeState.PROPOSED: frozenset(
        {TradeState.APPROVED, TradeState.REJECTED, TradeState.CANCELLED, TradeState.DATA_ERROR}
    ),
    TradeState.APPROVED: frozenset(
        {TradeState.ENTERED, TradeState.CANCELLED, TradeState.DATA_ERROR}
    ),
    TradeState.ENTERED: frozenset({TradeState.MANAGED, TradeState.EXITED}),
    TradeState.MANAGED: frozenset({TradeState.MANAGED, TradeState.EXITED}),
    TradeState.EXITED: frozenset({TradeState.REVIEWED}),
    TradeState.REVIEWED: frozenset(),
    TradeState.REJECTED: frozenset({TradeState.REVIEWED}),
    TradeState.CANCELLED: frozenset({TradeState.REVIEWED}),
    TradeState.DATA_ERROR: frozenset({TradeState.REVIEWED}),
}


@dataclass(frozen=True)
class TradePlan:
    trade_id: str
    symbol: str
    instrument: InstrumentSelected
    entry_price: float
    stop_price: float
    target_price: float
    max_holding_days: int
    option_expiration: str | None = None
    minimum_exit_dte: int = 7
    scale_out_price: float | None = None
    scale_out_fraction: float = 0.5
    trailing_stop_percent: float | None = None
    allow_averaging_down: bool = False

    def __post_init__(self) -> None:
        if not self.trade_id or not self.symbol:
            raise ValueError("trade_id and symbol are required")
        if self.instrument == InstrumentSelected.NONE:
            raise ValueError("trade plan requires OPTION or STOCK")
        if min(self.entry_price, self.stop_price, self.target_price) <= 0:
            raise ValueError("entry, stop, and target prices must be positive")
        if not self.stop_price < self.entry_price < self.target_price:
            raise ValueError("long trade requires stop < entry < target")
        if self.max_holding_days <= 0 or self.minimum_exit_dte < 0:
            raise ValueError("holding and expiration controls are invalid")
        if self.instrument == InstrumentSelected.OPTION and not self.option_expiration:
            raise ValueError("option trade requires expiration")
        if self.scale_out_price is not None and self.scale_out_price <= self.entry_price:
            raise ValueError("scale-out price must exceed entry")
        if not 0 < self.scale_out_fraction < 1:
            raise ValueError("scale_out_fraction must be within (0, 1)")
        if self.trailing_stop_percent is not None and not 0 < self.trailing_stop_percent < 1:
            raise ValueError("trailing_stop_percent must be within (0, 1)")
        if self.allow_averaging_down:
            raise ValueError("averaging down requires a separately approved strategy")


@dataclass(frozen=True)
class TradeEvent:
    event_id: str
    trade_id: str
    sequence: int
    previous_state: TradeState | None
    state: TradeState
    reason: str
    occurred_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    actor: str = "SYSTEM"
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["previous_state"] = (
            None if self.previous_state is None else self.previous_state.value
        )
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True)
class TradeRecord:
    plan: TradePlan
    events: tuple[TradeEvent, ...]

    @property
    def state(self) -> TradeState:
        return self.events[-1].state


@dataclass(frozen=True)
class MarketObservation:
    price: float
    days_held: int
    pine_exit: bool = False
    turtle_exit: bool = False
    option_dte: int | None = None
    assignment_risk: bool = False
    corporate_action: bool = False
    data_error: bool = False
    stale_quote: bool = False
    halted: bool = False
    gap_below_stop: bool = False
    exercise_risk: bool = False
    earnings_within_days: int | None = None
    ex_dividend_within_days: int | None = None
    high_water_mark: float | None = None
    attempted_add_below_entry: bool = False


@dataclass(frozen=True)
class ManagementDecision:
    action: ManagementAction
    reason: str
    exit_reason: ExitReason | None = None
    size_fraction: float | None = None


class TradeLifecycleEngine:
    def create(self, plan: TradePlan, *, occurred_at: str | None = None) -> TradeRecord:
        event = TradeEvent(
            event_id=f"{plan.trade_id}:1",
            trade_id=plan.trade_id,
            sequence=1,
            previous_state=None,
            state=TradeState.PROPOSED,
            reason="TRADE_PROPOSED",
            occurred_at=occurred_at or datetime.now(UTC).isoformat(),
        )
        return TradeRecord(plan=plan, events=(event,))

    def transition(
        self,
        record: TradeRecord,
        *,
        new_state: TradeState,
        reason: str,
        occurred_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str = "SYSTEM",
        idempotency_key: str | None = None,
    ) -> TradeRecord:
        if not actor:
            raise ValueError("transition actor is required")
        if idempotency_key is not None:
            matching = [event for event in record.events if event.idempotency_key == idempotency_key]
            if matching:
                return record
        if new_state not in ALLOWED_TRANSITIONS[record.state]:
            raise ValueError(f"invalid transition: {record.state.value} -> {new_state.value}")
        if not reason:
            raise ValueError("transition reason is required")
        sequence = len(record.events) + 1
        event = TradeEvent(
            event_id=f"{record.plan.trade_id}:{sequence}",
            trade_id=record.plan.trade_id,
            sequence=sequence,
            previous_state=record.state,
            state=new_state,
            reason=reason,
            occurred_at=occurred_at or datetime.now(UTC).isoformat(),
            metadata=dict(metadata or {}),
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return TradeRecord(plan=record.plan, events=(*record.events, event))

    def evaluate_management(
        self,
        record: TradeRecord,
        observation: MarketObservation,
    ) -> ManagementDecision:
        if record.state not in {TradeState.ENTERED, TradeState.MANAGED}:
            raise ValueError("management evaluation requires an open paper trade")
        if observation.price <= 0 or observation.days_held < 0:
            raise ValueError("invalid market observation")
        if observation.data_error or observation.stale_quote:
            return ManagementDecision(ManagementAction.DATA_ERROR, "MARKET_DATA_ERROR")
        if observation.halted:
            return ManagementDecision(ManagementAction.ALERT, "TRADING_HALT")
        if observation.attempted_add_below_entry:
            return ManagementDecision(ManagementAction.ALERT, "AVERAGING_DOWN_PROHIBITED")
        if observation.exercise_risk and record.plan.instrument == InstrumentSelected.OPTION:
            return ManagementDecision(
                ManagementAction.EXIT, "OPTION_EXERCISE_RISK", ExitReason.EXERCISE_RISK
            )
        if observation.assignment_risk and record.plan.instrument == InstrumentSelected.OPTION:
            return ManagementDecision(
                ManagementAction.EXIT, "OPTION_ASSIGNMENT_RISK", ExitReason.ASSIGNMENT_RISK
            )
        if (
            record.plan.instrument == InstrumentSelected.OPTION
            and observation.option_dte is not None
            and observation.option_dte <= record.plan.minimum_exit_dte
        ):
            return ManagementDecision(
                ManagementAction.EXIT, "OPTION_EXPIRATION_WINDOW", ExitReason.EXPIRATION_RISK
            )
        if observation.gap_below_stop:
            return ManagementDecision(ManagementAction.EXIT, "GAP_BELOW_STOP", ExitReason.GAP_STOP)
        if observation.price <= record.plan.stop_price:
            return ManagementDecision(ManagementAction.EXIT, "STOP_REACHED", ExitReason.STOP)
        if (
            record.plan.trailing_stop_percent is not None
            and observation.high_water_mark is not None
            and observation.price
            <= observation.high_water_mark * (1 - record.plan.trailing_stop_percent)
        ):
            return ManagementDecision(
                ManagementAction.EXIT, "TRAILING_STOP", ExitReason.TRAILING_STOP
            )
        if (
            record.plan.scale_out_price is not None
            and observation.price >= record.plan.scale_out_price
        ):
            return ManagementDecision(
                ManagementAction.SCALE_OUT,
                "SCALE_OUT_TARGET",
                size_fraction=record.plan.scale_out_fraction,
            )
        if observation.price >= record.plan.target_price:
            return ManagementDecision(ManagementAction.EXIT, "TARGET_REACHED", ExitReason.TARGET)
        if observation.pine_exit:
            return ManagementDecision(ManagementAction.EXIT, "PINE_EXIT", ExitReason.PINE_EXIT)
        if observation.turtle_exit:
            return ManagementDecision(ManagementAction.EXIT, "TURTLE_EXIT", ExitReason.TURTLE_EXIT)
        if observation.days_held >= record.plan.max_holding_days:
            return ManagementDecision(ManagementAction.EXIT, "TIME_STOP", ExitReason.TIME_STOP)
        if observation.earnings_within_days is not None and observation.earnings_within_days <= 2:
            return ManagementDecision(ManagementAction.ALERT, "EARNINGS_REVIEW")
        if (
            observation.ex_dividend_within_days is not None
            and observation.ex_dividend_within_days <= 2
        ):
            return ManagementDecision(ManagementAction.ALERT, "DIVIDEND_REVIEW")
        if observation.corporate_action:
            return ManagementDecision(ManagementAction.ALERT, "CORPORATE_ACTION_REVIEW")
        return ManagementDecision(ManagementAction.HOLD, "NO_EXIT_TRIGGER")
