"""Research-only v2.5 runner persistence study.

Entry is frozen at ADX >=17 and rising with existing v2.4 gates.
No broker/Lambda/paper-ledger writes.
"""
from __future__ import annotations

import json
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import median

from daily_alpha.backtest import fetch_orats_history, indicators

DEV_SYMBOLS = {
    "LRCX","MU","FTI","IRM","RCMT","HUBB","ALGN","HUM","MRK","PSX","VLO",
    "PLTR","SNDK","JNJ","HOOD","C",
}
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
SYMBOLS = [s for i, s in enumerate(SYMBOLS) if s not in DEV_SYMBOLS and s not in SYMBOLS[:i]]

SELECT_START = date(2022, 1, 1)
SELECT_END = date(2022, 12, 31)
HOLDOUT_START = date(2023, 1, 1)
HOLDOUT_END = date(2023, 12, 31)
FETCH_START = date(2021, 1, 1)

RUNNERS = (
    "BENCHMARK_BE",
    "STRONG_BE_MINUS_1ATR",
    "STRONG_BE_MINUS_2ATR",
    "STRONG_TRAIL4_CAPPED_BE",
    "STRONG_GRACE3",
    "STRONG_UNTIL_WEAK",
)


def entry_adx_ok(rows, i: int) -> bool:
    value = rows[i]["adx"]
    if value is None or i <= 0 or rows[i - 1]["adx"] is None:
        return False
    value = float(value)
    return value >= 17.0 and value > float(rows[i - 1]["adx"])


def strong_persistence(row, prev_row) -> bool:
    if int(row["trend_state"]) != 1 or row["adx"] is None or row["efficiency"] is None:
        return False
    adx = float(row["adx"])
    eff = float(row["efficiency"])
    if adx < 20.0 or eff < 0.25:
        return False
    if prev_row is None or prev_row["adx"] is None:
        return False
    # Constructive means not rolling over materially; allow a tiny one-day wiggle.
    return adx >= float(prev_row["adx"]) - 0.75


def runner_floor_for(
    mode: str,
    *,
    row,
    prev_row,
    avg_cost: float,
    base_atr: float,
    highest_close: float,
    bars_after_harvest: int,
) -> tuple[float | None, str]:
    strong = strong_persistence(row, prev_row)
    if mode == "BENCHMARK_BE":
        return avg_cost, "BREAK_EVEN"
    if mode == "STRONG_BE_MINUS_1ATR":
        return (avg_cost - base_atr, "BE_MINUS_1ATR") if strong else (avg_cost, "BREAK_EVEN")
    if mode == "STRONG_BE_MINUS_2ATR":
        return (avg_cost - 2.0 * base_atr, "BE_MINUS_2ATR") if strong else (avg_cost, "BREAK_EVEN")
    if mode == "STRONG_TRAIL4_CAPPED_BE":
        if strong:
            # Never tighten above break-even; this variant only gives extra downside room.
            return min(avg_cost, highest_close - 4.0 * base_atr), "TRAIL4_CAPPED_BE"
        return avg_cost, "BREAK_EVEN"
    if mode == "STRONG_GRACE3":
        if strong and bars_after_harvest <= 3:
            return None, "GRACE3"
        return avg_cost, "BREAK_EVEN"
    if mode == "STRONG_UNTIL_WEAK":
        return (None, "STRONG_NO_BE") if strong else (avg_cost, "BREAK_EVEN_REARMED")
    raise ValueError(mode)


