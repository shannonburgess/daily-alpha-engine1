"""Research-only comparison of 10-day vs 20-day normal breakout entries.

Entry ADX is frozen at the validated v2.5 candidate: ADX >=17 and rising.
All other v2.4/v2.5 gates, adds, exits, and Earnings Gap & Go behavior are unchanged.
No broker calls, Lambda execution, or paper-ledger writes.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import median

from daily_alpha.backtest import fetch_orats_history, indicators

DEV_SYMBOLS = [
    "LRCX","MU","FTI","IRM","RCMT","HUBB","ALGN","HUM","MRK","PSX","VLO",
    "PLTR","SNDK","JNJ","HOOD","C",
]
HOLDOUT_SYMBOLS = [
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
HOLDOUT_SYMBOLS = [s for i, s in enumerate(HOLDOUT_SYMBOLS) if s not in DEV_SYMBOLS and s not in HOLDOUT_SYMBOLS[:i]]
ALL_SYMBOLS = HOLDOUT_SYMBOLS + [s for s in DEV_SYMBOLS if s not in HOLDOUT_SYMBOLS]

PERIODS = {
    "2022": (date(2022,1,1), date(2022,12,31)),
    "2023": (date(2023,1,1), date(2023,12,31)),
    "2024_25": (date(2024,1,1), date(2025,12,31)),
    "2026_YTD": (date(2026,1,1), date(2026,7,31)),
}
FETCH_START = date(2021,1,1)
FETCH_END = date(2026,7,31)
BREAKOUTS = (10, 20)


def upper_and_fresh(bars, i: int, length: int):
    if i < length:
        return None, False
    upper = max(b.high for b in bars[i-length:i])
    breakout_now = bars[i].close > upper
    breakout_prev = False
    if i >= length + 1:
        prev_upper = max(b.high for b in bars[i-length-1:i-1])
        breakout_prev = bars[i-1].close > prev_upper
    return upper, breakout_now and not breakout_prev


def entry_adx_ok(ind, i: int) -> bool:
    value = ind[i]["adx"]
    if value is None or float(value) < 17.0 or i <= 0 or ind[i-1]["adx"] is None:
        return False
    return float(value) > float(ind[i-1]["adx"])


def run_variant(bars, ind, *, start: date, end: date, breakout_len: int) -> dict:
    qty = 0.0
    avg_cost = 0.0
    entry_breakout = None
    entry_bar = None
    base_entry = None
    base_atr = None
    add1_done = add2_done = harvest_done = False
    add1_bar = add2_bar = None
    current = None
    break_even = None
    trades: list[dict] = []

    for i, (bar, row) in enumerate(zip(bars, ind)):
        in_window = start <= bar.trade_date <= end
        flat = qty == 0
        upper_n, fresh_n = upper_and_fresh(bars, i, breakout_len)
        price_ok = bar.close >= 25.0
        eff_ok = row["efficiency"] is not None and float(row["efficiency"]) >= 0.20
        rsi_ok = row["rsi"] is not None and float(row["rsi"]) <= 80.0
        adx_ok = entry_adx_ok(ind, i)

        normal_setup = (
            in_window and flat and fresh_n
            and not bool(row["is_earnings_up_gap"])
            and int(row["trend_state"]) == 1
            and bool(row["normal_trend_mature"])
        )
        normal_entry = normal_setup and price_ok and eff_ok and rsi_ok and adx_ok
        # Earnings sleeve intentionally unchanged: preserve existing 20-day Gap & Go behavior.
        gap_entry = in_window and flat and bool(row["gap_go"]) and bool(row["fresh_breakout"]) and price_ok
        long_entry = normal_entry or gap_entry
        entry_type = "EARNINGS_GAP_GO" if gap_entry else f"NORMAL_BREAKOUT_{breakout_len}D" if normal_entry else "NONE"
        signal_breakout = float(row["upper20"]) if gap_entry and row["upper20"] is not None else upper_n

        if long_entry:
            entry_breakout = float(signal_breakout) if signal_breakout is not None else None
            entry_bar = i
            base_entry = bar.close
            base_atr = float(row["atr"]) if row["atr"] is not None else None
            add1_done = add2_done = harvest_done = False
            add1_bar = add2_bar = None
            break_even = None

        bars_since = i - entry_bar if entry_bar is not None else None
        failed_exit = (
            qty > 0 and entry_breakout is not None and bars_since is not None
            and 1 <= bars_since <= 3 and bar.close < entry_breakout
        )
        runner_trend_ok = (
            int(row["trend_state"]) == 1
            and row["adx"] is not None and float(row["adx"]) >= 17.0
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
            break_even = avg_cost

        be_exit = qty > 0 and harvest_done and break_even is not None and bar.close <= break_even
        turtle_exit = qty > 0 and row["lower10"] is not None and bar.close < float(row["lower10"])
        trend_exit = qty > 0 and bool(row["bear_flip"])
        long_exit = in_window and (be_exit or failed_exit or turtle_exit or trend_exit)
        if be_exit:
            exit_reason = "BREAK_EVEN"
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
                "entry_breakout": entry_breakout,
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
            break_even = None

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
    return {
        "breakout_len": breakout_len,
        "trade_count": len(trades),
        "wins": sum(1 for t in trades if float(t["realized_pnl"]) > 0),
        "aggregate_return_pct_on_gross": pnl / gross * 100.0 if gross else 0.0,
        "total_pnl_units": pnl,
        "gross_deployed_units": gross,
        "trades": trades,
    }


def summarize(records, period_key: str, length: int, symbols: list[str]) -> dict:
    stats = [records[s][period_key][str(length)] for s in symbols if "data_error" not in records[s]]
    trades = [t for st in stats for t in st["trades"]]
    returns = [st["aggregate_return_pct_on_gross"] for st in stats]
    gains = sum(max(float(t["realized_pnl"]), 0.0) for t in trades)
    losses = -sum(min(float(t["realized_pnl"]), 0.0) for t in trades)
    return {
        "symbols": len(stats),
        "symbols_with_trades": sum(1 for st in stats if st["trade_count"] > 0),
        "positive_symbols": sum(1 for st in stats if st["aggregate_return_pct_on_gross"] > 0),
        "mean_symbol_return_pct": sum(returns)/len(returns) if returns else 0.0,
        "median_symbol_return_pct": median(returns) if returns else 0.0,
        "trades": len(trades),
        "wins": sum(1 for t in trades if float(t["realized_pnl"]) > 0),
        "win_rate_pct": (sum(1 for t in trades if float(t["realized_pnl"]) > 0)/len(trades)*100.0) if trades else 0.0,
        "profit_factor": gains/losses if losses > 0 else None,
        "gross_deployed_return_pct": (sum(st["total_pnl_units"] for st in stats)/sum(st["gross_deployed_units"] for st in stats)*100.0) if sum(st["gross_deployed_units"] for st in stats) else 0.0,
        "failed_breakouts": sum(1 for t in trades if t.get("exit_reason") == "FAILED_BREAKOUT"),
        "turtle10_exits": sum(1 for t in trades if t.get("exit_reason") == "TURTLE_10"),
        "harvested_trades": sum(1 for t in trades if t.get("harvested")),
    }


def fetch_one(symbol: str, token: str):
    bars, meta = fetch_orats_history(symbol, start=FETCH_START, end=FETCH_END, token=token)
    return symbol, bars, meta, indicators(bars)


def main():
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN missing")
    records = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_one, s, token): s for s in ALL_SYMBOLS}
        for fut in as_completed(futures):
            symbol = futures[fut]
            rec = {"symbol": symbol, "group": "DEV" if symbol in DEV_SYMBOLS else "HOLDOUT"}
            try:
                _, bars, meta, ind = fut.result()
                rec["source"] = meta[0].get("source") if meta else "ORATS"
                for period_key, (start, end) in PERIODS.items():
                    rec[period_key] = {str(n): run_variant(bars, ind, start=start, end=end, breakout_len=n) for n in BREAKOUTS}
            except Exception as exc:
                rec["data_error"] = f"{type(exc).__name__}:{exc}"
            records[symbol] = rec

    output = {
        "definitions": {
            "10D": "Normal entry uses fresh close above prior 10 trading-day high; ADX>=17 and rising; other gates unchanged",
            "20D": "Validated v2.5 entry benchmark: fresh close above prior 20 trading-day high; ADX>=17 and rising",
            "earnings": "Earnings Gap & Go remains on existing v2.4/v2.5 20-day breakout behavior in both variants",
            "exit": "Both variants retain failed-breakout, Turtle-10, trend-flip, +1/+2 ATR adds, +3ATR harvest and post-harvest break-even",
        },
        "holdout_count": len(HOLDOUT_SYMBOLS),
        "dev_count": len(DEV_SYMBOLS),
        "records": records,
        "summary": {},
    }
    for period_key in PERIODS:
        output["summary"][period_key] = {
            "HOLDOUT": {str(n): summarize(records, period_key, n, HOLDOUT_SYMBOLS) for n in BREAKOUTS},
            "DEV": {str(n): summarize(records, period_key, n, DEV_SYMBOLS) for n in BREAKOUTS},
        }

    # First-entry timing diagnostics for 2026 and the development names.
    first_entry = {}
    for symbol in ALL_SYMBOLS:
        if "data_error" in records[symbol]:
            continue
        first_entry[symbol] = {}
        for period_key in PERIODS:
            first_entry[symbol][period_key] = {}
            for n in BREAKOUTS:
                trades = records[symbol][period_key][str(n)]["trades"]
                first_entry[symbol][period_key][str(n)] = trades[0] if trades else None
    output["first_entry"] = first_entry

    Path("v25-10day-breakout.json").write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Daily Alpha v2.5 — 10-day vs 20-day breakout study",
        "",
        f"Holdout symbols: {len(HOLDOUT_SYMBOLS)}; development symbols: {len(DEV_SYMBOLS)}; data errors: {sum(1 for r in records.values() if 'data_error' in r)}",
        "",
        "## 113-stock decision universe",
        "",
        "| Period | Breakout | Mean symbol | Median | Gross deployed | Trades | Win rate | Profit factor | Positive | Failed BO | Harvested |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period_key in PERIODS:
        for n in BREAKOUTS:
            s = output["summary"][period_key]["HOLDOUT"][str(n)]
            lines.append(
                f"| {period_key} | {n}D | {s['mean_symbol_return_pct']:.2f}% | {s['median_symbol_return_pct']:.2f}% | {s['gross_deployed_return_pct']:.2f}% | {s['trades']} | {s['win_rate_pct']:.1f}% | {s['profit_factor']:.2f} | {s['positive_symbols']}/{s['symbols']} | {s['failed_breakouts']} | {s['harvested_trades']} |"
            )
    lines += ["", "## Development-name 2026 diagnostic", "", "| Symbol | 10D first entry | 10D return | 20D first entry | 20D return |", "|---|---|---:|---|---:|"]
    for symbol in DEV_SYMBOLS:
        r = records[symbol]
        if "data_error" in r:
            lines.append(f"| {symbol} | DATA_ERROR | | | |")
            continue
        t10 = r["2026_YTD"]["10"]["trades"]
        t20 = r["2026_YTD"]["20"]["trades"]
        d10 = t10[0]["entry_date"] if t10 else "NONE"
        d20 = t20[0]["entry_date"] if t20 else "NONE"
        x10 = r["2026_YTD"]["10"]["aggregate_return_pct_on_gross"]
        x20 = r["2026_YTD"]["20"]["aggregate_return_pct_on_gross"]
        lines.append(f"| {symbol} | {d10} | {x10:.2f}% | {d20} | {x20:.2f}% |")

    Path("v25-10day-breakout.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(Path("v25-10day-breakout.md").read_text())


if __name__ == "__main__":
    main()
