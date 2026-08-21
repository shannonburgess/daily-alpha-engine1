"""Deterministic MU intraday momentum signal baseline for Agentic Intraday V1.

This module converts point-in-time intraday observations into a reproducible PAPER
entry signal. It performs no ledger mutation and contains no broker/live route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .agentic_intraday import (
    AGENTIC_INTRADAY_ACCOUNT,
    AGENTIC_INTRADAY_PILOT_SYMBOL,
    IntradayAction,
    IntradayPhase,
    IntradaySignalEvent,
    intraday_bar_phase,
    required_entry_timeframe,
)


@dataclass(frozen=True)
class IntradayMomentumPolicy:
    """Frozen-candidate V1 thresholds; configurable before forward-test freeze."""

    opening_range_minutes: int = 6
    min_opening_relative_volume: float = 1.50
    min_standard_relative_volume: float = 1.20
    min_relative_strength_pct: float = 0.0
    max_opening_vwap_extension_pct: float = 0.010
    max_standard_vwap_extension_pct: float = 0.0075
    require_sector_context: bool = True
    require_standard_ema_alignment: bool = True
    block_scheduled_macro_window: bool = True
    block_earnings_event_risk: bool = True


@dataclass(frozen=True)
class IntradayMomentumObservation:
    observation_id: str
    timeframe: str
    observed_at: datetime
    close: float
    high: float
    low: float
    vwap: float
    relative_volume: float
    relative_strength_pct: float
    daily_context_approved: bool
    context_15m_approved: bool
    sector_context_approved: bool
    average_daily_share_volume: float
    opening_range_established: bool = False
    opening_range_high: float | None = None
    continuation_high: float | None = None
    ema9: float | None = None
    ema20: float | None = None
    scheduled_macro_blackout: bool = False
    earnings_event_risk: bool = False
    account_id: str = AGENTIC_INTRADAY_ACCOUNT
    symbol: str = AGENTIC_INTRADAY_PILOT_SYMBOL


@dataclass(frozen=True)
class MomentumSignalDecision:
    triggered: bool
    trigger_type: str | None
    reasons: tuple[str, ...]
    phase: IntradayPhase
    timeframe: str
    entry_price: float | None
    stock_stop_price: float | None
    vwap_extension_pct: float | None


def evaluate_mu_momentum_signal(
    observation: IntradayMomentumObservation,
    policy: IntradayMomentumPolicy | None = None,
) -> MomentumSignalDecision:
    """Evaluate the frozen-candidate MU opening/continuation signal deterministically."""
    rules = policy or IntradayMomentumPolicy()
    _validate_observation(observation)
    timeframe = observation.timeframe.upper()
    phase = intraday_bar_phase(observation.observed_at, timeframe)
    reasons: list[str] = []

    required = required_entry_timeframe(phase)
    if required is None:
        reasons.append(f"SIGNAL_NOT_ALLOWED_IN_{phase.value}")
    elif timeframe != required:
        reasons.append(f"SIGNAL_REQUIRES_{required}")

    if not observation.daily_context_approved:
        reasons.append("DAILY_CONTEXT_NOT_APPROVED")
    if not observation.context_15m_approved:
        reasons.append("CONTEXT_15M_NOT_APPROVED")
    if rules.require_sector_context and not observation.sector_context_approved:
        reasons.append("SECTOR_CONTEXT_NOT_APPROVED")
    if rules.block_scheduled_macro_window and observation.scheduled_macro_blackout:
        reasons.append("SCHEDULED_MACRO_BLACKOUT")
    if rules.block_earnings_event_risk and observation.earnings_event_risk:
        reasons.append("EARNINGS_EVENT_RISK_BLOCKED")

    extension = (observation.close - observation.vwap) / observation.vwap
    stop = _structural_stop(observation)
    if stop is None:
        reasons.append("STRUCTURAL_STOP_UNAVAILABLE")

    trigger_type: str | None = None
    if phase == IntradayPhase.OPENING_2M and timeframe == "2M":
        trigger_type = "OPENING_2M_ORB"
        _opening_checks(observation, rules, extension, reasons)
    elif phase == IntradayPhase.STANDARD_5M and timeframe == "5M":
        trigger_type = "STANDARD_5M_CONTINUATION"
        _standard_checks(observation, rules, extension, reasons)

    triggered = not reasons and trigger_type is not None and stop is not None
    return MomentumSignalDecision(
        triggered=triggered,
        trigger_type=trigger_type if triggered else None,
        reasons=tuple(dict.fromkeys(reasons)),
        phase=phase,
        timeframe=timeframe,
        entry_price=observation.close if triggered else None,
        stock_stop_price=stop if triggered else None,
        vwap_extension_pct=round(extension, 6),
    )


def build_intraday_entry_event(
    observation: IntradayMomentumObservation,
    decision: MomentumSignalDecision,
) -> IntradaySignalEvent:
    """Convert a triggered deterministic decision into the Stage-1 entry contract."""
    if not decision.triggered or decision.entry_price is None or decision.stock_stop_price is None:
        raise ValueError("INTRADAY_MOMENTUM_SIGNAL_NOT_TRIGGERED")
    return IntradaySignalEvent(
        event_id=observation.observation_id,
        action=IntradayAction.ENTRY_LONG,
        timeframe=decision.timeframe,
        price=decision.entry_price,
        observed_at=observation.observed_at,
        daily_context_approved=observation.daily_context_approved,
        context_15m_approved=observation.context_15m_approved,
        stock_stop_price=decision.stock_stop_price,
        average_daily_share_volume=observation.average_daily_share_volume,
        account_id=observation.account_id,
        symbol=observation.symbol,
        instrument="STOCK",
        trading_authorized=False,
        live_trading_enabled=False,
    )


def _opening_checks(
    observation: IntradayMomentumObservation,
    rules: IntradayMomentumPolicy,
    extension: float,
    reasons: list[str],
) -> None:
    if not observation.opening_range_established:
        reasons.append("OPENING_RANGE_NOT_ESTABLISHED")
    if observation.opening_range_high is None:
        reasons.append("OPENING_RANGE_HIGH_MISSING")
    elif observation.close <= observation.opening_range_high:
        reasons.append("OPENING_RANGE_BREAKOUT_NOT_CONFIRMED")
    if observation.close <= observation.vwap:
        reasons.append("PRICE_NOT_ABOVE_VWAP")
    if observation.relative_volume < rules.min_opening_relative_volume:
        reasons.append("OPENING_RELATIVE_VOLUME_TOO_LOW")
    if observation.relative_strength_pct <= rules.min_relative_strength_pct:
        reasons.append("RELATIVE_STRENGTH_NOT_POSITIVE")
    if extension > rules.max_opening_vwap_extension_pct:
        reasons.append("OPENING_VWAP_EXTENSION_TOO_HIGH")


def _standard_checks(
    observation: IntradayMomentumObservation,
    rules: IntradayMomentumPolicy,
    extension: float,
    reasons: list[str],
) -> None:
    if observation.continuation_high is None:
        reasons.append("CONTINUATION_HIGH_MISSING")
    elif observation.close <= observation.continuation_high:
        reasons.append("CONTINUATION_BREAKOUT_NOT_CONFIRMED")
    if observation.close <= observation.vwap:
        reasons.append("PRICE_NOT_ABOVE_VWAP")
    if observation.relative_volume < rules.min_standard_relative_volume:
        reasons.append("STANDARD_RELATIVE_VOLUME_TOO_LOW")
    if observation.relative_strength_pct <= rules.min_relative_strength_pct:
        reasons.append("RELATIVE_STRENGTH_NOT_POSITIVE")
    if rules.require_standard_ema_alignment:
        if observation.ema9 is None or observation.ema20 is None:
            reasons.append("STANDARD_EMA_CONTEXT_MISSING")
        elif observation.ema9 <= observation.ema20:
            reasons.append("STANDARD_EMA_TREND_NOT_ALIGNED")
    if extension > rules.max_standard_vwap_extension_pct:
        reasons.append("STANDARD_VWAP_EXTENSION_TOO_HIGH")


def _structural_stop(observation: IntradayMomentumObservation) -> float | None:
    candidate = max(observation.low, observation.vwap)
    if candidate <= 0 or candidate >= observation.close:
        return None
    return round(candidate, 6)


def _validate_observation(observation: IntradayMomentumObservation) -> None:
    if not observation.observation_id.strip():
        raise ValueError("INTRADAY_OBSERVATION_ID_REQUIRED")
    if observation.account_id != AGENTIC_INTRADAY_ACCOUNT:
        raise ValueError("INTRADAY_ACCOUNT_ID_INVALID")
    if observation.symbol.upper() != AGENTIC_INTRADAY_PILOT_SYMBOL:
        raise ValueError("INTRADAY_PILOT_SYMBOL_INVALID")
    if observation.observed_at.tzinfo is None:
        raise ValueError("INTRADAY_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    if observation.timeframe.upper() not in {"2M", "5M"}:
        raise ValueError("INTRADAY_MOMENTUM_TIMEFRAME_INVALID")
    numeric = (
        observation.close,
        observation.high,
        observation.low,
        observation.vwap,
        observation.relative_volume,
        observation.relative_strength_pct,
        observation.average_daily_share_volume,
    )
    if any(not math.isfinite(value) for value in numeric):
        raise ValueError("INTRADAY_MOMENTUM_NUMERIC_CONTEXT_INVALID")
    if min(observation.close, observation.high, observation.low, observation.vwap) <= 0:
        raise ValueError("INTRADAY_MOMENTUM_PRICE_CONTEXT_INVALID")
    if observation.high < observation.low:
        raise ValueError("INTRADAY_MOMENTUM_BAR_RANGE_INVALID")
    if not observation.low <= observation.close <= observation.high:
        raise ValueError("INTRADAY_MOMENTUM_CLOSE_OUTSIDE_BAR")
    if observation.relative_volume < 0 or observation.average_daily_share_volume < 0:
        raise ValueError("INTRADAY_MOMENTUM_VOLUME_CONTEXT_INVALID")
