"""Historical option-layer backtest for Daily Alpha v2.4 signals.

Research only. Selects bullish calls using the production OptionQualityRules,
then exits the same contract at the underlying strategy exit or expiration.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from .backtest import fetch_orats_history, indicators, run_strategy
from .backtest_sensitivity import reclassify_gap_go
from .config import OptionQualityRules
from .orats_historical_transport import request_json


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [r for r in payload["data"] if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_chain(ticker: str, trade_date: str, token: str) -> list[dict[str, Any]]:
    q = urlencode({
        "token": token,
        "ticker": ticker,
        "tradeDate": trade_date,
        "dte": "45,75",
        "fields": "ticker,tradeDate,expirDate,dte,strike,stockPrice,callBidPrice,callAskPrice,callVolume,callOpenInterest,delta",
    })
    return _rows(
        request_json(
            f"https://api.orats.io/datav2/hist/strikes?{q}",
            token=token,
            header_auth=False,
        )
    )


def fetch_contract(ticker: str, expiry: str, strike: float, trade_date: str, token: str) -> dict[str, Any] | None:
    q = urlencode({
        "token": token,
        "ticker": ticker,
        "expirDate": expiry,
        "strike": strike,
        "tradeDate": trade_date,
    })
    rows = _rows(
        request_json(
            f"https://api.orats.io/datav2/hist/strikes/options?{q}",
            token=token,
            header_auth=False,
        )
    )
    if not rows:
        return None
    exact = [r for r in rows if str(r.get("tradeDate", ""))[:10] == trade_date]
    return exact[0] if exact else rows[-1]


def select_call(rows: list[dict[str, Any]], rules: OptionQualityRules) -> dict[str, Any] | None:
    qualified = []
    for r in rows:
        bid = _num(r.get("callBidPrice")); ask = _num(r.get("callAskPrice"))
        mid = (bid + ask) / 2 if bid > 0 and ask >= bid else 0
        spread = (ask - bid) / mid if mid > 0 else 999
        delta = _num(r.get("delta")); dte = int(_num(r.get("dte")))
        oi = int(_num(r.get("callOpenInterest"))); vol = int(_num(r.get("callVolume")))
        if (rules.min_dte <= dte <= rules.max_dte and bid >= rules.min_bid and ask >= bid
                and spread <= rules.max_spread_pct and oi >= rules.min_open_interest
                and vol >= rules.min_volume and rules.min_abs_delta <= abs(delta) <= rules.max_abs_delta):
            qualified.append((spread, -oi, -vol, abs(delta - 0.55), -dte, r))
    return min(qualified, key=lambda x: x[:-1])[-1] if qualified else None


def mid_call(row: dict[str, Any]) -> float:
    bid = _num(row.get("callBidPrice")); ask = _num(row.get("callAskPrice"))
    return (bid + ask) / 2 if bid >= 0 and ask >= bid else 0.0


def optionize_trade(ticker: str, trade: Any, token: str) -> dict[str, Any]:
    entry_date = trade.entry_date
    chain = fetch_chain(ticker, entry_date, token)
    selected = select_call(chain, OptionQualityRules())
    base = {"ticker": ticker, "entry_type": trade.entry_type, "underlying_entry": entry_date,
            "underlying_exit": trade.exit_date, "underlying_r": trade.r_multiple}
    if selected is None:
        return {**base, "status": "NO_QUALIFIED_OPTION"}
    expiry = str(selected.get("expirDate"))[:10]
    strike = _num(selected.get("strike")); entry_mid = mid_call(selected)
    if entry_mid <= 0:
        return {**base, "status": "NO_ENTRY_MID"}
    effective_exit = min(date.fromisoformat(trade.exit_date), date.fromisoformat(expiry)).isoformat()
    exit_row = fetch_contract(ticker, expiry, strike, effective_exit, token)
    if exit_row is None:
        # walk backwards for holidays / missing expiration snapshot
        d = date.fromisoformat(effective_exit)
        for _ in range(5):
            d -= timedelta(days=1)
            exit_row = fetch_contract(ticker, expiry, strike, d.isoformat(), token)
            if exit_row is not None:
                effective_exit = d.isoformat(); break
    if exit_row is None:
        return {**base, "status": "NO_EXIT_QUOTE", "expiry": expiry, "strike": strike}
    exit_mid = mid_call(exit_row)
    ret = (exit_mid - entry_mid) / entry_mid * 100
    return {**base, "status": "OK", "expiry": expiry, "strike": strike,
            "entry_dte": int(_num(selected.get("dte"))), "delta": _num(selected.get("delta")),
            "entry_mid": round(entry_mid, 4), "exit_date": effective_exit,
            "exit_mid": round(exit_mid, 4), "option_return_pct": round(ret, 2),
            "expired_before_signal_exit": effective_exit < trade.exit_date}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default="MRVL,NVDA,AMD,AVGO,MU,QCOM,ARM,INTC,DELL,ORCL,MSFT,GOOGL,META,AMZN,NFLX,CRM,NOW,TSLA")
    p.add_argument("--start", default="2024-01-01"); p.add_argument("--end", default="2026-08-14")
    p.add_argument("--close-location", type=float, default=0.70); p.add_argument("--json-out", default="")
    args = p.parse_args(); token = os.getenv("ORATS_TOKEN", "").strip()
    if not token: raise SystemExit("ORATS_TOKEN is required")
    start = date.fromisoformat(args.start); end = date.fromisoformat(args.end)
    results=[]; failures=[]
    for ticker in [x.strip().upper() for x in args.tickers.split(",") if x.strip()]:
        try:
            bars,_=fetch_orats_history(ticker,start=start,end=end,token=token)
            rows=reclassify_gap_go(bars,indicators(bars),close_location=args.close_location)
            trades,_=run_strategy(bars,rows,version="2.4",start=start,end=end)
            for t in trades: results.append(optionize_trade(ticker,t,token))
        except (RuntimeError, ValueError) as exc:
            failures.append(f"{ticker}:{type(exc).__name__}")
    ok=[r for r in results if r.get("status")=="OK"]
    gap=[r for r in ok if r["entry_type"]=="EARNINGS_GAP_GO"]
    normal=[r for r in ok if r["entry_type"]=="NORMAL_BREAKOUT"]
    def stats(rows):
        vals=[r["option_return_pct"] for r in rows]
        return {"trades":len(rows),"wins":sum(v>0 for v in vals),"win_rate_pct":round(100*sum(v>0 for v in vals)/len(vals),2) if vals else 0,
                "avg_return_pct":round(statistics.mean(vals),2) if vals else None,"median_return_pct":round(statistics.median(vals),2) if vals else None,
                "sum_return_pct":round(sum(vals),2),"expired_before_signal_exit":sum(bool(r.get("expired_before_signal_exit")) for r in rows)}
    report={"close_location":args.close_location,"all":stats(ok),"gap_go":stats(gap),"normal":stats(normal),
            "no_qualified_option":sum(r.get("status")=="NO_QUALIFIED_OPTION" for r in results),"failures":failures,"trades":results}
    print("DAILY ALPHA HISTORICAL OPTION BACKTEST")
    print(json.dumps({k:v for k,v in report.items() if k!="trades"},sort_keys=True))
    print("GAP_GO_OPTIONS")
    for r in gap: print(json.dumps(r,sort_keys=True))
    if args.json_out:
        with open(args.json_out,"w",encoding="utf-8") as fh: json.dump(report,fh,indent=2,sort_keys=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
