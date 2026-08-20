"""Controlled ACTIVE_BUY continuation entry overlay for the server PAPER scanner.

The SH24/SH25 TradingView strategies remain unchanged for prospective champion/
challenger evidence.  This module addresses a separate Daily Alpha portfolio need:
a persistent OVTLYR BUY may still be a valid controlled entry after its first Turtle
breakout bar has passed.

Continuation entries are deliberately conservative.  They require a recent confirmed
20-day breakout, intact trend/quality evidence, the broader $10 Daily Alpha price
floor, and an explicit +1 ATR no-chase ceiling.  They reuse the existing scanner ->
next-session -> fresh ORATS/liquidity/portfolio-risk -> PAPER execution chain and can
never authorize live trading.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from .backtest import Bar, indicators
from .execution_universe import (
    CANONICAL_STRATEGY,
    CANONICAL_TIMEFRAME,
    CANONICAL_VERSION,
    SCANNER_SOURCE,
    ScannerDecision,
    ScannerState,
)

CONTINUATION_ENTRY_VARIANT = "ACTIVE_BUY_CONTINUATION"
CONTINUATION_EXECUTION_ENTRY_TYPE = "NORMAL_BREAKOUT"
CONTINUATION_LIFECYCLE = "ENTRY_WATCH"
DAILY_ALPHA_MIN_PRICE = 10.0
RECENT_BREAKOUT_MAX_AGE_BARS = 10
MAX_CHASE_ATR = 1.0
MIN_TREND_EFFICIENCY = 0.20
MAX_ENTRY_RSI = 80.0
MIN_ADX = 25.0


def evaluate_active_buy_continuation(
    symbol: str,
    bars: list[Bar],
    *,
    ovtlyr_status: str,
    state: ScannerState | None,
    now: datetime,
    require_trade_date: date | None = None,
    max_breakout_age_bars: int = RECENT_BREAKOUT_MAX_AGE_BARS,
) -> ScannerDecision:
    """Evaluate one persistent ACTIVE_BUY for a bounded continuation entry.

    The execution contract continues to use the canonical ``NORMAL_BREAKOUT`` entry
    type so it traverses the existing validated scanner boundary.  ``entry_variant``
    and the continuation provenance fields make the distinct decision rule explicit
    in durable evidence.
    """
    if max_breakout_age_bars < 0:
        raise ValueError("Continuation breakout age must be non-negative")
    if len(bars) < 80:
        raise ValueError(f"Insufficient bars for {symbol}: {len(bars)}")

    reference = _aware(now)
    rows = indicators(bars)
    if len(rows) != len(bars):
        raise ValueError("Continuation indicator/bar length mismatch")

    bar = bars[-1]
    row = rows[-1]
    market_date = bar.trade_date
    metrics = _metrics(bar, row)

    if require_trade_date is not None and market_date != require_trade_date:
        return _wait(
            symbol,
            market_date,
            "NO_CURRENT_CONFIRMED_DAILY_BAR",
            state,
            metrics,
        )
    if state is not None:
        return _wait(
            symbol,
            market_date,
            "OPEN_POSITION_CONTINUATION_ENTRY_NOT_ALLOWED",
            state,
            metrics,
        )
    if str(ovtlyr_status or "").strip().upper() != "ACTIVE_BUY":
        return _wait(
            symbol,
            market_date,
            "CONTINUATION_REQUIRES_ACTIVE_BUY",
            None,
            metrics,
        )
    if bar.close < DAILY_ALPHA_MIN_PRICE:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_PRICE_BELOW_10",
            None,
            metrics,
        )
    if bool(row.get("is_earnings_up_gap")):
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_EARNINGS_EVENT_BAR",
            None,
            metrics,
        )

    breakout = _recent_breakout(
        bars,
        rows,
        max_age_bars=max_breakout_age_bars,
    )
    if breakout is None:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_NO_RECENT_20D_BREAKOUT",
            None,
            metrics,
        )

    breakout_index, breakout_level, breakout_atr = breakout
    breakout_age = len(bars) - 1 - breakout_index
    replay_max_price = breakout_level + MAX_CHASE_ATR * breakout_atr
    metrics.update(
        {
            "continuation_breakout_date": bars[breakout_index].trade_date.isoformat(),
            "continuation_breakout_age_bars": breakout_age,
            "continuation_breakout_level": breakout_level,
            "continuation_breakout_atr": breakout_atr,
            "continuation_replay_max_price": replay_max_price,
        }
    )

    if bar.close <= breakout_level:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_BREAKOUT_NO_LONGER_HELD",
            None,
            metrics,
        )
    if bar.close > replay_max_price:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_EXTENDED_ABOVE_1ATR",
            None,
            metrics,
        )
    if int(row.get("trend_state") or 0) != 1:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_TREND_NOT_BULLISH",
            None,
            metrics,
        )
    if not bool(row.get("normal_trend_mature")):
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_TREND_NOT_MATURE",
            None,
            metrics,
        )

    efficiency = _optional_float(row.get("efficiency"))
    if efficiency is None or efficiency < MIN_TREND_EFFICIENCY:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_LOW_TREND_EFFICIENCY",
            None,
            metrics,
        )
    rsi = _optional_float(row.get("rsi"))
    if rsi is None or rsi > MAX_ENTRY_RSI:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_RSI_EXTENDED",
            None,
            metrics,
        )
    adx = _optional_float(row.get("adx"))
    if adx is None or adx < MIN_ADX:
        return _wait(
            symbol,
            market_date,
            "WAIT_ACTIVE_BUY_ADX_BELOW_25",
            None,
            metrics,
        )

    current_atr = _optional_float(row.get("atr"))
    lower10 = _optional_float(row.get("lower10"))
    if (
        current_atr is None
        or current_atr <= 0
        or lower10 is None
        or lower10 <= 0
        or lower10 >= bar.close
    ):
        return _wait(
            symbol,
            market_date,
            "ACTIVE_BUY_CONTINUATION_CONTEXT_INCOMPLETE",
            None,
            metrics,
        )

    average_daily_dollar_volume = _average_dollar_volume(bars)
    signal = {
        "source": SCANNER_SOURCE,
        "signal_id": (
            f"DA-SCAN-{symbol.upper()}-{market_date.isoformat()}-"
            f"{CONTINUATION_ENTRY_VARIANT}"
        ),
        "symbol": symbol.upper(),
        "action": "ENTRY_LONG",
        "strategy": CANONICAL_STRATEGY,
        "strategy_version": CANONICAL_VERSION,
        "timeframe": CANONICAL_TIMEFRAME,
        "price": float(bar.close),
        "bar_time": reference.isoformat(),
        # Reuse the validated scanner entry contract while retaining explicit
        # continuation provenance for audit/forensics.
        "entry_type": CONTINUATION_EXECUTION_ENTRY_TYPE,
        "entry_variant": CONTINUATION_ENTRY_VARIANT,
        "source_lifecycle": "ACTIVE_BUY",
        # Treat a continuation as a half-size starter rather than a full confirmed
        # leader allocation. The downstream lifecycle engine maps ENTRY_WATCH to 50%.
        "lifecycle": CONTINUATION_LIFECYCLE,
        "continuation_breakout_date": bars[breakout_index].trade_date.isoformat(),
        "continuation_breakout_age_bars": breakout_age,
        "continuation_breakout_level": breakout_level,
        "continuation_breakout_atr": breakout_atr,
        "replay_max_price": replay_max_price,
        "stock_stop_price": lower10,
        "average_daily_dollar_volume": average_daily_dollar_volume,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    proposed_state = ScannerState(
        symbol=symbol.upper(),
        entry_date=market_date.isoformat(),
        runner_base_entry=float(bar.close),
        runner_base_atr=current_atr,
        entry_breakout_level=breakout_level,
        last_signal_id=signal["signal_id"],
    )
    return ScannerDecision(
        symbol=symbol.upper(),
        market_bar_date=market_date.isoformat(),
        action="ENTRY_LONG",
        reason=CONTINUATION_ENTRY_VARIANT,
        signal=signal,
        proposed_state=proposed_state,
        metrics=metrics,
    )


def _recent_breakout(
    bars: list[Bar],
    rows: list[dict[str, Any]],
    *,
    max_age_bars: int,
) -> tuple[int, float, float] | None:
    first = max(0, len(rows) - 1 - max_age_bars)
    for index in range(len(rows) - 1, first - 1, -1):
        row = rows[index]
        if not bool(row.get("fresh_breakout")):
            continue
        level = _optional_float(row.get("upper20"))
        atr = _optional_float(row.get("atr"))
        if level is None or level <= 0 or atr is None or atr <= 0:
            continue
        if bars[index].close <= level:
            continue
        return index, level, atr
    return None


def _wait(
    symbol: str,
    market_date: date,
    reason: str,
    state: ScannerState | None,
    metrics: dict[str, Any],
) -> ScannerDecision:
    return ScannerDecision(
        symbol=symbol.upper(),
        market_bar_date=market_date.isoformat(),
        action=None,
        reason=reason,
        signal=None,
        proposed_state=state,
        metrics=metrics,
    )


def _metrics(bar: Bar, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "close": bar.close,
        "atr": row.get("atr"),
        "rsi": row.get("rsi"),
        "adx": row.get("adx"),
        "efficiency": row.get("efficiency"),
        "upper20": row.get("upper20"),
        "lower10": row.get("lower10"),
        "trend_state": row.get("trend_state"),
        "fresh_breakout": row.get("fresh_breakout"),
        "continuation_variant": CONTINUATION_ENTRY_VARIANT,
        "daily_alpha_min_price": DAILY_ALPHA_MIN_PRICE,
        "max_chase_atr": MAX_CHASE_ATR,
    }


def _average_dollar_volume(bars: list[Bar]) -> float:
    window = bars[-20:]
    if len(window) < 20:
        return 0.0
    return sum(bar.close * bar.volume for bar in window) / len(window)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
