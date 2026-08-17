"""Integrated Daily Alpha portfolio + executable long-call accelerator backtest.

Uses a 95% scaled S8 share/2x control and a 5% premium account. Options are
entered at the historical ask, marked/exited at the historical bid, limited to
1.5% NAV per position and two concurrent positions. Research only.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from .backtest import _request_json, fetch_orats_history, indicators, run_strategy
from .backtest_options import _num, _rows, fetch_contract
from .backtest_options_conservative import optionize_conservative
from .scenario_backtest import DEFAULT_STOCKS, metrics, r2_scores
from .scenario_backtest import run as run_scenarios

OPTION_COHORT = (
    "MRVL,NVDA,AMD,AVGO,MU,QCOM,ARM,INTC,DELL,ORCL,MSFT,GOOGL,META,"
    "AMZN,NFLX,CRM,NOW,TSLA"
)


def contract_history(
    ticker: str, expiry: str, strike: float, start: date, end: date, token: str
) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "token": token, "ticker": ticker, "expirDate": expiry,
            "strike": strike,
        }
    )
    url = f"https://api.orats.io/datav2/hist/strikes/options?{query}"
    error: RuntimeError | None = None
    for attempt in range(4):
        try:
            payload = _request_json(url, token=token, header_auth=False)
            break
        except RuntimeError as exc:
            error = exc
            if "HTTP 502" not in str(exc) or attempt == 3:
                raise
            time.sleep(2**attempt)
    else:
        assert error is not None
        raise error
    return _rows(payload)


def candidate_options(start: date, end: date, token: str) -> list[dict[str, Any]]:
    """Select only point-in-time top-two R2 entries before querying options."""
    trades: list[tuple[str, Any]] = []
    scores: dict[str, dict[date, float]] = {}
    for ticker in OPTION_COHORT.split(","):
        bars, _ = fetch_orats_history(ticker, start=start, end=end, token=token)
        scores[ticker] = r2_scores(bars)
        rows = indicators(bars)
        ticker_trades, _ = run_strategy(
            bars, rows, version="2.4", start=start, end=end
        )
        trades.extend((ticker, trade) for trade in ticker_trades)

    by_entry: dict[date, list[tuple[str, Any]]] = {}
    for ticker, trade in trades:
        by_entry.setdefault(date.fromisoformat(trade.entry_date), []).append((ticker, trade))

    selected: list[dict[str, Any]] = []
    for entry_date, entry_trades in sorted(by_entry.items()):
        ranked = sorted(
            entry_trades,
            key=lambda item: scores[item[0]].get(entry_date, float("-inf")),
            reverse=True,
        )[:2]
        for ticker, trade in ranked:
            row = optionize_conservative(ticker, trade, token)
            if row.get("status") == "OK":
                expiry = date.fromisoformat(str(row["expiry"]))
                roll_date = expiry - timedelta(days=21)
                current_exit = date.fromisoformat(str(row["exit_date"]))
                entry_date_actual = date.fromisoformat(str(row["underlying_entry"]))
                if entry_date_actual < roll_date < current_exit:
                    quote_date = roll_date
                    exit_row = None
                    for _ in range(6):
                        exit_row = fetch_contract(
                            ticker, str(row["expiry"]), float(row["strike"]),
                            quote_date.isoformat(), token,
                        )
                        if exit_row is not None:
                            break
                        quote_date -= timedelta(days=1)
                    if exit_row is None:
                        row = {**row, "status": "NO_21_DTE_EXIT_QUOTE"}
                    else:
                        row["exit_date"] = quote_date.isoformat()
                        row["exit_bid"] = round(_num(exit_row.get("callBidPrice")), 4)
                        row["exit_reason"] = "21_DTE"
            row["rank_at_entry"] = next(
                i + 1 for i, item in enumerate(ranked) if item[0] == ticker
            )
            selected.append(row)
    return selected


def daily_marks(
    trade: dict[str, Any], dates: list[date], token: str
) -> dict[date, float]:
    marks: dict[date, float] = {}
    start = date.fromisoformat(str(trade["underlying_entry"]))
    end = date.fromisoformat(str(trade["exit_date"]))
    history = contract_history(
        str(trade["ticker"]), str(trade["expiry"]), float(trade["strike"]),
        start, end, token,
    )
    by_date = {
        date.fromisoformat(str(row["tradeDate"])[:10]): row
        for row in history if row.get("tradeDate")
    }
    last_bid: float | None = None
    for mark_date in dates:
        if mark_date < start or mark_date > end:
            continue
        row = by_date.get(mark_date)
        if row is not None:
            bid = _num(row.get("callBidPrice"))
            if bid >= 0:
                last_bid = bid
        if last_bid is not None:
            marks[mark_date] = last_bid
    return marks


def simulate_integrated(
    control_curve: list[dict[str, Any]], option_rows: list[dict[str, Any]], token: str
) -> tuple[list[tuple[date, float]], dict[str, Any]]:
    dates = [date.fromisoformat(row["date"]) for row in control_curve]
    control = {date.fromisoformat(row["date"]): float(row["nav"]) for row in control_curve}
    valid = [row for row in option_rows if row.get("status") == "OK"]
    all_marks = [daily_marks(row, dates, token) for row in valid]

    initial = control[dates[0]]
    core_units = 0.95
    option_cash = initial * 0.05
    positions: dict[int, tuple[float, float]] = {}  # index -> contracts, cost
    nav: list[tuple[date, float]] = []
    exposure: list[float] = []
    realized_option_pnl = 0.0

    for d in dates:
        core_value = control[d] * core_units
        marked = sum(qty * all_marks[i].get(d, 0.0) * 100 for i, (qty, _) in positions.items())
        total_before = core_value + option_cash + marked

        for i, row in enumerate(valid):
            if date.fromisoformat(row["underlying_entry"]) != d or i in positions:
                continue
            if len(positions) >= 2:
                continue
            ask = float(row["entry_ask"])
            allocation = min(total_before * 0.015, option_cash)
            contracts = int(allocation // (ask * 100))
            if contracts < 1:
                continue
            cost = contracts * ask * 100
            option_cash -= cost
            positions[i] = (float(contracts), cost)

        for i in list(positions):
            row = valid[i]
            if date.fromisoformat(row["exit_date"]) != d:
                continue
            qty, cost = positions.pop(i)
            proceeds = qty * float(row["exit_bid"]) * 100
            option_cash += proceeds
            realized_option_pnl += proceeds - cost

        marked = sum(qty * all_marks[i].get(d, 0.0) * 100 for i, (qty, _) in positions.items())
        total = core_value + option_cash + marked
        nav.append((d, total))
        exposure.append((core_value + marked) / total if total > 0 else 0.0)

    summary = metrics(nav, exposure, 0.0)
    summary.update(
        {
            "qualified_option_candidates": len(valid),
            "option_positions_opened": sum(
                1 for row in valid if float(row.get("entry_ask", 0)) * 100 <= initial * 0.015
            ),
            "realized_option_pnl": round(realized_option_pnl, 2),
            "option_pnl_pct_initial_nav": round(realized_option_pnl / initial * 100, 2),
        }
    )
    return nav, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--json-out", default="portfolio-options.json")
    args = parser.parse_args()
    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")

    scenario_args = SimpleNamespace(
        start=args.start, end=args.end,
        stocks=DEFAULT_STOCKS,
        initial_nav=1_000_000.0, workers=6,
    )
    control = run_scenarios(scenario_args)
    option_rows = candidate_options(
        date.fromisoformat(args.start), date.fromisoformat(args.end), token
    )
    nav, integrated = simulate_integrated(
        control["curves"]["S8_RANKED_TOP10_2X"], option_rows, token
    )
    result = {
        "performance_basis": "BACKTEST",
        "control": control["results"]["S8_RANKED_TOP10_2X"],
        "integrated_options": integrated,
        "option_rules": {
            "premium_budget_pct": 5.0, "per_position_pct": 1.5,
            "max_concurrent": 2, "entry_mark": "ASK", "daily_exit_mark": "BID",
        },
        "option_candidates": option_rows,
        "integrated_curve": [
            {"date": d.isoformat(), "nav": round(value, 2)} for d, value in nav
        ],
    }
    Path(args.json_out).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("DAILY ALPHA INTEGRATED OPTIONS PORTFOLIO")
    print("CONTROL", json.dumps(result["control"], sort_keys=True))
    print("INTEGRATED", json.dumps(integrated, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
