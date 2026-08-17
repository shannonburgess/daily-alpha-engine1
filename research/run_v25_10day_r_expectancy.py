"""Research-only R-expectancy comparison for v2.5 10D vs 20D breakout.

Uses canonical Daily Alpha R: initial two-unit risk from entry close to prior 10-day low.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from daily_alpha.backtest import fetch_orats_history, indicators
from research.run_v25_10day_breakout import HOLDOUT_SYMBOLS, PERIODS, run_variant

FETCH_START = date(2021,1,1)
FETCH_END = date(2026,7,31)
BREAKOUTS = (10,20)


def attach_r(trades, bars, ind):
    by_date = {b.trade_date.isoformat(): i for i,b in enumerate(bars)}
    out=[]
    for trade in trades:
        t=dict(trade)
        i=by_date.get(str(t['entry_date']))
        lower10 = ind[i]['lower10'] if i is not None else None
        initial_risk = max(float(t['entry_price']) - float(lower10), 0.0) if lower10 is not None else None
        risk_dollars = 2.0 * initial_risk if initial_risk and initial_risk > 0 else None
        t['initial_risk_per_unit'] = initial_risk
        t['r_multiple'] = float(t['realized_pnl']) / risk_dollars if risk_dollars else None
        out.append(t)
    return out


def summarize(trades):
    rs=[float(t['r_multiple']) for t in trades if t.get('r_multiple') is not None]
    wins=[r for r in rs if r>0]
    losses=[r for r in rs if r<=0]
    win_rate=len(wins)/len(rs) if rs else 0.0
    avg_win=sum(wins)/len(wins) if wins else 0.0
    avg_loss=abs(sum(losses)/len(losses)) if losses else 0.0
    expectancy=(win_rate*avg_win)-((1-win_rate)*avg_loss) if rs else 0.0
    # algebraically identical to mean R; include both as cross-check.
    mean_r=sum(rs)/len(rs) if rs else 0.0
    return {
        'trades_with_r':len(rs),
        'wins':len(wins),
        'win_rate_pct':win_rate*100.0,
        'avg_winner_r':avg_win,
        'avg_loser_r':avg_loss,
        'expectancy_r':expectancy,
        'mean_r':mean_r,
        'payoff_ratio_r':avg_win/avg_loss if avg_loss>0 else None,
        'best_r':max(rs) if rs else 0.0,
        'worst_r':min(rs) if rs else 0.0,
    }


def fetch_one(symbol, token):
    bars,_=fetch_orats_history(symbol,start=FETCH_START,end=FETCH_END,token=token)
    return symbol,bars,indicators(bars)


def main():
    token=os.environ.get('ORATS_TOKEN','').strip()
    if not token: raise SystemExit('ORATS_TOKEN missing')
    aggregated={p:{str(n):[] for n in BREAKOUTS} for p in PERIODS}
    errors={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs={pool.submit(fetch_one,s,token):s for s in HOLDOUT_SYMBOLS}
        for fut in as_completed(futs):
            symbol=futs[fut]
            try:
                _,bars,ind=fut.result()
                for p,(start,end) in PERIODS.items():
                    for n in BREAKOUTS:
                        result=run_variant(bars,ind,start=start,end=end,breakout_len=n)
                        aggregated[p][str(n)].extend(attach_r(result['trades'],bars,ind))
            except Exception as exc:
                errors[symbol]=f'{type(exc).__name__}:{exc}'

    summary={p:{str(n):summarize(aggregated[p][str(n)]) for n in BREAKOUTS} for p in PERIODS}
    combined={str(n):summarize([t for p in PERIODS for t in aggregated[p][str(n)]]) for n in BREAKOUTS}
    output={'definition':'1R = initial two-unit risk from entry close to prior 10-day low','symbols':len(HOLDOUT_SYMBOLS)-len(errors),'errors':errors,'periods':summary,'combined_2022_through_2026YTD':combined}
    Path('v25-10day-r-expectancy.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    lines=['# Daily Alpha 10D vs 20D — Win Rate and R Expectancy','',f"Valid symbols: {output['symbols']}; errors: {len(errors)}",'', '| Period | Breakout | Trades | Win rate | Avg winner R | Avg loser R | Payoff | Expectancy R/trade | Best R | Worst R |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for p in PERIODS:
        for n in BREAKOUTS:
            s=summary[p][str(n)]
            lines.append(f"| {p} | {n}D | {s['trades_with_r']} | {s['win_rate_pct']:.1f}% | {s['avg_winner_r']:.2f}R | {s['avg_loser_r']:.2f}R | {s['payoff_ratio_r']:.2f}x | {s['expectancy_r']:+.3f}R | {s['best_r']:.2f}R | {s['worst_r']:.2f}R |")
    lines += ['', '## Combined 2022 through 2026 YTD', '', '| Breakout | Trades | Win rate | Avg winner R | Avg loser R | Payoff | Expectancy R/trade |','|---|---:|---:|---:|---:|---:|---:|']
    for n in BREAKOUTS:
        s=combined[str(n)]
        lines.append(f"| {n}D | {s['trades_with_r']} | {s['win_rate_pct']:.1f}% | {s['avg_winner_r']:.2f}R | {s['avg_loser_r']:.2f}R | {s['payoff_ratio_r']:.2f}x | {s['expectancy_r']:+.3f}R |")
    Path('v25-10day-r-expectancy.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(Path('v25-10day-r-expectancy.md').read_text())

if __name__=='__main__': main()
