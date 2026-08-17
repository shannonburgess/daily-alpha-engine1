"""Research-only full-portfolio backtest for the R2 long-runner architecture.

Compares:
A) R2 stock shares + Treasury reserve
B) A + risk-normalized 2x/3x sector proxy sleeve
C) B + drawdown-based new-risk throttling
D) C + dynamic synthetic SPY beta hedge

No broker, Lambda, paper-ledger, or live-trading mutation.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import statistics
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from daily_alpha.backtest import fetch_orats_history, indicators

START = date(2022, 1, 1)
END = date(2026, 7, 31)
FETCH_START = date(2021, 1, 1)
INITIAL_NAV = 1_250_000.0
SGOV_FEE = 0.0009  # 0.09% annual fee proxy

# Broad liquid research universe used in the R2 studies.
STOCK_SECTORS = {
    # Semiconductors
    "NVDA":"SEMIS","AVGO":"SEMIS","AMD":"SEMIS","QCOM":"SEMIS","TXN":"SEMIS","AMAT":"SEMIS","KLAC":"SEMIS",
    # Technology / software
    "AAPL":"TECH","MSFT":"TECH","CRM":"TECH","NOW":"TECH","ORCL":"TECH","IBM":"TECH","CSCO":"TECH","PANW":"TECH",
    # Communication / internet
    "META":"COMM","GOOGL":"COMM","NFLX":"COMM",
    # Financials
    "JPM":"FIN","BAC":"FIN","WFC":"FIN","GS":"FIN","MS":"FIN","AXP":"FIN","SCHW":"FIN",
    # Health
    "UNH":"HEALTH","LLY":"HEALTH","ABBV":"HEALTH","TMO":"HEALTH","DHR":"HEALTH","ISRG":"HEALTH","AMGN":"HEALTH",
    # Industrials
    "CAT":"IND","DE":"IND","GE":"IND","RTX":"IND","HON":"IND","ETN":"IND","EMR":"IND","PWR":"IND",
    # Energy
    "XOM":"ENERGY","CVX":"ENERGY","COP":"ENERGY","EOG":"ENERGY","SLB":"ENERGY","MPC":"ENERGY",
    # Consumer
    "WMT":"CONS","COST":"CONS","HD":"CONS","LOW":"CONS","MCD":"CONS","BKNG":"CONS","TSLA":"CONS",
    # Real estate
    "AMT":"REAL","PLD":"REAL","EQIX":"REAL",
    # Materials
    "LIN":"MAT","FCX":"MAT",
    # Utilities
    "NEE":"UTIL",
}

# Signal proxy -> execution vehicles. If a ticker lacks history, that lane is skipped.
SECTOR_VEHICLES = {
    "SEMIS": {"proxy":"SOXX", "lev2":"USD", "lev3":"SOXL"},
    "TECH": {"proxy":"XLK", "lev2":"ROM", "lev3":"TECL"},
    "COMM": {"proxy":"XLC", "lev2":"LTL", "lev3":None},
    "FIN": {"proxy":"XLF", "lev2":"UYG", "lev3":"FAS"},
    "HEALTH": {"proxy":"XLV", "lev2":"RXL", "lev3":"CURE"},
    "IND": {"proxy":"XLI", "lev2":"UXI", "lev3":"DUSL"},
    "ENERGY": {"proxy":"XLE", "lev2":"ERX", "lev3":None},
    "CONS": {"proxy":"XLY", "lev2":"UCC", "lev3":"WANT"},
    "REAL": {"proxy":"XLRE", "lev2":"URE", "lev3":"DRN"},
    "MAT": {"proxy":"XLB", "lev2":"UYM", "lev3":"MATL"},
    "UTIL": {"proxy":"XLU", "lev2":"UPW", "lev3":None},
}

ALL_FETCH = sorted(set(STOCK_SECTORS) | {"SPY"} | {x for v in SECTOR_VEHICLES.values() for x in v.values() if x})

@dataclass
class Position:
    symbol: str
    kind: str  # STOCK / LEV2 / LEV3
    sector: str
    qty: float
    unit_qty: float
    avg: float
    entry: float
    risk_dist: float
    atr0: float
    added1: bool = False
    added2: bool = False


def prior_high(bars, i, n):
    return max(x.high for x in bars[i-n:i]) if i >= n else None


def prior_low(bars, i, n):
    return min(x.low for x in bars[i-n:i]) if i >= n else None


def fresh_breakout(bars, i, n):
    u = prior_high(bars, i, n)
    if u is None:
        return False
    prev = False
    if i >= n + 1:
        prev_u = max(x.high for x in bars[i-n-1:i-1])
        prev = bars[i-1].close > prev_u
    return bars[i].close > u and not prev


def close_location(bar):
    return (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else 0.5


def relvol(bars, i, n=20):
    if i < n:
        return 0.0
    avg = sum(x.volume for x in bars[i-n:i]) / n
    return bars[i].volume / avg if avg > 0 else 0.0


def normal_r2_signal(bars, ind, i, *, close_min=0.65, adx_min=17.0):
    bar = bars[i]
    r = ind[i]
    if not fresh_breakout(bars, i, 20):
        return False
    if bool(r.get("is_earnings_up_gap")):
        return False
    if int(r.get("trend_state") or 0) != 1:
        return False
    if i < 2 or int(ind[i-1].get("trend_state") or 0) != 1 or int(ind[i-2].get("trend_state") or 0) != 1:
        return False
    adx = r.get("adx")
    prev_adx = ind[i-1].get("adx") if i > 0 else None
    eff = r.get("efficiency")
    rsi = r.get("rsi")
    if None in (adx, prev_adx, eff, rsi):
        return False
    if float(adx) < adx_min or float(adx) <= float(prev_adx):
        return False
    if float(eff) < 0.20 or float(rsi) > 80 or bar.close < 25:
        return False
    if close_location(bar) < close_min:
        return False
    return True


def gap_go_signal(bars, ind, i):
    r = ind[i]
    return bool(r.get("gap_go")) and bool(r.get("fresh_breakout")) and bars[i].close >= 25


def sector_signal(bars, ind, i):
    # Base sector qualification from unlevered sector ETF.
    if not normal_r2_signal(bars, ind, i, close_min=0.65, adx_min=17.0):
        return None
    r = ind[i]
    strong = float(r["adx"]) >= 20 and relvol(bars, i) >= 1.20 and close_location(bars[i]) >= 0.75
    return "LEV3" if strong else "LEV2"


def fetch_one(symbol, token):
    bars, meta = fetch_orats_history(symbol, start=FETCH_START, end=END, token=token)
    return symbol, bars, indicators(bars), meta


def get_tbill_daily_rates():
    """Fetch DGS3MO from FRED and convert annual percent yield to daily decimal.

    Used as an SGOV-like Treasury reserve carry proxy, net of SGOV fee. Missing days
    forward-fill the last available observation. If unavailable, reserve carry is 0.
    """
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            text = resp.read().decode("utf-8")
        rows = csv.DictReader(io.StringIO(text))
        obs = {}
        for row in rows:
            val = row.get("DGS3MO")
            if not val or val == ".":
                continue
            d = datetime.strptime(row["observation_date"], "%Y-%m-%d").date()
            obs[d] = max(float(val) / 100.0 - SGOV_FEE, 0.0) / 252.0
        return obs, "FRED_DGS3MO_NET_SGOV_FEE"
    except Exception as exc:
        return {}, f"ZERO_CARRY_FALLBACK:{type(exc).__name__}"


def metrics(dates, navs, rf_daily):
    rets = []
    excess = []
    peak = navs[0]
    max_dd = 0.0
    dd_start = None
    max_recovery = 0
    underwater_start = None
    months = defaultdict(lambda: [None, None])
    for i in range(1, len(navs)):
        r = navs[i] / navs[i-1] - 1.0
        rets.append(r)
        excess.append(r - rf_daily.get(dates[i], 0.0))
        if navs[i] > peak:
            peak = navs[i]
            if underwater_start is not None:
                max_recovery = max(max_recovery, (dates[i] - underwater_start).days)
                underwater_start = None
        else:
            if underwater_start is None:
                underwater_start = dates[i]
        dd = navs[i] / peak - 1.0
        if dd < max_dd:
            max_dd = dd
            dd_start = dates[i]
        key = (dates[i].year, dates[i].month)
        if months[key][0] is None:
            months[key][0] = navs[i-1]
        months[key][1] = navs[i]
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    cagr = (navs[-1] / navs[0]) ** (1 / years) - 1
    vol = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    ex_mean = statistics.mean(excess) * 252 if excess else 0.0
    ex_vol = statistics.pstdev(excess) * math.sqrt(252) if len(excess) > 1 else 0.0
    sharpe = ex_mean / ex_vol if ex_vol > 0 else None
    downside = [min(x, 0.0) for x in excess]
    dvol = math.sqrt(statistics.mean([x*x for x in downside])) * math.sqrt(252) if downside else 0.0
    sortino = ex_mean / dvol if dvol > 0 else None
    calmar = cagr / abs(max_dd) if max_dd < 0 else None
    month_rets = [(end/start - 1) for start, end in months.values() if start and end]
    return {
        "ending_nav": navs[-1],
        "cagr_pct": cagr*100,
        "ann_vol_pct": vol*100,
        "sharpe_excess_tbill": sharpe,
        "sortino_excess_tbill": sortino,
        "max_drawdown_pct": max_dd*100,
        "calmar": calmar,
        "worst_month_pct": min(month_rets)*100 if month_rets else 0.0,
        "max_recovery_days": max_recovery,
        "max_dd_date": dd_start.isoformat() if dd_start else None,
    }


def run_portfolio(data, rf_daily, *, sector_sleeve, throttle, beta_hedge, sector_exit_days=10):
    # Align to SPY dates; only dates with SPY history are portfolio dates.
    spy_bars, spy_ind, _ = data["SPY"]
    dates = [b.trade_date for b in spy_bars if START <= b.trade_date <= END]
    by_symbol = {}
    idx_by_symbol = {}
    for s, (bars, ind, meta) in data.items():
        by_symbol[s] = {b.trade_date: (b, ind[i], i) for i, b in enumerate(bars)}
        idx_by_symbol[s] = (bars, ind)

    nav = INITIAL_NAV
    cash = INITIAL_NAV
    positions: dict[str, Position] = {}
    navs = [nav]
    out_dates = [dates[0]]
    peak = nav
    prior_prices = {}
    hedge_weight = 0.0
    stats = defaultdict(int)

    for di, d in enumerate(dates):
        if di == 0:
            for s in by_symbol:
                if d in by_symbol[s]:
                    prior_prices[s] = by_symbol[s][d][0].close
            continue

        # Treasury reserve carry on idle cash (SGOV-like reserve proxy).
        cash *= 1.0 + rf_daily.get(d, 0.0)

        # Mark risky positions to market.
        for s, p in list(positions.items()):
            row = by_symbol.get(s, {}).get(d)
            if not row:
                continue
            px = row[0].close
            prev = prior_prices.get(s, px)
            cash += p.qty * (px - prev)
            prior_prices[s] = px

        # Synthetic SPY beta hedge overlay. Hedge notional is set from prior-day drawdown.
        spy_row = by_symbol["SPY"].get(d)
        if spy_row:
            spy_px = spy_row[0].close
            spy_prev = prior_prices.get("SPY", spy_px)
            if beta_hedge and spy_prev > 0 and hedge_weight > 0:
                cash += -hedge_weight * nav * (spy_px / spy_prev - 1.0)
            prior_prices["SPY"] = spy_px

        # Current NAV equals cash plus current market value notionally already embedded via MTM.
        nav = cash
        for p in positions.values():
            row = by_symbol.get(p.symbol, {}).get(d)
            if row:
                nav += p.qty * row[0].close
                cash -= p.qty * row[0].close
        # Rebase cash after computing NAV: actual cash is NAV minus marked market values.
        mv = sum(p.qty * by_symbol[p.symbol][d][0].close for p in positions.values() if d in by_symbol.get(p.symbol, {}))
        cash = nav - mv
        peak = max(peak, nav)
        dd = nav / peak - 1.0

        risk_mult = 1.0
        if throttle:
            if dd <= -0.12: risk_mult = 0.25
            elif dd <= -0.08: risk_mult = 0.50
            elif dd <= -0.05: risk_mult = 0.75
        if beta_hedge:
            if dd <= -0.12: hedge_weight = 0.60
            elif dd <= -0.08: hedge_weight = 0.40
            elif dd <= -0.05: hedge_weight = 0.20
            else: hedge_weight = 0.0

        # Exit and add logic.
        for s, p in list(positions.items()):
            row = by_symbol.get(s, {}).get(d)
            if not row:
                continue
            bar, r, i = row
            bars, ind = idx_by_symbol[s]
            exit_n = 55 if p.kind == "STOCK" else sector_exit_days
            low_exit = prior_low(bars, i, exit_n)
            hard = bar.close <= p.entry - 0.75 * p.risk_dist
            trend_exit = low_exit is not None and bar.close < low_exit
            if hard or trend_exit:
                cash += p.qty * bar.close
                stats[f"exit_{p.kind}"] += 1
                del positions[s]
                continue
            adx = r.get("adx")
            trend_ok = int(r.get("trend_state") or 0) == 1 and adx is not None and float(adx) >= 17
            if p.kind == "STOCK" and trend_ok:
                if not p.added1 and bar.close >= p.entry + p.atr0:
                    cost = p.unit_qty * bar.close
                    if cash >= cost:
                        cash -= cost
                        p.avg = (p.avg*p.qty + bar.close*p.unit_qty) / (p.qty+p.unit_qty)
                        p.qty += p.unit_qty
                        p.added1 = True
                        stats["stock_add1"] += 1
                elif p.added1 and not p.added2 and bar.close >= p.entry + 2*p.atr0:
                    cost = p.unit_qty * bar.close
                    if cash >= cost:
                        cash -= cost
                        p.avg = (p.avg*p.qty + bar.close*p.unit_qty) / (p.qty+p.unit_qty)
                        p.qty += p.unit_qty
                        p.added2 = True
                        stats["stock_add2"] += 1

        # Determine stock entry candidates first.
        stock_candidates = []
        sectors_with_stock_entry = set()
        sectors_with_open_stock = {p.sector for p in positions.values() if p.kind == "STOCK"}
        for s, sector in STOCK_SECTORS.items():
            if s in positions or s not in by_symbol or d not in by_symbol[s]:
                continue
            bar, r, i = by_symbol[s][d]
            bars, ind = idx_by_symbol[s]
            if normal_r2_signal(bars, ind, i) or gap_go_signal(bars, ind, i):
                l10 = prior_low(bars, i, 10)
                atr = r.get("atr")
                if l10 is None or atr is None or bar.close <= l10:
                    continue
                risk_dist = bar.close - l10
                score = float(r.get("adx") or 0) + 50*float(r.get("efficiency") or 0)
                stock_candidates.append((score, s, sector, bar.close, risk_dist, float(atr)))
                sectors_with_stock_entry.add(sector)
        stock_candidates.sort(reverse=True)

        # Open highest-quality stock entries subject to cash and 0.50% initial-risk budget.
        for _, s, sector, px, risk_dist, atr in stock_candidates:
            risk_budget = nav * 0.005 * risk_mult
            unit_qty = (risk_budget / 2.0) / risk_dist
            # 15% NAV initial notional cap per stock.
            unit_qty = min(unit_qty, (0.15*nav/2.0) / px)
            qty = 2*unit_qty
            cost = qty*px
            if qty <= 0 or cash < cost:
                continue
            cash -= cost
            positions[s] = Position(s, "STOCK", sector, qty, unit_qty, px, px, risk_dist, atr)
            prior_prices[s] = px
            stats["entry_STOCK"] += 1

        # Sector proxy sleeve only when the sector has no qualifying/open stock exposure.
        if sector_sleeve:
            sectors_with_open_stock = {p.sector for p in positions.values() if p.kind == "STOCK"}
            sectors_with_open_lev = {p.sector for p in positions.values() if p.kind in ("LEV2","LEV3")}
            for sector, spec in SECTOR_VEHICLES.items():
                if sector in sectors_with_stock_entry or sector in sectors_with_open_stock or sector in sectors_with_open_lev:
                    continue
                proxy = spec["proxy"]
                if proxy not in by_symbol or d not in by_symbol[proxy]:
                    continue
                pbar, pr, pi = by_symbol[proxy][d]
                pbars, pind = idx_by_symbol[proxy]
                lane = sector_signal(pbars, pind, pi)
                if not lane:
                    continue
                exec_symbol = spec["lev3"] if lane == "LEV3" and spec.get("lev3") in by_symbol else spec.get("lev2")
                if not exec_symbol or exec_symbol not in by_symbol or d not in by_symbol[exec_symbol] or exec_symbol in positions:
                    continue
                ebar, er, ei = by_symbol[exec_symbol][d]
                ebars, eind = idx_by_symbol[exec_symbol]
                l10 = prior_low(ebars, ei, 10)
                atr = er.get("atr")
                if l10 is None or atr is None or ebar.close <= l10:
                    continue
                risk_dist = ebar.close - l10
                risk_pct = 0.0025 if lane == "LEV3" else 0.0035
                risk_budget = nav * risk_pct * risk_mult
                qty = risk_budget / risk_dist
                # Cap leveraged ETF initial notional: 10% NAV (3x), 12.5% NAV (2x).
                cap = (0.10 if lane == "LEV3" else 0.125) * nav
                qty = min(qty, cap / ebar.close)
                cost = qty * ebar.close
                if qty <= 0 or cash < cost:
                    continue
                cash -= cost
                positions[exec_symbol] = Position(exec_symbol, lane, sector, qty, qty, ebar.close, ebar.close, risk_dist, float(atr))
                prior_prices[exec_symbol] = ebar.close
                stats[f"entry_{lane}"] += 1

        # End-of-day NAV.
        mv = sum(p.qty * by_symbol[p.symbol][d][0].close for p in positions.values() if d in by_symbol.get(p.symbol, {}))
        nav = cash + mv
        navs.append(nav)
        out_dates.append(d)

    return out_dates, navs, dict(stats)


def main():
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN missing")
    data = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(fetch_one, s, token): s for s in ALL_FETCH}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                sym, bars, ind, meta = fut.result()
                data[sym] = (bars, ind, meta)
            except Exception as exc:
                errors[s] = f"{type(exc).__name__}:{exc}"
    if "SPY" not in data:
        raise SystemExit("SPY history unavailable")

    rf_daily, rf_source = get_tbill_daily_rates()

    variants = {
        "A_R2_STOCKS_SGOV": dict(sector_sleeve=False, throttle=False, beta_hedge=False),
        "B_R2_PLUS_2X3X_SECTOR_SGOV": dict(sector_sleeve=True, throttle=False, beta_hedge=False),
        "C_B_PLUS_DRAWDOWN_THROTTLE": dict(sector_sleeve=True, throttle=True, beta_hedge=False),
        "D_FULL_WITH_SPY_BETA_HEDGE": dict(sector_sleeve=True, throttle=True, beta_hedge=True),
    }
    results = {}
    for name, kwargs in variants.items():
        dates, navs, stats = run_portfolio(data, rf_daily, **kwargs)
        results[name] = {"metrics": metrics(dates, navs, rf_daily), "trade_stats": stats}

    out = {
        "research_only": True,
        "period": [START.isoformat(), END.isoformat()],
        "initial_nav": INITIAL_NAV,
        "cash_reserve_proxy": rf_source,
        "stock_risk_pct": 0.50,
        "lev2_risk_pct": 0.35,
        "lev3_risk_pct": 0.25,
        "sector_exit_days": 10,
        "r2_rules": "20D breakout + ADX>=17 rising + eff>=0.20 + RSI<=80 + close location>=0.65 + 55D exit + 0.75R hard close cap + +1/+2ATR adds",
        "sector_rules": "unlevered sector proxy must qualify; exceptional ADX>=20 rising + relvol>=1.2 + close location>=0.75 selects 3x when available, otherwise 2x; no stock setup/open exposure in sector",
        "drawdown_throttle": {"<5%":1.0,"5-8%":0.75,"8-12%":0.50,">=12%":0.25},
        "beta_hedge_notional": {"<5%":0.0,"5-8%":0.20,"8-12%":0.40,">=12%":0.60},
        "valid_symbols": len(data),
        "data_errors": errors,
        "variants": results,
    }
    Path("r2-portfolio-defense.json").write_text(json.dumps(out, indent=2))

    lines = [
        "# Daily Alpha R2 Full Portfolio Defense Backtest",
        "",
        f"Period: {START} to {END}; valid histories: {len(data)}; errors: {len(errors)}; reserve: {rf_source}.",
        "",
        "| Variant | CAGR | Vol | Sharpe | Sortino | Max DD | Calmar | Worst month | Ending NAV |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, payload in results.items():
        m = payload["metrics"]
        lines.append(
            f"| {name} | {m['cagr_pct']:.2f}% | {m['ann_vol_pct']:.2f}% | {m['sharpe_excess_tbill']:.2f} | {m['sortino_excess_tbill']:.2f} | {m['max_drawdown_pct']:.2f}% | {m['calmar']:.2f} | {m['worst_month_pct']:.2f}% | ${m['ending_nav']:,.0f} |"
        )
    lines += ["", "## Trade counts"]
    for name, payload in results.items():
        lines.append(f"- **{name}**: {payload['trade_stats']}")
    if errors:
        lines += ["", "## Data errors", "```json", json.dumps(errors, indent=2), "```"]
    Path("r2-portfolio-defense.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
