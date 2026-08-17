"""Focused historical option backtest for Gap & Go entries."""
from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import date

from .backtest import fetch_orats_history, indicators, run_strategy
from .backtest_options import optionize_trade
from .backtest_sensitivity import reclassify_gap_go

TICKERS = "MRVL,NVDA,AMD,AVGO,MU,QCOM,ARM,INTC,DELL,ORCL,MSFT,GOOGL,META,AMZN,NFLX,CRM,NOW,TSLA"


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--thresholds",default="0.70,0.75"); p.add_argument("--json-out",default="")
    a=p.parse_args(); token=os.getenv("ORATS_TOKEN","").strip()
    if not token: raise SystemExit("ORATS_TOKEN required")
    start=date(2024,1,1); end=date(2026,8,14); out=[]
    for threshold in [float(x) for x in a.thresholds.split(",")]:
        option_rows=[]; signal_count=0; failures=[]
        for ticker in TICKERS.split(","):
            try:
                bars,_=fetch_orats_history(ticker,start=start,end=end,token=token)
                rows=reclassify_gap_go(bars,indicators(bars),close_location=threshold)
                trades,_=run_strategy(bars,rows,version="2.4",start=start,end=end)
                gap=[t for t in trades if t.entry_type=="EARNINGS_GAP_GO"]
                signal_count += len(gap)
                option_rows.extend(optionize_trade(ticker,t,token) for t in gap)
            except (RuntimeError,ValueError) as exc:
                failures.append(f"{ticker}:{type(exc).__name__}")
        ok=[r for r in option_rows if r.get("status")=="OK"]
        vals=[float(r["option_return_pct"]) for r in ok]
        summary={"threshold":threshold,"gap_go_signals":signal_count,"qualified_option_trades":len(ok),
                 "no_qualified_option":sum(r.get("status")=="NO_QUALIFIED_OPTION" for r in option_rows),
                 "wins":sum(v>0 for v in vals),"win_rate_pct":round(100*sum(v>0 for v in vals)/len(vals),2) if vals else 0,
                 "avg_return_pct":round(statistics.mean(vals),2) if vals else None,
                 "median_return_pct":round(statistics.median(vals),2) if vals else None,
                 "sum_return_pct":round(sum(vals),2),"expired_before_signal_exit":sum(bool(r.get("expired_before_signal_exit")) for r in ok),
                 "failures":failures,"trades":option_rows}
        out.append(summary)
        print("GAP_GO_OPTION_BACKTEST",json.dumps({k:v for k,v in summary.items() if k!="trades"},sort_keys=True))
        for r in ok: print(json.dumps(r,sort_keys=True))
    if a.json_out:
        with open(a.json_out,"w",encoding="utf-8") as fh: json.dump(out,fh,indent=2,sort_keys=True)
    return 0

if __name__=="__main__": raise SystemExit(main())
