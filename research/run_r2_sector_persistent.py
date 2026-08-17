"""Research-only persistent-sector sleeve test layered on the R2 stock portfolio.

Uses the same stock/share model and Treasury reserve as run_r2_portfolio_defense.py,
but allows a sector proxy that is already in a persistent bullish trend to trigger a
risk-normalized 2x/3x ETF when no stock setup/open stock exists in that sector.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_PATH = Path(__file__).with_name("run_r2_portfolio_defense.py")
spec = importlib.util.spec_from_file_location("r2def", BASE_PATH)
r2 = importlib.util.module_from_spec(spec)
sys.modules["r2def"] = r2
spec.loader.exec_module(r2)


def persistent_sector_signal(bars, ind, i):
    if i < 20:
        return None
    r = ind[i]
    adx = r.get("adx")
    prev_adx = ind[i-1].get("adx")
    eff = r.get("efficiency")
    rsi = r.get("rsi")
    if None in (adx, prev_adx, eff, rsi):
        return None
    if int(r.get("trend_state") or 0) != 1:
        return None
    if int(ind[i-1].get("trend_state") or 0) != 1 or int(ind[i-2].get("trend_state") or 0) != 1:
        return None
    if float(adx) < 17 or float(adx) <= float(prev_adx) or float(eff) < 0.20 or float(rsi) > 80:
        return None
    sma20 = sum(x.close for x in bars[i-20:i]) / 20
    if bars[i].close <= sma20:
        return None
    strong = (
        float(adx) >= 22
        and r2.relvol(bars, i) >= 1.20
        and r2.close_location(bars[i]) >= 0.70
    )
    return "LEV3" if strong else "LEV2"


def main():
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN missing")
    data = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(r2.fetch_one, s, token): s for s in r2.ALL_FETCH}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                sym, bars, ind, meta = fut.result()
                data[sym] = (bars, ind, meta)
            except Exception as exc:
                errors[s] = f"{type(exc).__name__}:{exc}"
    if "SPY" not in data:
        raise SystemExit("SPY history unavailable")

    rf_daily, rf_source = r2.get_tbill_daily_rates()
    r2.sector_signal = persistent_sector_signal

    results = {}
    d0, n0, s0 = r2.run_portfolio(data, rf_daily, sector_sleeve=False, throttle=False, beta_hedge=False)
    results["STOCK_ONLY"] = {"metrics": r2.metrics(d0, n0, rf_daily), "stats": s0}
    for exit_days in (5, 10, 20):
        d, n, st = r2.run_portfolio(
            data, rf_daily,
            sector_sleeve=True,
            throttle=False,
            beta_hedge=False,
            sector_exit_days=exit_days,
        )
        results[f"SECTOR_2X3X_EXIT_{exit_days}D"] = {"metrics": r2.metrics(d, n, rf_daily), "stats": st}

    out = {
        "research_only": True,
        "reserve": rf_source,
        "persistent_sector_rule": "bullish 3-bar trend + ADX>=17 rising + efficiency>=0.20 + RSI<=80 + close>SMA20; 3x requires ADX>=22, relative volume>=1.2, close-location>=0.70; otherwise 2x",
        "results": results,
        "errors": errors,
    }
    Path("r2-sector-persistent.json").write_text(json.dumps(out, indent=2))

    lines = [
        "# Daily Alpha Persistent Sector 2x/3x Sleeve",
        "",
        f"Reserve: {rf_source}; histories: {len(data)}; errors: {len(errors)}.",
        "",
        "| Variant | CAGR | Sharpe | Sortino | Max DD | Calmar | Worst month | Ending NAV | 2x entries | 3x entries |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, p in results.items():
        m, st = p["metrics"], p["stats"]
        lines.append(
            f"| {name} | {m['cagr_pct']:.2f}% | {m['sharpe_excess_tbill']:.2f} | {m['sortino_excess_tbill']:.2f} | {m['max_drawdown_pct']:.2f}% | {m['calmar']:.2f} | {m['worst_month_pct']:.2f}% | ${m['ending_nav']:,.0f} | {st.get('entry_LEV2',0)} | {st.get('entry_LEV3',0)} |"
        )
    Path("r2-sector-persistent.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
