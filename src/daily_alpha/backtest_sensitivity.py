"""Close-location sensitivity study for the Daily Alpha earnings Gap & Go sleeve."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from dataclasses import asdict
from datetime import date
from typing import Any

from .backtest import fetch_orats_history, indicators, run_strategy, summarize


def reclassify_gap_go(
    bars: list[Any], rows: list[dict[str, Any]], *, close_location: float
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for bar, original in zip(bars, rows, strict=True):
        row = dict(original)
        upper20 = row.get("upper20")
        earnings_breakout = upper20 is not None and bar.close > float(upper20)
        rsi = row.get("rsi")
        gap_go = bool(
            row.get("is_earnings_up_gap")
            and bar.close >= bar.open
            and float(row.get("close_location", 0.0)) >= close_location
            and float(row.get("gap_retention", 0.0)) >= 0.70
            and float(row.get("relative_volume", 0.0)) >= 1.50
            and rsi is not None
            and float(rsi) <= 85.0
            and int(row.get("trend_state", 0)) == 1
            and earnings_breakout
        )
        gap_crap = bool(
            row.get("is_earnings_up_gap")
            and not gap_go
            and (
                (bar.close < bar.close - float(row.get("gap_retention", 0.0)) * float(row.get("gap_dollars", 0.0)))
                or float(row.get("gap_retention", 0.0)) < 0.50
                or (bar.close < bar.open and float(row.get("close_location", 0.0)) < 0.50)
            )
        )
        # The first crap clause above is algebraically awkward because previous close is not stored.
        # Recover previous close directly from gap retention / dollars where possible.
        if row.get("is_earnings_up_gap") and not gap_go:
            gap_dollars = float(row.get("gap_dollars", 0.0))
            retention = float(row.get("gap_retention", 0.0))
            previous_close = bar.close - retention * gap_dollars if gap_dollars > 0 else bar.close
            gap_crap = bool(
                bar.close < previous_close
                or retention < 0.50
                or (bar.close < bar.open and float(row.get("close_location", 0.0)) < 0.50)
            )
        row["gap_go"] = gap_go
        row["gap_crap"] = gap_crap
        row["gap_wait"] = bool(row.get("is_earnings_up_gap") and not gap_go and not gap_crap)
        adjusted.append(row)
    return adjusted


def _gap_trade_stats(trades: list[Any]) -> dict[str, Any]:
    gap = [trade for trade in trades if trade.entry_type == "EARNINGS_GAP_GO"]
    rs = [
        float(trade.r_multiple)
        for trade in gap
        if trade.r_multiple is not None and math.isfinite(float(trade.r_multiple))
    ]
    returns = [float(trade.return_pct) for trade in gap]
    best_r = max(rs) if rs else None
    return {
        "trades": len(gap),
        "wins": sum(trade.realized_pnl > 0 for trade in gap),
        "win_rate_pct": round(100 * sum(trade.realized_pnl > 0 for trade in gap) / len(gap), 2)
        if gap
        else 0.0,
        "total_r": round(sum(rs), 2),
        "avg_r": round(statistics.mean(rs), 2) if rs else None,
        "median_r": round(statistics.median(rs), 2) if rs else None,
        "total_r_ex_best": round(sum(rs) - best_r, 2) if best_r is not None else None,
        "best_r": round(best_r, 2) if best_r is not None else None,
        "sum_return_pct": round(sum(returns), 2),
        "median_return_pct": round(statistics.median(returns), 2) if returns else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tickers",
        default="MRVL,NVDA,AMD,AVGO,MU,QCOM,ARM,INTC,DELL,ORCL,MSFT,GOOGL,META,AMZN,NFLX,CRM,NOW,TSLA",
    )
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--thresholds", default="0.60,0.65,0.70,0.75,0.80")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")

    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    thresholds = [float(value) for value in args.thresholds.split(",")]
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    data: dict[str, tuple[list[Any], list[dict[str, Any]]]] = {}
    failures: list[str] = []
    for ticker in tickers:
        try:
            bars, _ = fetch_orats_history(ticker, start=start, end=end, token=token)
            data[ticker] = (bars, indicators(bars))
        except Exception as exc:  # research batch should continue per ticker
            failures.append(f"{ticker}:{type(exc).__name__}")

    results: list[dict[str, Any]] = []
    mrvl: list[dict[str, Any]] = []
    for threshold in thresholds:
        all_trades: list[Any] = []
        per_ticker: list[dict[str, Any]] = []
        for ticker, (bars, base_rows) in data.items():
            rows = reclassify_gap_go(bars, base_rows, close_location=threshold)
            trades, events = run_strategy(bars, rows, version="2.4", start=start, end=end)
            all_trades.extend(trades)
            summary = summarize(trades)
            per_ticker.append(
                {
                    "ticker": ticker,
                    "trades": summary["trades"],
                    "total_r": summary["total_r"],
                    "gap_go_trades": summary["gap_go_trades"],
                }
            )
            if ticker == "MRVL":
                event = next((item for item in events if item["date"] == "2026-03-06"), None)
                trade = next(
                    (
                        asdict(item)
                        for item in trades
                        if item.entry_type == "EARNINGS_GAP_GO" and item.entry_date == "2026-03-06"
                    ),
                    None,
                )
                mrvl.append(
                    {
                        "threshold": threshold,
                        "event": event,
                        "trade": trade,
                    }
                )

        cohort = summarize(all_trades)
        results.append(
            {
                "close_location_threshold": threshold,
                "cohort": cohort,
                "gap_go": _gap_trade_stats(all_trades),
                "per_ticker": per_ticker,
            }
        )

    report = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "tickers_completed": sorted(data),
        "failures": failures,
        "thresholds": results,
        "mrvl_2026_03_06": mrvl,
    }

    print("DAILY ALPHA GAP & GO CLOSE-LOCATION SENSITIVITY")
    for result in results:
        cohort = result["cohort"]
        gap = result["gap_go"]
        print(
            f"threshold={result['close_location_threshold']:.2f} "
            f"cohort_trades={cohort['trades']} cohort_R={cohort['total_r']:.2f} "
            f"gap_trades={gap['trades']} gap_win={gap['win_rate_pct']:.2f}% "
            f"gap_R={gap['total_r']:.2f} gap_avg_R={gap['avg_r']} "
            f"gap_median_R={gap['median_r']} gap_R_ex_best={gap['total_r_ex_best']}"
        )
    print()
    print("MRVL 2026-03-06")
    for item in mrvl:
        print(json.dumps(item, sort_keys=True))
    print()
    print("FAILURES")
    print(json.dumps(failures))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
