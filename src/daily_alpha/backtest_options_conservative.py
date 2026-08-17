"""Conservative Gap & Go option backtest using ask entry and bid exit."""
from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import date, timedelta
from typing import Any

from .backtest import fetch_orats_history, indicators, run_strategy
from .backtest_options import _num, fetch_chain, fetch_contract, select_call
from .backtest_sensitivity import reclassify_gap_go
from .config import OptionQualityRules

TICKERS = (
    "MRVL,NVDA,AMD,AVGO,MU,QCOM,ARM,INTC,DELL,ORCL,MSFT,GOOGL,META,"
    "AMZN,NFLX,CRM,NOW,TSLA"
)


def optionize_conservative(ticker: str, trade: Any, token: str) -> dict[str, Any]:
    chain = fetch_chain(ticker, trade.entry_date, token)
    selected = select_call(chain, OptionQualityRules())
    base = {
        "ticker": ticker,
        "entry_type": trade.entry_type,
        "underlying_entry": trade.entry_date,
        "underlying_exit": trade.exit_date,
        "underlying_r": trade.r_multiple,
    }
    if selected is None:
        return {**base, "status": "NO_QUALIFIED_OPTION"}

    expiry = str(selected.get("expirDate", ""))[:10]
    strike = _num(selected.get("strike"))
    entry_ask = _num(selected.get("callAskPrice"))
    if entry_ask <= 0:
        return {**base, "status": "NO_ENTRY_ASK"}

    signal_exit = date.fromisoformat(trade.exit_date)
    expiration = date.fromisoformat(expiry)
    effective_exit = min(signal_exit, expiration)
    exit_row = fetch_contract(ticker, expiry, strike, effective_exit.isoformat(), token)
    if exit_row is None:
        for _ in range(5):
            effective_exit -= timedelta(days=1)
            exit_row = fetch_contract(
                ticker, expiry, strike, effective_exit.isoformat(), token
            )
            if exit_row is not None:
                break
    if exit_row is None:
        return {**base, "status": "NO_EXIT_QUOTE", "expiry": expiry, "strike": strike}

    exit_bid = _num(exit_row.get("callBidPrice"))
    if exit_bid < 0:
        return {**base, "status": "INVALID_EXIT_BID", "expiry": expiry, "strike": strike}
    option_return = (exit_bid - entry_ask) / entry_ask * 100.0
    return {
        **base,
        "status": "OK",
        "expiry": expiry,
        "strike": strike,
        "entry_dte": int(_num(selected.get("dte"))),
        "delta": _num(selected.get("delta")),
        "entry_ask": round(entry_ask, 4),
        "exit_date": effective_exit.isoformat(),
        "exit_bid": round(exit_bid, 4),
        "option_return_pct": round(option_return, 2),
        "expired_before_signal_exit": effective_exit < signal_exit,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "OK"]
    returns = [float(row["option_return_pct"]) for row in completed]
    return {
        "qualified_option_trades": len(completed),
        "no_qualified_option": sum(
            row.get("status") == "NO_QUALIFIED_OPTION" for row in rows
        ),
        "wins": sum(value > 0 for value in returns),
        "win_rate_pct": (
            round(100.0 * sum(value > 0 for value in returns) / len(returns), 2)
            if returns
            else 0.0
        ),
        "avg_return_pct": round(statistics.mean(returns), 2) if returns else None,
        "median_return_pct": round(statistics.median(returns), 2) if returns else None,
        "sum_return_pct": round(sum(returns), 2),
        "expired_before_signal_exit": sum(
            bool(row.get("expired_before_signal_exit")) for row in completed
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", default="0.70,0.75")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")

    start = date(2024, 1, 1)
    end = date(2026, 8, 14)
    report: list[dict[str, Any]] = []
    cached: dict[str, tuple[list[Any], list[dict[str, Any]]]] = {}
    failures: list[str] = []

    for ticker in TICKERS.split(","):
        try:
            bars, _ = fetch_orats_history(ticker, start=start, end=end, token=token)
            cached[ticker] = (bars, indicators(bars))
        except (RuntimeError, ValueError) as exc:
            failures.append(f"{ticker}:{type(exc).__name__}")

    for threshold in [float(value) for value in args.thresholds.split(",")]:
        option_rows: list[dict[str, Any]] = []
        gap_signals = 0
        for ticker, (bars, base_rows) in cached.items():
            rows = reclassify_gap_go(bars, base_rows, close_location=threshold)
            trades, _ = run_strategy(
                bars, rows, version="2.4", start=start, end=end
            )
            gap_trades = [
                trade for trade in trades if trade.entry_type == "EARNINGS_GAP_GO"
            ]
            gap_signals += len(gap_trades)
            for trade in gap_trades:
                option_rows.append(optionize_conservative(ticker, trade, token))

        summary = summarize(option_rows)
        result = {
            "threshold": threshold,
            "gap_go_signals": gap_signals,
            "failures": failures,
            **summary,
            "trades": option_rows,
        }
        report.append(result)
        print(
            "CONSERVATIVE_GAP_GO_OPTION_BACKTEST",
            json.dumps(
                {key: value for key, value in result.items() if key != "trades"},
                sort_keys=True,
            ),
        )
        for row in option_rows:
            if row.get("status") == "OK":
                print(json.dumps(row, sort_keys=True))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