def run_variant(bars, ind, *, start: date, end: date, runner_mode: str) -> dict:
    qty = 0.0
    avg_cost = 0.0
    entry_breakout = None
    entry_bar = None
    base_entry = None
    base_atr = None
    add1_done = add2_done = harvest_done = False
    add1_bar = add2_bar = harvest_bar = None
    current = None
    runner_floor = None
    runner_reason = None
    highest_close_after_harvest = None
    trades: list[dict] = []

    for i, (bar, row) in enumerate(zip(bars, ind)):
        in_window = start <= bar.trade_date <= end
        flat = qty == 0
        price_ok = bar.close >= 25.0
        eff_ok = row["efficiency"] is not None and float(row["efficiency"]) >= 0.20
        rsi_ok = row["rsi"] is not None and float(row["rsi"]) <= 80.0
        adx_ok = entry_adx_ok(ind, i)

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
            add1_bar = add2_bar = harvest_bar = None
            runner_floor = None
            runner_reason = None
            highest_close_after_harvest = None

        bars_since = i - entry_bar if entry_bar is not None else None
        failed_exit = (
            qty > 0 and entry_breakout is not None and bars_since is not None
            and 1 <= bars_since <= 3 and bar.close < entry_breakout
        )
        runner_trend_ok = int(row["trend_state"]) == 1 and row["adx"] is not None and float(row["adx"]) >= 17.0
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
            harvest_bar = i
            highest_close_after_harvest = bar.close

        if harvest_done and harvest_bar is not None and highest_close_after_harvest is not None and base_atr is not None:
            highest_close_after_harvest = max(highest_close_after_harvest, bar.close)
            bars_after_harvest = i - harvest_bar
            candidate_floor, candidate_reason = runner_floor_for(
                runner_mode,
                row=row,
                prev_row=ind[i - 1] if i > 0 else None,
                avg_cost=avg_cost,
                base_atr=base_atr,
                highest_close=highest_close_after_harvest,
                bars_after_harvest=bars_after_harvest,
            )
            # Unlike the prior adaptive test, relaxation is allowed while persistence is strong.
            # When persistence weakens, BE is immediately re-armed.
            runner_floor = candidate_floor
            runner_reason = candidate_reason

        floor_exit = qty > 0 and harvest_done and runner_floor is not None and bar.close <= runner_floor
        turtle_exit = qty > 0 and row["lower10"] is not None and bar.close < float(row["lower10"])
        trend_exit = qty > 0 and bool(row["bear_flip"])
        long_exit = in_window and (floor_exit or failed_exit or turtle_exit or trend_exit)
        if floor_exit:
            exit_reason = runner_reason or "RUNNER_FLOOR"
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
            add1_bar = add2_bar = harvest_bar = None
            current = None
            runner_floor = runner_reason = highest_close_after_harvest = None

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
        "runner_mode": runner_mode,
        "trade_count": len(trades),
        "wins": sum(1 for t in trades if float(t["realized_pnl"]) > 0),
        "aggregate_return_pct_on_gross": pnl / gross * 100.0 if gross else 0.0,
        "compounded_trade_return_pct": (compounded - 1.0) * 100.0 if trades else 0.0,
        "total_pnl_units": pnl,
        "gross_deployed_units": gross,
        "trades": trades,
    }


def summarize(records: dict[str, dict], period_key: str, runner_mode: str) -> dict:
    stats = [r[period_key][runner_mode] for r in records.values() if "data_error" not in r]
    trades = [t for s in stats for t in s["trades"]]
    returns = [s["aggregate_return_pct_on_gross"] for s in stats]
    gains = sum(max(float(t["realized_pnl"]), 0.0) for t in trades)
    losses = -sum(min(float(t["realized_pnl"]), 0.0) for t in trades)
    gross = sum(float(s["gross_deployed_units"]) for s in stats)
    pnl = sum(float(s["total_pnl_units"]) for s in stats)
    return {
        "symbols": len(stats),
        "positive_symbols": sum(1 for x in returns if x > 0),
        "trades": len(trades),
        "wins": sum(1 for t in trades if float(t["realized_pnl"]) > 0),
        "win_rate_pct": (sum(1 for t in trades if float(t["realized_pnl"]) > 0) / len(trades) * 100.0) if trades else 0.0,
        "mean_symbol_return_pct": sum(returns) / len(returns) if returns else 0.0,
        "median_symbol_return_pct": median(returns) if returns else 0.0,
        "profit_factor": gains / losses if losses > 0 else None,
        "gross_deployed_return_pct": pnl / gross * 100.0 if gross else 0.0,
        "best_trade_return_pct": max((float(t["return_pct"]) for t in trades), default=0.0),
        "worst_trade_return_pct": min((float(t["return_pct"]) for t in trades), default=0.0),
    }


