"""Agent controller for the isolated MU intraday PAPER pilot.

The controller owns deterministic state transitions and decision orchestration only.
It never writes to a ledger and never calls a broker. A later execution adapter may
consume PAPER_ENTRY_READY or FLATTEN_REQUIRED instructions after this contract is
validated.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .agentic_intraday import (
    AGENTIC_INTRADAY_ACCOUNT,
    AGENTIC_INTRADAY_PILOT_SYMBOL,
    IntradayPhase,
    IntradayPortfolioState,
    IntradaySignalEvent,
    IntradayState,
    advance_intraday_state,
    evaluate_intraday_entry,
    intraday_phase,
    management_timeframe,
    must_flatten,
)
from .agentic_intraday_momentum import (
    IntradayMomentumObservation,
    build_intraday_entry_event,
    evaluate_mu_momentum_signal,
)


class IntradayAgentOperation(StrEnum):
    NO_ACTION = "NO_ACTION"
    PAPER_ENTRY_READY = "PAPER_ENTRY_READY"
    TRANSFER_TO_5M = "TRANSFER_TO_5M"
    MANAGEMENT_ONLY = "MANAGEMENT_ONLY"
    FLATTEN_REQUIRED = "FLATTEN_REQUIRED"


@dataclass(frozen=True)
class IntradayAgentSnapshot:
    symbol: str = AGENTIC_INTRADAY_PILOT_SYMBOL
    account_id: str = AGENTIC_INTRADAY_ACCOUNT
    state: IntradayState = IntradayState.DISCOVERED
    last_observation_id: str | None = None
    pending_entry_event_id: str | None = None
    manager_timeframe: str | None = None
    entry_price: float | None = None
    stock_stop_price: float | None = None
    share_quantity: int = 0
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class IntradayAgentDecision:
    operation: IntradayAgentOperation
    reason: str
    snapshot: IntradayAgentSnapshot
    signal_reasons: tuple[str, ...] = ()
    risk_reasons: tuple[str, ...] = ()
    entry_event: IntradaySignalEvent | None = None
    share_quantity: int = 0
    idempotent: bool = False


def evaluate_agent_observation(
    snapshot: IntradayAgentSnapshot,
    observation: IntradayMomentumObservation,
    portfolio: IntradayPortfolioState,
) -> IntradayAgentDecision:
    """Move one point-in-time MU observation through signal and risk gates."""
    _validate_snapshot(snapshot)
    if snapshot.last_observation_id == observation.observation_id:
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.NO_ACTION,
            reason="DUPLICATE_OBSERVATION",
            snapshot=snapshot,
            idempotent=True,
        )
    if snapshot.state in {
        IntradayState.RISK_APPROVED,
        IntradayState.PAPER_OPEN,
        IntradayState.MANAGED_5M,
        IntradayState.PARTIAL,
        IntradayState.EXITED,
        IntradayState.FORENSICS_COMPLETE,
    }:
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.NO_ACTION,
            reason=f"OBSERVATION_NOT_ACCEPTED_IN_{snapshot.state.value}",
            snapshot=replace(snapshot, last_observation_id=observation.observation_id),
        )

    working = _move_to_watch_state(snapshot, observation)
    signal = evaluate_mu_momentum_signal(observation)
    if not signal.triggered:
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.NO_ACTION,
            reason="MOMENTUM_SIGNAL_NOT_TRIGGERED",
            snapshot=replace(working, last_observation_id=observation.observation_id),
            signal_reasons=signal.reasons,
        )

    triggered = replace(
        working,
        state=advance_intraday_state(working.state, IntradayState.ENTRY_TRIGGERED),
        last_observation_id=observation.observation_id,
    )
    entry_event = build_intraday_entry_event(observation, signal)
    risk = evaluate_intraday_entry(entry_event, portfolio)
    if not risk.approved:
        rejected = replace(
            triggered,
            state=advance_intraday_state(triggered.state, IntradayState.REJECTED),
        )
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.NO_ACTION,
            reason="INTRADAY_RISK_REJECTED",
            snapshot=rejected,
            risk_reasons=risk.reasons,
        )

    approved = replace(
        triggered,
        state=advance_intraday_state(triggered.state, IntradayState.RISK_APPROVED),
        pending_entry_event_id=entry_event.event_id,
        manager_timeframe=entry_event.timeframe,
        entry_price=entry_event.price,
        stock_stop_price=entry_event.stock_stop_price,
        share_quantity=risk.share_quantity,
    )
    return IntradayAgentDecision(
        operation=IntradayAgentOperation.PAPER_ENTRY_READY,
        reason="SIGNAL_AND_RISK_APPROVED",
        snapshot=approved,
        entry_event=entry_event,
        share_quantity=risk.share_quantity,
    )


def acknowledge_paper_open(
    snapshot: IntradayAgentSnapshot,
    *,
    event_id: str,
) -> IntradayAgentSnapshot:
    """Advance only after an external PAPER executor confirms a matching open."""
    _validate_snapshot(snapshot)
    if snapshot.state != IntradayState.RISK_APPROVED:
        raise ValueError("INTRADAY_PAPER_OPEN_ACK_STATE_INVALID")
    if not snapshot.pending_entry_event_id or event_id != snapshot.pending_entry_event_id:
        raise ValueError("INTRADAY_PAPER_OPEN_ACK_EVENT_MISMATCH")
    return replace(
        snapshot,
        state=advance_intraday_state(snapshot.state, IntradayState.PAPER_OPEN),
        pending_entry_event_id=None,
    )


def evaluate_agent_clock(
    snapshot: IntradayAgentSnapshot,
    *,
    now: datetime,
) -> IntradayAgentDecision:
    """Issue deterministic handoff/management/flatten instructions for an open PAPER state."""
    _validate_snapshot(snapshot)
    phase = intraday_phase(now)
    open_state = snapshot.state in {
        IntradayState.PAPER_OPEN,
        IntradayState.MANAGED_5M,
        IntradayState.PARTIAL,
    }
    if not open_state:
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.NO_ACTION,
            reason="NO_OPEN_INTRADAY_AGENT_STATE",
            snapshot=snapshot,
        )

    if must_flatten(now, has_open_position=True):
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.FLATTEN_REQUIRED,
            reason="MANDATORY_INTRADAY_FLATTEN",
            snapshot=snapshot,
        )

    if phase == IntradayPhase.MANAGEMENT_ONLY:
        manager = management_timeframe(now)
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.MANAGEMENT_ONLY,
            reason="NEW_ENTRIES_DISABLED_MANAGEMENT_ONLY",
            snapshot=replace(snapshot, manager_timeframe=manager),
        )

    manager = management_timeframe(now)
    if (
        phase == IntradayPhase.STANDARD_5M
        and snapshot.state == IntradayState.PAPER_OPEN
        and snapshot.manager_timeframe == "2M"
    ):
        transferred = replace(
            snapshot,
            state=advance_intraday_state(snapshot.state, IntradayState.MANAGED_5M),
            manager_timeframe="5M",
        )
        return IntradayAgentDecision(
            operation=IntradayAgentOperation.TRANSFER_TO_5M,
            reason="OPENING_POSITION_TRANSFERRED_TO_5M_MANAGER",
            snapshot=transferred,
        )

    return IntradayAgentDecision(
        operation=IntradayAgentOperation.NO_ACTION,
        reason="NO_CLOCK_ACTION_REQUIRED",
        snapshot=replace(snapshot, manager_timeframe=manager or snapshot.manager_timeframe),
    )


def acknowledge_exit(snapshot: IntradayAgentSnapshot) -> IntradayAgentSnapshot:
    _validate_snapshot(snapshot)
    if snapshot.state not in {
        IntradayState.PAPER_OPEN,
        IntradayState.MANAGED_5M,
        IntradayState.PARTIAL,
    }:
        raise ValueError("INTRADAY_EXIT_ACK_STATE_INVALID")
    return replace(
        snapshot,
        state=advance_intraday_state(snapshot.state, IntradayState.EXITED),
        manager_timeframe=None,
        share_quantity=0,
    )


def complete_forensics(snapshot: IntradayAgentSnapshot) -> IntradayAgentSnapshot:
    _validate_snapshot(snapshot)
    if snapshot.state not in {IntradayState.EXITED, IntradayState.REJECTED}:
        raise ValueError("INTRADAY_FORENSICS_STATE_INVALID")
    return replace(
        snapshot,
        state=advance_intraday_state(snapshot.state, IntradayState.FORENSICS_COMPLETE),
    )


def _move_to_watch_state(
    snapshot: IntradayAgentSnapshot,
    observation: IntradayMomentumObservation,
) -> IntradayAgentSnapshot:
    if not (
        observation.daily_context_approved
        and observation.context_15m_approved
        and observation.sector_context_approved
    ):
        return snapshot

    phase = intraday_phase(observation.observed_at)
    if phase == IntradayPhase.OPENING_2M:
        target = IntradayState.WATCHING_2M
    elif phase == IntradayPhase.STANDARD_5M:
        target = IntradayState.WATCHING_5M
    else:
        return snapshot

    working = snapshot
    if working.state == IntradayState.DISCOVERED:
        working = replace(
            working,
            state=advance_intraday_state(
                working.state,
                IntradayState.CONTEXT_APPROVED,
            ),
        )

    can_move_to_target = working.state == IntradayState.CONTEXT_APPROVED or (
        working.state == IntradayState.WATCHING_2M
        and target == IntradayState.WATCHING_5M
    )
    if can_move_to_target:
        working = replace(
            working,
            state=advance_intraday_state(working.state, target),
        )
    return working


def _validate_snapshot(snapshot: IntradayAgentSnapshot) -> None:
    if snapshot.account_id != AGENTIC_INTRADAY_ACCOUNT:
        raise ValueError("INTRADAY_AGENT_ACCOUNT_INVALID")
    if snapshot.symbol.upper() != AGENTIC_INTRADAY_PILOT_SYMBOL:
        raise ValueError("INTRADAY_AGENT_SYMBOL_INVALID")
    if snapshot.trading_authorized is not False:
        raise ValueError("INTRADAY_AGENT_LIVE_AUTHORIZATION_FORBIDDEN")
    if snapshot.live_trading_enabled is not False:
        raise ValueError("INTRADAY_AGENT_LIVE_TRADING_FORBIDDEN")
