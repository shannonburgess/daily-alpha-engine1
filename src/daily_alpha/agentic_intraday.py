"""Isolated Agentic Intraday V1 contracts for MU PAPER model validation.

This module intentionally does not mutate the existing SH24/SH25 swing books and
contains no broker or live-trading route. It defines the first intraday pilot's
clock, state machine, signal contract and conservative PAPER entry-risk envelope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

AGENTIC_INTRADAY_ACCOUNT = "PAPER_AGENTIC_INTRADAY_V1"
AGENTIC_INTRADAY_PILOT_SYMBOL = "MU"
AGENTIC_INTRADAY_SCHEMA = "2026-08-21-v1"
NEW_YORK = ZoneInfo("America/New_York")


class IntradayPhase(StrEnum):
    CLOSED = "CLOSED"
    OPENING_2M = "OPENING_2M"
    STANDARD_5M = "STANDARD_5M"
    MANAGEMENT_ONLY = "MANAGEMENT_ONLY"
    FLATTEN_ONLY = "FLATTEN_ONLY"


class IntradayAction(StrEnum):
    CONTEXT = "CONTEXT"
    ENTRY_LONG = "ENTRY_LONG"
    ADD = "ADD"
    PARTIAL = "PARTIAL"
    EXIT = "EXIT"


class IntradayState(StrEnum):
    DISCOVERED = "DISCOVERED"
    CONTEXT_APPROVED = "CONTEXT_APPROVED"
    WATCHING_2M = "WATCHING_2M"
    WATCHING_5M = "WATCHING_5M"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    RISK_APPROVED = "RISK_APPROVED"
    PAPER_OPEN = "PAPER_OPEN"
    MANAGED_5M = "MANAGED_5M"
    PARTIAL = "PARTIAL"
    EXITED = "EXITED"
    REJECTED = "REJECTED"
    FORENSICS_COMPLETE = "FORENSICS_COMPLETE"


@dataclass(frozen=True)
class IntradayRiskPolicy:
    """Conservative pilot limits; PAPER only."""

    max_risk_per_trade_nav: float = 0.0025
    max_new_risk_per_day_nav: float = 0.005
    max_new_trades_per_day: int = 2
    max_notional_per_trade_nav: float = 0.02
    min_company_price: float = 10.0
    min_average_daily_share_volume_exclusive: float = 1_500_000.0
    long_only: bool = True
    shares_only: bool = True
    averaging_down_allowed: bool = False
    overnight_positions_allowed: bool = False


@dataclass(frozen=True)
class IntradayPortfolioState:
    nav: float
    trades_opened_today: int = 0
    daily_new_risk_dollars: float = 0.0
    open_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.nav <= 0:
            raise ValueError("INTRADAY_NAV_MUST_BE_POSITIVE")
        if self.trades_opened_today < 0:
            raise ValueError("INTRADAY_TRADE_COUNT_INVALID")
        if self.daily_new_risk_dollars < 0:
            raise ValueError("INTRADAY_DAILY_RISK_INVALID")


@dataclass(frozen=True)
class IntradaySignalEvent:
    event_id: str
    action: IntradayAction
    timeframe: str
    price: float
    observed_at: datetime
    daily_context_approved: bool
    context_15m_approved: bool
    stock_stop_price: float | None = None
    average_daily_share_volume: float | None = None
    schema_version: str = AGENTIC_INTRADAY_SCHEMA
    source: str = "DAILY_ALPHA_AGENTIC_INTRADAY"
    account_id: str = AGENTIC_INTRADAY_ACCOUNT
    symbol: str = AGENTIC_INTRADAY_PILOT_SYMBOL
    instrument: str = "STOCK"
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class IntradayEntryDecision:
    approved: bool
    reasons: tuple[str, ...]
    phase: IntradayPhase
    required_timeframe: str | None
    share_quantity: int
    planned_risk_dollars: float
    planned_notional_dollars: float


_ALLOWED_TRANSITIONS: dict[IntradayState, frozenset[IntradayState]] = {
    IntradayState.DISCOVERED: frozenset(
        {IntradayState.CONTEXT_APPROVED, IntradayState.REJECTED}
    ),
    IntradayState.CONTEXT_APPROVED: frozenset(
        {
            IntradayState.WATCHING_2M,
            IntradayState.WATCHING_5M,
            IntradayState.REJECTED,
        }
    ),
    IntradayState.WATCHING_2M: frozenset(
        {IntradayState.ENTRY_TRIGGERED, IntradayState.WATCHING_5M, IntradayState.REJECTED}
    ),
    IntradayState.WATCHING_5M: frozenset(
        {IntradayState.ENTRY_TRIGGERED, IntradayState.REJECTED}
    ),
    IntradayState.ENTRY_TRIGGERED: frozenset(
        {IntradayState.RISK_APPROVED, IntradayState.REJECTED}
    ),
    IntradayState.RISK_APPROVED: frozenset(
        {IntradayState.PAPER_OPEN, IntradayState.REJECTED}
    ),
    IntradayState.PAPER_OPEN: frozenset(
        {IntradayState.MANAGED_5M, IntradayState.PARTIAL, IntradayState.EXITED}
    ),
    IntradayState.MANAGED_5M: frozenset(
        {IntradayState.PARTIAL, IntradayState.EXITED}
    ),
    IntradayState.PARTIAL: frozenset(
        {IntradayState.MANAGED_5M, IntradayState.EXITED}
    ),
    IntradayState.EXITED: frozenset({IntradayState.FORENSICS_COMPLETE}),
    IntradayState.REJECTED: frozenset({IntradayState.FORENSICS_COMPLETE}),
    IntradayState.FORENSICS_COMPLETE: frozenset(),
}


def intraday_phase(value: datetime) -> IntradayPhase:
    """Return the authoritative U.S. regular-session phase for an aware timestamp."""
    if value.tzinfo is None:
        raise ValueError("INTRADAY_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    local = value.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return IntradayPhase.CLOSED
    clock = local.time().replace(tzinfo=None)
    if time(9, 30) <= clock < time(10, 0):
        return IntradayPhase.OPENING_2M
    if time(10, 0) <= clock < time(15, 30):
        return IntradayPhase.STANDARD_5M
    if time(15, 30) <= clock < time(15, 50):
        return IntradayPhase.MANAGEMENT_ONLY
    if time(15, 50) <= clock < time(16, 0):
        return IntradayPhase.FLATTEN_ONLY
    return IntradayPhase.CLOSED


def required_entry_timeframe(phase: IntradayPhase) -> str | None:
    if phase == IntradayPhase.OPENING_2M:
        return "2M"
    if phase == IntradayPhase.STANDARD_5M:
        return "5M"
    return None


def management_timeframe(value: datetime) -> str | None:
    """Use 2M during the opening pilot and 5M for the remainder of the session."""
    phase = intraday_phase(value)
    if phase == IntradayPhase.OPENING_2M:
        return "2M"
    if phase in {
        IntradayPhase.STANDARD_5M,
        IntradayPhase.MANAGEMENT_ONLY,
        IntradayPhase.FLATTEN_ONLY,
    }:
        return "5M"
    return None


def must_flatten(value: datetime, *, has_open_position: bool) -> bool:
    if not has_open_position:
        return False
    return intraday_phase(value) in {IntradayPhase.FLATTEN_ONLY, IntradayPhase.CLOSED}


def advance_intraday_state(current: IntradayState, target: IntradayState) -> IntradayState:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"INTRADAY_STATE_TRANSITION_INVALID:{current.value}->{target.value}")
    return target


def validate_event_identity(event: IntradaySignalEvent) -> None:
    """Protect the pilot's isolation and safety boundary before any decision."""
    if event.schema_version != AGENTIC_INTRADAY_SCHEMA:
        raise ValueError("INTRADAY_SCHEMA_VERSION_INVALID")
    if not event.event_id.strip():
        raise ValueError("INTRADAY_EVENT_ID_REQUIRED")
    if event.account_id != AGENTIC_INTRADAY_ACCOUNT:
        raise ValueError("INTRADAY_ACCOUNT_ID_INVALID")
    if event.symbol.upper() != AGENTIC_INTRADAY_PILOT_SYMBOL:
        raise ValueError("INTRADAY_PILOT_SYMBOL_INVALID")
    if event.instrument.upper() != "STOCK":
        raise ValueError("INTRADAY_SHARES_ONLY")
    if event.trading_authorized is not False:
        raise ValueError("INTRADAY_LIVE_AUTHORIZATION_FORBIDDEN")
    if event.live_trading_enabled is not False:
        raise ValueError("INTRADAY_LIVE_TRADING_FORBIDDEN")
    if event.observed_at.tzinfo is None:
        raise ValueError("INTRADAY_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    if event.price <= 0 or not math.isfinite(event.price):
        raise ValueError("INTRADAY_PRICE_INVALID")
    if event.timeframe.upper() not in {"2M", "5M", "15M"}:
        raise ValueError("INTRADAY_TIMEFRAME_INVALID")
    if event.action == IntradayAction.CONTEXT and event.timeframe.upper() != "15M":
        raise ValueError("INTRADAY_CONTEXT_REQUIRES_15M")


def evaluate_intraday_entry(
    event: IntradaySignalEvent,
    portfolio: IntradayPortfolioState,
    policy: IntradayRiskPolicy | None = None,
) -> IntradayEntryDecision:
    """Evaluate a prospective long stock PAPER entry without mutating any ledger."""
    validate_event_identity(event)
    if event.action != IntradayAction.ENTRY_LONG:
        raise ValueError("INTRADAY_ENTRY_DECISION_REQUIRES_ENTRY_LONG")

    rules = policy or IntradayRiskPolicy()
    phase = intraday_phase(event.observed_at)
    required = required_entry_timeframe(phase)
    reasons: list[str] = []

    if required is None:
        reasons.append(f"ENTRY_NOT_ALLOWED_IN_{phase.value}")
    elif event.timeframe.upper() != required:
        reasons.append(f"ENTRY_REQUIRES_{required}")

    if not event.daily_context_approved:
        reasons.append("DAILY_CONTEXT_NOT_APPROVED")
    if not event.context_15m_approved:
        reasons.append("CONTEXT_15M_NOT_APPROVED")
    if event.price < rules.min_company_price:
        reasons.append("STOCK_PRICE_BELOW_CANONICAL_FLOOR")

    volume = event.average_daily_share_volume
    if volume is None or not math.isfinite(volume):
        reasons.append("LIQUIDITY_EVIDENCE_MISSING")
    elif volume <= rules.min_average_daily_share_volume_exclusive:
        reasons.append("LIQUIDITY_FILTERED")

    stop = event.stock_stop_price
    if stop is None or not math.isfinite(stop) or stop <= 0 or stop >= event.price:
        reasons.append("STOCK_STOP_INVALID_FOR_LONG_ENTRY")

    if event.symbol.upper() in {symbol.upper() for symbol in portfolio.open_symbols}:
        reasons.append("OPEN_INTRADAY_POSITION_ALREADY_EXISTS")
    if portfolio.trades_opened_today >= rules.max_new_trades_per_day:
        reasons.append("INTRADAY_DAILY_TRADE_LIMIT")

    max_daily_risk = portfolio.nav * rules.max_new_risk_per_day_nav
    max_trade_risk = portfolio.nav * rules.max_risk_per_trade_nav
    if portfolio.daily_new_risk_dollars >= max_daily_risk:
        reasons.append("INTRADAY_DAILY_RISK_LIMIT")

    share_quantity = 0
    planned_risk = 0.0
    planned_notional = 0.0
    if stop is not None and math.isfinite(stop) and 0 < stop < event.price:
        risk_per_share = event.price - stop
        risk_budget_remaining = max(0.0, max_daily_risk - portfolio.daily_new_risk_dollars)
        risk_budget = min(max_trade_risk, risk_budget_remaining)
        risk_limited_shares = math.floor(risk_budget / risk_per_share)
        notional_limited_shares = math.floor(
            (portfolio.nav * rules.max_notional_per_trade_nav) / event.price
        )
        share_quantity = max(0, min(risk_limited_shares, notional_limited_shares))
        planned_risk = share_quantity * risk_per_share
        planned_notional = share_quantity * event.price
        if share_quantity <= 0:
            reasons.append("INTRADAY_POSITION_SIZE_ZERO")

    approved = not reasons
    if not approved:
        share_quantity = 0
        planned_risk = 0.0
        planned_notional = 0.0

    return IntradayEntryDecision(
        approved=approved,
        reasons=tuple(dict.fromkeys(reasons)),
        phase=phase,
        required_timeframe=required,
        share_quantity=share_quantity,
        planned_risk_dollars=round(planned_risk, 2),
        planned_notional_dollars=round(planned_notional, 2),
    )