def paired_delta(records: dict[str, dict], period_key: str, mode: str) -> dict:
    vals = []
    for r in records.values():
        if "data_error" in r:
            continue
        vals.append(
            r[period_key][mode]["aggregate_return_pct_on_gross"]
            - r[period_key]["BENCHMARK_BE"]["aggregate_return_pct_on_gross"]
        )
    improved = sum(1 for x in vals if x > 1e-12)
    worse = sum(1 for x in vals if x < -1e-12)
    unchanged = len(vals) - improved - worse
    rng = random.Random(250817)
    means = []
    for _ in range(10000):
        sample = [vals[rng.randrange(len(vals))] for _ in vals]
        means.append(sum(sample) / len(sample))
    means.sort()
    return {
        "mean_pp": sum(vals) / len(vals),
        "median_pp": median(vals),
        "improved": improved,
        "unchanged": unchanged,
        "worse": worse,
        "bootstrap95_pp": [means[249], means[9749]],
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
        for fut in as_completed(futures):
            symbol = futures[fut]
            rec = {"symbol": symbol}
            try:
                _, bars, meta, ind = fut.result()
                rec["source"] = meta[0].get("source") if meta else "ORATS"
                rec["select_2022"] = {m: run_variant(bars, ind, start=SELECT_START, end=SELECT_END, runner_mode=m) for m in RUNNERS}
                rec["holdout_2023"] = {m: run_variant(bars, ind, start=HOLDOUT_START, end=HOLDOUT_END, runner_mode=m) for m in RUNNERS}
            except Exception as exc:
                rec["data_error"] = f"{type(exc).__name__}:{exc}"
            records[symbol] = rec

    summary = {
        "design": {
            "entry": "ADX>=17 and rising; v2.4 fresh breakout/trend/maturity/efficiency/RSI unchanged",
            "selection_period": [SELECT_START.isoformat(), SELECT_END.isoformat()],
            "holdout_period": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            "dev_names_excluded": sorted(DEV_SYMBOLS),
        },
        "data_errors": {s:r["data_error"] for s,r in records.items() if "data_error" in r},
        "select_2022": {m: summarize(records, "select_2022", m) for m in RUNNERS},
        "holdout_2023": {m: summarize(records, "holdout_2023", m) for m in RUNNERS},
        "holdout_paired_vs_benchmark": {m: paired_delta(records, "holdout_2023", m) for m in RUNNERS if m != "BENCHMARK_BE"},
        "records": records,
    }

    # Rank only on 2022; 2023 is reported without changing the selected rule.
    rank = sorted(
        RUNNERS,
        key=lambda m: (
            summary["select_2022"][m]["profit_factor"] or 0.0,
            summary["select_2022"][m]["gross_deployed_return_pct"],
            summary["select_2022"][m]["mean_symbol_return_pct"],
        ),
        reverse=True,
    )
    summary["selected_from_2022"] = rank[0]

    Path("v25-runner-persistence.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Daily Alpha v2.5 Runner Persistence Study",
        "",
        f"Valid symbols: {len(records) - len(summary['data_errors'])}; data errors: {len(summary['data_errors'])}",
        f"Rule selected from 2022 only: **{summary['selected_from_2022']}**",
        "",
        "## 2022 selection/reference",
        "",
        "| Runner | Mean symbol | Median | Gross deployed | Trades | Win rate | Profit factor | Positive symbols |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in RUNNERS:
        s = summary["select_2022"][m]
        lines.append(f"| {m} | {s['mean_symbol_return_pct']:.2f}% | {s['median_symbol_return_pct']:.2f}% | {s['gross_deployed_return_pct']:.2f}% | {s['trades']} | {s['win_rate_pct']:.1f}% | {(s['profit_factor'] or 0):.2f} | {s['positive_symbols']}/{s['symbols']} |")
    lines += ["", "## 2023 untouched holdout", "", "| Runner | Mean symbol | Median | Gross deployed | Trades | Win rate | Profit factor | Positive symbols |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for m in RUNNERS:
        s = summary["holdout_2023"][m]
        lines.append(f"| {m} | {s['mean_symbol_return_pct']:.2f}% | {s['median_symbol_return_pct']:.2f}% | {s['gross_deployed_return_pct']:.2f}% | {s['trades']} | {s['win_rate_pct']:.1f}% | {(s['profit_factor'] or 0):.2f} | {s['positive_symbols']}/{s['symbols']} |")
    lines += ["", "## 2023 paired deltas versus benchmark", ""]
    for m, d in summary["holdout_paired_vs_benchmark"].items():
        lines.append(f"- {m}: mean {d['mean_pp']:+.2f}pp; median {d['median_pp']:+.2f}pp; improved/unchanged/worse {d['improved']}/{d['unchanged']}/{d['worse']}; bootstrap95 {d['bootstrap95_pp'][0]:+.2f} to {d['bootstrap95_pp'][1]:+.2f}pp")
    Path("v25-runner-persistence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(Path("v25-runner-persistence.md").read_text())

if __name__ == "__main__":
    main()
