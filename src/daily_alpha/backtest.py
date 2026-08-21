"""Vendor-independent Daily Alpha historical strategy research helpers.

This module contains deterministic strategy math only. Historical bars must be
supplied by the caller; no external market-data or options-data API is contacted.
Research only. No trade routing or live authorization.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

CANONICAL_GAP_GO_CLOSE_LOCATION = 0.70
EARLY_GAP_GO_CLOSE_LOCATION = 0.60


@dataclass
class Bar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    earnings_event: bool = False


@dataclass
class Trade:
    version: str
    entry_type: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    units_bought: float
    realized_pnl: float
    gross_entry_cost: float
    return_pct: float
    r_multiple: float | None
    exit_reason: str
    adds: int
    harvested: bool


def gap_go_close_location_band(close_location: float) -> str:
    """Classify the canonical v2.4 close-location band."""
    if close_location >= CANONICAL_GAP_GO_CLOSE_LOCATION:
        return "FULL"
    if close_location >= EARLY_GAP_GO_CLOSE_LOCATION:
        return "EARLY"
    return "BELOW"


def indicators(bars: list[Bar]) -> list[dict[str, Any]]:
    """Return minimal deterministic point-in-time rows for supplied bars.

    Full historical studies may enrich these rows before calling ``run_strategy``.
    Keeping the base implementation source-neutral ensures research never depends
    on a retired provider.
    """
    rows: list[dict[str, Any]] = []
    for index, bar in enumerate(bars):
        prior = bars[index - 1] if index > 0 else None
        prior_close = prior.close if prior else bar.open
        gap_dollars = bar.open - prior_close
        day_range = bar.high - bar.low
        close_location = (bar.close - bar.low) / day_range if day_range > 0 else 0.0
        gap_retention = (
            (bar.close - prior_close) / gap_dollars if gap_dollars > 0 else 0.0
        )
        rows.append(
            {
                "upper20": None,
                "lower10": None,
                "fresh_breakout": False,
                "trend_state": 0,
                "bear_flip": False,
                "normal_trend_mature": False,
                "earnings_window": bar.earnings_event,
                "gap_dollars": gap_dollars,
                "gap_pct": (gap_dollars / prior_close * 100.0) if prior_close > 0 else 0.0,
                "gap_atr": 0.0,
                "close_location": close_location,
                "gap_retention": gap_retention,
                "relative_volume": 0.0,
                "is_earnings_up_gap": bool(bar.earnings_event and gap_dollars > 0),
                "gap_go": False,
                "gap_go_early": False,
                "gap_crap": False,
                "gap_wait": bool(bar.earnings_event and gap_dollars > 0),
                "atr": None,
                "rsi": None,
                "adx": None,
                "efficiency": None,
            }
        )
    return rows


def run_strategy(
    bars: list[Bar],
    rows: list[dict[str, Any]],
    *,
    version: str,
    start: date,
    end: date,
) -> tuple[list[Trade], list[dict[str, Any]]]:
    """Run a bounded deterministic research simulation over supplied rows.

    The implementation intentionally preserves the v2.4 earnings classification
    contract used by regression tests. EARLY Gap & Go is watch-only; FULL Gap & Go
    can create a research trade. Normal-breakout rows can also create a simple
    same-bar research trade when their explicit gates are already supplied as true.
    """
    if len(bars) != len(rows):
        raise ValueError("bars and rows must have the same length")
    trades: list[Trade] = []
    events: list[dict[str, Any]] = []

    for bar, row in zip(bars, rows, strict=True):
        if bar.trade_date < start or bar.trade_date > end:
            continue
        gap_go = row.get("gap_go") is True
        gap_go_early = row.get("gap_go_early") is True
        gap_crap = row.get("gap_crap") is True
        gap_wait = row.get("gap_wait") is True
        if gap_go:
            classification = "EARNINGS_GAP_GO"
        elif gap_go_early:
            classification = "EARNINGS_GAP_GO_EARLY"
        elif gap_crap:
            classification = "EARNINGS_GAP_CRAP"
        elif gap_wait:
            classification = "EARNINGS_WAIT"
        else:
            classification = "NONE"

        full_gap_entry = bool(version == "2.4" and gap_go)
        normal_entry = bool(
            row.get("fresh_breakout") is True
            and not row.get("is_earnings_up_gap")
            and int(row.get("trend_state") or 0) == 1
            and row.get("normal_trend_mature") is True
        )
        v24_entry = full_gap_entry or normal_entry
        events.append(
            {
                "date": bar.trade_date.isoformat(),
                "classification": classification,
                "v24_entry": v24_entry,
                "research_only": True,
                "trading_authorized": False,
                "live_trading_enabled": False,
            }
        )
        if not v24_entry:
            continue

        entry_type = "EARNINGS_GAP_GO" if full_gap_entry else "NORMAL_BREAKOUT"
        entry_price = bar.close
        exit_price = bar.close
        trades.append(
            Trade(
                version=version,
                entry_type=entry_type,
                entry_date=bar.trade_date.isoformat(),
                exit_date=bar.trade_date.isoformat(),
                entry_price=entry_price,
                exit_price=exit_price,
                units_bought=1.0,
                realized_pnl=0.0,
                gross_entry_cost=entry_price,
                return_pct=0.0,
                r_multiple=0.0,
                exit_reason="SAME_BAR_RESEARCH_PLACEHOLDER",
                adds=0,
                harvested=False,
            )
        )
    return trades, events


def summarize(trades: list[Trade]) -> dict[str, Any]:
    finite_r = [
        float(trade.r_multiple)
        for trade in trades
        if trade.r_multiple is not None and math.isfinite(float(trade.r_multiple))
    ]
    return {
        "trades": len(trades),
        "wins": sum(trade.realized_pnl > 0 for trade in trades),
        "total_r": round(sum(finite_r), 4),
        "gap_go_trades": sum(trade.entry_type == "EARNINGS_GAP_GO" for trade in trades),
        "normal_breakout_trades": sum(
            trade.entry_type == "NORMAL_BREAKOUT" for trade in trades
        ),
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def trades_to_dicts(trades: list[Trade]) -> list[dict[str, Any]]:
    return [asdict(trade) for trade in trades]
