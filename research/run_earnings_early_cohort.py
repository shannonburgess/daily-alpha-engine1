"""Empirical underlying-only study for EARNINGS_GAP_GO_EARLY events.

This research runner intentionally does not authorize entries. It measures whether
the canonical 60%-<70% close-location earnings cohort has stable forward behavior
before historical option implementation is considered.

The study uses only ORATS daily OHLCV/earnings data known by each event date and
reports fixed-horizon outcomes, MAE/MFE, confirmation frequencies, and the existing
25% starter / 25%->50% confirmation scenario helper at a T+20 research horizon.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any

from daily_alpha.backtest import fetch_orats_history, indicators
from daily_alpha.earnings_early_research import (
    EarlyConfirmationRule,
    EarlyEventPath,
    compare_early_entry_paths,
)

SYMBOLS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN",
    "AMAT","KLAC","CRM","NOW","ORCL","IBM","CSCO","PANW","JPM","BAC","WFC",
    "GS","MS","AXP","SCHW","UNH","LLY","ABBV","TMO","DHR","ISRG","AMGN",
    "CAT","DE","GE","RTX","HON","ETN","EMR","PWR","XOM","CVX","COP","EOG",
    "SLB","MPC","WMT","COST","HD","LOW","MCD","BKNG","TSLA","NFLX","NEE",
    "AMT","PLD","EQIX","LIN","FCX",
]
START = date(2021, 1, 1)
END = date(2026, 7, 31)
EVENT_START = date(2022, 1, 1)
HORIZONS = (5, 10, 20, 40)


def pct(a: float, b: float) -> float:
    return (b / a - 1.0) * 100.0 if a > 0 else 0.0


def collect_symbol(symbol: str, token: str) -> list[dict[str, Any]]:
    bars, _ = fetch_orats_history(symbol, start=START, end=END, token=token)
    rows = indicators(bars)
    events: list[dict[str, Any]] = []
    max_h = max(HORIZONS)

    for i, (bar, row) in enumerate(zip(bars, rows)):
        if bar.trade_date < EVENT_START or not bool(row.get("gap_go_early")):
            continue
        if i + max_h >= len(bars):
            continue

        event: dict[str, Any] = {
            "symbol": symbol,
            "date": bar.trade_date.isoformat(),
            "event_close": bar.close,
            "event_high": bar.high,
            "close_location": round(float(row.get("close_location") or 0.0), 6),
            "relative_volume": round(float(row.get("relative_volume") or 0.0), 4),
            "rsi": round(float(row.get("rsi") or 0.0), 4),
        }
        for horizon in HORIZONS:
            event[f"return_{horizon}d_pct"] = round(pct(bar.close, bars[i + horizon].close), 4)

        path20 = bars[i + 1 : i + 21]
        event["mae_20d_pct"] = round(
            min(pct(bar.close, future.low) for future in path20), 4
        )
        event["mfe_20d_pct"] = round(
            max(pct(bar.close, future.high) for future in path20), 4
        )

        forward_closes = tuple(b.close for b in bars[i + 1 : i + 3])
        research_path = EarlyEventPath(
            event_close=bar.close,
            event_high=bar.high,
            forward_closes=forward_closes,
            exit_price=bars[i + 20].close,
        )
        for max_days in (1, 2):
            for rule in (
                EarlyConfirmationRule.CLOSE_ABOVE_EVENT_HIGH,
                EarlyConfirmationRule.CLOSE_ABOVE_EVENT_CLOSE,
            ):
                results = compare_early_entry_paths(
                    research_path,
                    confirmation_rule=rule,
                    max_confirmation_days=max_days,
                )
                prefix = f"{rule.value}_{max_days}D"
                confirm = results[-1]
                event[f"{prefix}_confirmed"] = confirm.confirmation_day is not None
                event[f"{prefix}_starter_then_confirm_pct"] = confirm.normalized_return_pct
        events.append(event)
    return events


def describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    losses = [x for x in values if x < 0]
    return {
        "n": len(values),
        "mean": round(mean(values), 4),
        "median": round(median(values), 4),
        "win_rate_pct": round(sum(x > 0 for x in values) / len(values) * 100.0, 2),
        "p10": round(ordered[max(0, math.floor(0.10 * (len(ordered) - 1)))], 4),
        "p90": round(ordered[min(len(ordered) - 1, math.floor(0.90 * (len(ordered) - 1)))], 4),
        "avg_loss": round(mean(losses), 4) if losses else None,
    }


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(events), "horizons": {}, "confirmation": {}}
    for horizon in HORIZONS:
        key = f"return_{horizon}d_pct"
        out["horizons"][f"{horizon}d"] = describe([float(e[key]) for e in events])
    out["mae_20d"] = describe([float(e["mae_20d_pct"]) for e in events])
    out["mfe_20d"] = describe([float(e["mfe_20d_pct"]) for e in events])

    for max_days in (1, 2):
        for rule in (
            EarlyConfirmationRule.CLOSE_ABOVE_EVENT_HIGH,
            EarlyConfirmationRule.CLOSE_ABOVE_EVENT_CLOSE,
        ):
            prefix = f"{rule.value}_{max_days}D"
            confirmed = [bool(e[f"{prefix}_confirmed"]) for e in events]
            returns = [float(e[f"{prefix}_starter_then_confirm_pct"]) for e in events]
            out["confirmation"][prefix] = {
                "confirmed_n": sum(confirmed),
                "confirmed_rate_pct": round(sum(confirmed) / len(events) * 100.0, 2)
                if events
                else 0.0,
                "normalized_t20_return": describe(returns),
            }
    return out


def exclusion_views(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {}
    best20 = max(events, key=lambda e: float(e["return_20d_pct"]))
    without_best = [e for e in events if e is not best20]
    without_mrvl = [e for e in events if e["symbol"] != "MRVL"]
    return {
        "all": summarize(events),
        "without_best_20d_event": {
            "excluded": {"symbol": best20["symbol"], "date": best20["date"], "return_20d_pct": best20["return_20d_pct"]},
            "summary": summarize(without_best),
        },
        "without_mrvl": summarize(without_mrvl),
        "mrvl_only": summarize([e for e in events if e["symbol"] == "MRVL"]),
    }


def main() -> None:
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")

    events: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect_symbol, symbol, token): symbol for symbol in SYMBOLS}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                events.extend(future.result())
            except Exception as exc:  # research runner preserves complete failure evidence
                failures[symbol] = f"{type(exc).__name__}: {exc}"

    events.sort(key=lambda e: (e["date"], e["symbol"]))
    payload = {
        "methodology": {
            "classification": "canonical EARNINGS_GAP_GO_EARLY 60%-<70% close-location band",
            "event_window": [EVENT_START.isoformat(), END.isoformat()],
            "horizons": list(HORIZONS),
            "implementation": "UNDERLYING_ONLY_FIXED_HORIZON_SCREEN",
            "paper_live_authorized": False,
            "options_deferred": "requires historical executable quote reliability",
        },
        "symbols_requested": len(SYMBOLS),
        "failures": failures,
        "views": exclusion_views(events),
        "events": events,
    }
    Path("earnings-early-cohort.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: v for k, v in payload.items() if k != "events"}, indent=2))


if __name__ == "__main__":
    main()
