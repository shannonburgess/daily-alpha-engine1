"""Research-only large-universe Daily Alpha v2.5 holdout study.

No broker calls, no Lambda execution, and no paper-ledger writes.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import median

from daily_alpha.backtest import fetch_orats_history, indicators

DEV_SYMBOLS = {
    "LRCX","MU","FTI","IRM","RCMT","HUBB","ALGN","HUM","MRK","PSX","VLO",
    "PLTR","SNDK","JNJ","HOOD","C",
}

# Broad liquid cross-sector holdout universe, intentionally excluding the 16 development names.
SYMBOLS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN",
    "AMAT","KLAC","CRM","NOW","ADBE","ORCL","IBM","CSCO","PANW","CRWD",
    "SNOW","INTC","MUFG","JPM","BAC","WFC","GS","MS","AXP","SCHW",
    "BLK","SPGI","CME","ICE","PNC","USB","COF","BK","TROW","UNH",
    "LLY","PFE","ABBV","TMO","DHR","ISRG","MDT","BMY","AMGN","GILD",
    "CVS","CI","ELV","BSX","ZTS","MCK","CAT","DE","GE","RTX",
    "BA","HON","ETN","PH","EMR","ITW","MMM","UPS","FDX","URI",
    "PWR","XOM","CVX","COP","EOG","SLB","OXY","MPC","KMI","WMB",
    "DVN","FANG","WMT","COST","HD","LOW","TGT","NKE","MCD","SBUX",
    "BKNG","MAR","ABNB","TSLA","GM","F","NFLX","DIS","T","NEE",
    "SO","DUK","AEP","EXC","SRE","AMT","PLD","EQIX","LIN","FCX",
    "NEM","NUE","SHW",
]
# De-duplicate defensively and enforce exclusion.
SYMBOLS = [s for i, s in enumerate(SYMBOLS) if s not in DEV_SYMBOLS and s not in SYMBOLS[:i]]

TRAIN_START = date(2024, 1, 1)
TRAIN_END = date(2025, 12, 31)
HOLDOUT_START = date(2026, 1, 1)
HOLDOUT_END = date(2026, 7, 31)
FETCH_START = date(2023, 1, 1)

VARIANTS = (
    "CURRENT_V24",
    "EARLY17_CURRENT_BE",
    "CURRENT25_ADAPTIVE",
    "V25_CANDIDATE",
)


def entry_adx_ok(rows, i: int, variant: str) -> bool:
    value = rows[i]["adx"]
    if value is None:
        return False
    value = float(value)
    if variant in {"CURRENT_V24", "CURRENT25_ADAPTIVE"}:
        return value >= 25.0
    if value < 17.0 or i <= 0 or rows[i - 1]["adx"] is None:
        return False
    return value > float(rows[i - 1]["adx"])


def runner_adx_min(variant: str) -> float:
    return 25.0 if variant in {"CURRENT_V24", "CURRENT25_ADAPTIVE"} else 17.0


def adaptive_runner_floor(*, row, prev_row, highest_close: float, base_atr: float, avg_cost: float) -> tuple[float, str]:
    adx = None if row["adx"] is None else float(row["adx"])
    prev_adx = None if prev_row is None or prev_row["adx"] is None else float(prev_row["adx"])
    eff = None if row["efficiency"] is None else float(row["efficiency"])
    bullish = int(row["trend_state"]) == 1
    if bullish and adx is not None and prev_adx is not None and eff is not None and adx >= 25.0 and adx > prev_adx and eff >= 0.35:
        return highest_close - 3.0 * base_atr, "ADAPTIVE_TRAIL_3ATR"
    if bullish and adx is not None and eff is not None and adx >= 20.0 and eff >= 0.25:
        return highest_close - 2.0 * base_atr, "ADAPTIVE_TRAIL_2ATR"
    return avg_cost, "ADAPTIVE_BREAK_EVEN"


def run_variant(bars, ind, *, start: date, end: date, variant: str) -> dict:
    qty = 0.0
    avg_cost = 0.0
    entry_breakout = None
    entry_bar = None
    base_entry = None
    base_atr = None
    add1_done = add2_done = harvest_done = False
    add1_bar = add2_bar = None
    current = None
    runner_floor = None
    runner_mode = None
    highest_close_after_harvest = None
    trades: list[dict] = []

    adaptive = variant in {"CURRENT25_ADAPTIVE", "V25_CANDIDATE"}

    for i, (bar, row) in enumerate(zip(bars, ind)):
        in_window = start <= bar.trade_date <= end
        flat = qty == 0
        price_ok = bar.close >= 25.0
        eff_ok = row["efficiency"] is not None and float(row["efficiency"]) >= 0.20
        rsi_ok = row["rsi"] is not None and float(row["rsi"]) <= 80.0
        adx_ok = entry_adx_ok(ind, i, variant)

        normal_setup = (
            in_window and flat and bool(row["fresh_breakout"])
            and not bool(row["is_earnings_up_gap"])
            and int(row["trend_state"]) == 1
            and bool(row["normal_trend_mature"])
        )
        normal_entry = normal_setup and price_ok and eff_ok and rsi_ok and adx_ok
        gap_entry = in_window and flat and bool(row["gap_go"]) and bool(row["fresh_breakout"]) and price_ok
        long_entry = normal_entry or gap_entry
        entry_type = "EARNINGS_GAP_GO" if gap_entry else "NORMAL_BREAKOUT" if normal_entry else "NONE"

        if long_entry:
            entry_breakout = float(row["upper20"])
            entry_bar = i
            base_entry = bar.close
            base_atr = float(row["atr"]) if row["atr"] is not None else None
            add1_done = add2_done = harvest_done = False
            add1_bar = add2_bar = None
            runner_floor = None
            runner_mode = None
            highest_close_after_harvest = None

        bars_since = i - entry_bar if entry_bar is not None else None
        failed_exit = (
            qty > 0 and entry_breakout is not None and bars_since is not None
            and 1 <= bars_since <= 3 and bar.close < entry_breakout
        )
        runner_trend_ok = (
            int(row["trend_state"]) == 1
            and row["adx"] is not None
            and float(row["adx"]) >= runner_adx_min(variant)
        )
        add1 = (
            qty > 0 and not add1_done and base_entry is not None and base_atr is not None
            and runner_trend_ok and bar.close >= base_entry + base_atr
        )
        if add1:
            add1_done = True
            add1_bar = i
        add2 = (
            qty > 0 and add1_done and not add2_done and add1_bar is not None and i > add1_bar
            and base_entry is not None and base_atr is not None and runner_trend_ok
            and bar.close >= base_entry + 2.0 * base_atr
        )
        if add2:
            add2_done = True
            add2_bar = i
        harvest = (
            qty > 0 and add2_done and not harvest_done and add2_bar is not None and i > add2_bar
            and base_entry is not None and base_atr is not None
            and bar.close >= base_entry + 3.0 * base_atr
        )
        if harvest:
            harvest_done = True
            highest_close_after_harvest = bar.close

        if harvest_done and highest_close_after_harvest is not None and base_atr is not None:
            highest_close_after_harvest = max(highest_close_after_harvest, bar.close)
            if adaptive:
                candidate_floor, candidate_mode = adaptive_runner_floor(
                    row=row,
                    prev_row=ind[i - 1] if i > 0 else None,
                    highest_close=highest_close_after_harvest,
                    base_atr=base_atr,
                    avg_cost=avg_cost,
                )
            else:
                candidate_floor, candidate_mode = avg_cost, "BREAK_EVEN"
            if runner_floor is None or candidate_floor > runner_floor:
                runner_floor = candidate_floor
                runner_mode = candidate_mode

        floor_exit = qty > 0 and harvest_done and runner_floor is not None and bar.close <= runner_floor
        turtle_exit = qty > 0 and row["lower10"] is not None and bar.close < float(row["lower10"])
        trend_exit = qty > 0 and bool(row["bear_flip"])
        long_exit = in_window and (floor_exit or failed_exit or turtle_exit or trend_exit)
        if floor_exit:
            exit_reason = runner_mode or "RUNNER_FLOOR"
        elif failed_exit:
            exit_reason = "FAILED_BREAKOUT"
        elif turtle_exit:
            exit_reason = "TURTLE_10"
        elif trend_exit:
            exit_reason = "TREND_FLIP"
        else:
            exit_reason = ""

        if long_entry:
            qty = 2.0
            avg_cost = bar.close
            current = {
                "entry_date": bar.trade_date.isoformat(),
                "entry_price": bar.close,
                "entry_type": entry_type,
                "entry_adx": row["adx"],
                "entry_efficiency": row["efficiency"],
                "gross_cost": 2.0 * bar.close,
                "realized_pnl": 0.0,
                "adds": 0,
                "harvested": False,
            }

        if add1 and current is not None:
            new_qty = qty + 1.0
            avg_cost = (avg_cost * qty + bar.close) / new_qty
            qty = new_qty
            current["gross_cost"] += bar.close
            current["adds"] += 1
        if add2 and current is not None:
            new_qty = qty + 1.0
            avg_cost = (avg_cost * qty + bar.close) / new_qty
            qty = new_qty
            current["gross_cost"] += bar.close
            current["adds"] += 1
        if harvest and current is not None and qty >= 1.0:
            current["realized_pnl"] += bar.close - avg_cost
            qty -= 1.0
            current["harvested"] = True
            current["harvest_date"] = bar.trade_date.isoformat()
            current["harvest_price"] = bar.close

        if long_exit and current is not None and qty > 0:
            current["realized_pnl"] += (bar.close - avg_cost) * qty
            current["exit_date"] = bar.trade_date.isoformat()
            current["exit_price"] = bar.close
            current["exit_reason"] = exit_reason
            current["return_pct"] = current["realized_pnl"] / current["gross_cost"] * 100.0
            trades.append(current)
            qty = 0.0
            avg_cost = 0.0
            entry_breakout = entry_bar = base_entry = base_atr = None
            add1_done = add2_done = harvest_done = False
            add1_bar = add2_bar = None
            current = None
            runner_floor = runner_mode = highest_close_after_harvest = None

    if current is not None and qty > 0:
        eligible = [b for b in bars if b.trade_date <= end]
        if eligible:
            last = max(eligible, key=lambda b: b.trade_date)
            current["realized_pnl"] += (last.close - avg_cost) * qty
            current["exit_date"] = last.trade_date.isoformat()
            current["exit_price"] = last.close
            current["exit_reason"] = "MARK_TO_END"
            current["return_pct"] = current["realized_pnl"] / current["gross_cost"] * 100.0
            trades.append(current)

    gross = sum(float(t["gross_cost"]) for t in trades)
    pnl = sum(float(t["realized_pnl"]) for t in trades)
    compounded = 1.0
    for t in trades:
        compounded *= 1.0 + float(t["return_pct"]) / 100.0
    return {
        "variant": variant,
        "trade_count": len(trades),
        "wins": sum(1 for t in trades if float(t["realized_pnl"]) > 0),
        "aggregate_return_pct_on_gross": pnl / gross * 100.0 if gross else 0.0,
        "compounded_trade_return_pct": (compounded - 1.0) * 100.0 if trades else 0.0,
        "total_pnl_units": pnl,
        "gross_deployed_units": gross,
        "trades": trades,
    }


def summarize(records: dict[str, dict], period_key: str, variant: str) -> dict:
    valid = [r for r in records.values() if "data_error" not in r]
    stats = [r[period_key][variant] for r in valid]
    trades = [t for s in stats for t in s["trades"]]
    returns = [s["aggregate_return_pct_on_gross"] for s in stats]
    comp = [s["compounded_trade_return_pct"] for s in stats]
    gains = sum(max(float(t["realized_pnl"]), 0.0) for t in trades)
    losses = -sum(min(float(t["realized_pnl"]), 0.0) for t in trades)
    return {
        "symbols": len(valid),
        "symbols_with_trades": sum(1 for s in stats if s["trade_count"] > 0),
        "positive_symbols": sum(1 for s in stats if s["aggregate_return_pct_on_gross"] > 0),
        "trades": len(trades),
        "wins": sum(1 for t in trades if float(t["realized_pnl"]) > 0),
        "win_rate_pct": (sum(1 for t in trades if float(t["realized_pnl"]) > 0) / len(trades) * 100.0) if trades else 0.0,
        "mean_symbol_return_pct": sum(returns) / len(returns) if returns else 0.0,
        "median_symbol_return_pct": median(returns) if returns else 0.0,
        "mean_symbol_compounded_pct": sum(comp) / len(comp) if comp else 0.0,
        "profit_factor": gains / losses if losses > 0 else None,
        "best_trade_return_pct": max((float(t["return_pct"]) for t in trades), default=0.0),
        "worst_trade_return_pct": min((float(t["return_pct"]) for t in trades), default=0.0),
    }


def fetch_one(symbol: str, token: str):
    bars, meta = fetch_orats_history(symbol, start=FETCH_START, end=HOLDOUT_END, token=token)
    return symbol, bars, meta, indicators(bars)


def main() -> None:
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN missing")

    records: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_one, s, token): s for s in SYMBOLS}
        for future in as_completed(futures):
            symbol = futures[future]
            rec = {"symbol": symbol}
            try:
                _, bars, meta, ind = future.result()
                rec["source"] = meta[0].get("source") if meta else "ORATS"
                rec["train"] = {}
                rec["holdout"] = {}
                train_bars = [b for b in bars if TRAIN_START <= b.trade_date <= TRAIN_END]
                holdout_bars = [b for b in bars if HOLDOUT_START <= b.trade_date <= HOLDOUT_END]
                rec["train_buy_hold_pct"] = (train_bars[-1].close / train_bars[0].close - 1.0) * 100.0 if len(train_bars) >= 2 else None
                rec["holdout_buy_hold_pct"] = (holdout_bars[-1].close / holdout_bars[0].close - 1.0) * 100.0 if len(holdout_bars) >= 2 else None
                for variant in VARIANTS:
                    rec["train"][variant] = run_variant(bars, ind, start=TRAIN_START, end=TRAIN_END, variant=variant)
                    rec["holdout"][variant] = run_variant(bars, ind, start=HOLDOUT_START, end=HOLDOUT_END, variant=variant)
            except Exception as exc:
                rec["data_error"] = f"{type(exc).__name__}:{exc}"
            records[symbol] = rec

    valid = [r for r in records.values() if "data_error" not in r]
    output = {
        "schema": "daily-alpha-v25-large-holdout-v1",
        "development_symbols_excluded": sorted(DEV_SYMBOLS),
        "requested_universe_size": len(SYMBOLS),
        "valid_symbols": len(valid),
        "data_errors": {s: r["data_error"] for s, r in records.items() if "data_error" in r},
        "periods": {
            "train": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
            "holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
        },
        "candidate_rule": {
            "entry": "ADX>=17 AND ADX rising + existing v2.4 fresh-breakout/trend-mature/efficiency/RSI gates; earnings GapGo unchanged",
            "runner": "after +3ATR harvest: 3ATR trail if bullish+ADX>=25+rising+efficiency>=0.35; else 2ATR trail if bullish+ADX>=20+efficiency>=0.25; else average-cost break-even; floor only tightens",
        },
        "summaries": {
            period: {v: summarize(records, period, v) for v in VARIANTS}
            for period in ("train", "holdout")
        },
        "symbols": records,
    }

    Path("v25-large-holdout.json").write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

    hs = output["summaries"]["holdout"]
    ts = output["summaries"]["train"]
    lines = [
        "# Daily Alpha v2.5 Large-Universe Holdout",
        "",
        f"Requested symbols: {len(SYMBOLS)}; valid: {len(valid)}; data errors: {len(output['data_errors'])}",
        "Development names excluded: " + ", ".join(sorted(DEV_SYMBOLS)),
        "",
        "## Aggregate comparison",
        "",
        "| Period | Variant | Mean symbol return | Median | Trades | Win rate | Profit factor | Positive symbols |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for period, stats in (("TRAIN 2024-25", ts), ("HOLDOUT 2026", hs)):
        for v in VARIANTS:
            s = stats[v]
            pf = "∞" if s["profit_factor"] is None and s["trades"] else f"{s['profit_factor']:.2f}" if s["profit_factor"] is not None else "n/a"
            lines.append(
                f"| {period} | {v} | {s['mean_symbol_return_pct']:.2f}% | {s['median_symbol_return_pct']:.2f}% | "
                f"{s['trades']} | {s['win_rate_pct']:.1f}% | {pf} | {s['positive_symbols']}/{s['symbols']} |"
            )

    lines += ["", "## Holdout per-symbol comparison", "", "| Symbol | Buy/Hold | Current v2.4 | Early17+BE | ADX25+Adaptive | v2.5 Candidate | Candidate vs current |", "|---|---:|---:|---:|---:|---:|---:|"]
    for symbol in sorted(records):
        r = records[symbol]
        if "data_error" in r:
            lines.append(f"| {symbol} | DATA_ERROR | | | | | |")
            continue
        h = r["holdout"]
        cur = h["CURRENT_V24"]["aggregate_return_pct_on_gross"]
        early = h["EARLY17_CURRENT_BE"]["aggregate_return_pct_on_gross"]
        adapt25 = h["CURRENT25_ADAPTIVE"]["aggregate_return_pct_on_gross"]
        cand = h["V25_CANDIDATE"]["aggregate_return_pct_on_gross"]
        bh = r["holdout_buy_hold_pct"]
        lines.append(f"| {symbol} | {bh:.2f}% | {cur:.2f}% | {early:.2f}% | {adapt25:.2f}% | {cand:.2f}% | {cand-cur:+.2f}pp |")

    Path("v25-large-holdout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:20]))
    print("\nHOLDOUT DELTAS:")
    for v in VARIANTS:
        print(v, json.dumps(hs[v], sort_keys=True))
    print("DATA_ERRORS", json.dumps(output["data_errors"], sort_keys=True))


if __name__ == "__main__":
    main()
