"""Daily Alpha R2 portfolio-scenario backtest.

R2 is the v2.4 Turtle signal engine. Portfolio sizing intentionally replaces
the Pine script's unit sizing so every scenario uses the same daily NAV ledger.
Options are excluded. Research/backtest use only; never routes trades.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .backtest import Bar, fetch_orats_history, indicators


DEFAULT_STOCKS = (
    "AAPL,MSFT,NVDA,AMD,AVGO,MU,QCOM,MRVL,ARM,INTC,AMZN,GOOGL,META,NFLX,"
    "CRM,NOW,ORCL,TSLA,DELL,ADBE,PANW,CRWD,PLTR,ANET,IBM,TSM,ASML,LRCX,"
    "AMAT,KLAC,GE,CAT,BA,JPM,GS,V,MA,WMT,COST,HD,LLY,UNH,ABBV,ISRG,XOM,"
    "CVX,COP,NKE,SBUX,UBER"
)

# Unlevered signal ETF -> (2x, 3x). Only products with usable history enter.
SECTOR_MAP = {
    "XLK": ("ROM", "TECL"),
    "SOXX": ("USD", "SOXL"),
    "XLF": ("UYG", "FAS"),
    "XLE": ("DIG", "ERX"),
    "XLV": ("RXL", "CURE"),
    "XLI": ("UXI", "DUSL"),
    "XLY": ("UCC", "WANT"),
    "XLU": ("UPW", "UTSL"),
}


@dataclass(frozen=True)
class Scenario:
    name: str
    stock_cap: float
    lev_cap: float
    use_sgov: bool
    allow_3x: bool
    throttle: bool


SCENARIOS = (
    Scenario("S0_SPY", 0.0, 0.0, False, False, False),
    Scenario("S1_R2_CORE", 0.70, 0.0, False, False, False),
    Scenario("S2_R2_SGOV", 0.70, 0.0, True, False, False),
    Scenario("S3_R2_2X_SGOV", 0.70, 0.15, True, False, False),
    Scenario("S4_R2_2X3X_SGOV", 0.70, 0.15, True, True, False),
    Scenario("S5_THROTTLED_HYBRID", 0.70, 0.15, True, True, True),
)


def r2_states(bars: list[Bar]) -> dict[date, bool]:
    """Return close-known v2.4 in/out states; orders apply next session."""
    rows = indicators(bars)
    active = False
    entry_level: float | None = None
    entry_i: int | None = None
    states: dict[date, bool] = {}
    for i, (bar, row) in enumerate(zip(bars, rows)):
        price_ok = bar.close >= 25.0
        eff_ok = row["efficiency"] is not None and float(row["efficiency"]) >= 0.20
        rsi_ok = row["rsi"] is not None and float(row["rsi"]) <= 80.0
        adx_ok = row["adx"] is not None and float(row["adx"]) >= 25.0
        normal = (
            not active and row["fresh_breakout"] and not row["is_earnings_up_gap"]
            and row["trend_state"] == 1 and row["normal_trend_mature"]
            and price_ok and eff_ok and rsi_ok and adx_ok
        )
        gap = (
            not active and row["gap_go"] and row["fresh_breakout"] and price_ok
        )
        if normal or gap:
            active = True
            entry_level = float(row["upper20"])
            entry_i = i

        age = i - entry_i if entry_i is not None else None
        failed = (
            active and entry_level is not None and age is not None
            and 1 <= age <= 3 and bar.close < entry_level
        )
        turtle = active and row["lower10"] is not None and bar.close < float(row["lower10"])
        trend = active and bool(row["bear_flip"])
        if failed or turtle or trend:
            active = False
            entry_level = None
            entry_i = None
        states[bar.trade_date] = active
    return states


def throttle_multiplier(drawdown: float) -> tuple[float, bool]:
    """Return stock budget multiplier and whether leverage remains enabled."""
    if drawdown > 0.15:
        return 0.0, False
    if drawdown > 0.12:
        return 0.25, False
    if drawdown > 0.08:
        return 0.50, False
    if drawdown > 0.05:
        return 0.75, True
    return 1.0, True


def metrics(nav: list[tuple[date, float]], exposure: list[float], turnover: float) -> dict[str, Any]:
    vals = [v for _, v in nav]
    daily = [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals)) if vals[i - 1] > 0]
    years = max((nav[-1][0] - nav[0][0]).days / 365.25, 1 / 252)
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1 if vals[0] > 0 else 0.0
    vol = pstdev(daily) * math.sqrt(252) if len(daily) > 1 else 0.0
    downside = [min(x, 0.0) for x in daily]
    downvol = math.sqrt(mean([x * x for x in downside])) * math.sqrt(252) if downside else 0.0
    peak = vals[0]
    max_dd = 0.0
    for value in vals:
        peak = max(peak, value)
        max_dd = max(max_dd, 1.0 - value / peak)
    rf = 0.0  # SGOV is modeled as an investable sleeve, not subtracted twice.
    return {
        "ending_nav": round(vals[-1], 2),
        "total_return_pct": round((vals[-1] / vals[0] - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "annual_vol_pct": round(vol * 100, 2),
        "sharpe": round((cagr - rf) / vol, 2) if vol else None,
        "sortino": round((cagr - rf) / downvol, 2) if downvol else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(cagr / max_dd, 2) if max_dd else None,
        "avg_effective_exposure_pct": round(mean(exposure) * 100, 2) if exposure else 0.0,
        "peak_effective_exposure_pct": round(max(exposure) * 100, 2) if exposure else 0.0,
        "turnover_x_nav": round(turnover / vals[0], 2),
    }


def simulate(
    scenario: Scenario,
    bars: dict[str, dict[date, Bar]],
    states: dict[str, dict[date, bool]],
    dates: list[date],
    stocks: list[str],
    initial_nav: float,
) -> tuple[list[tuple[date, float]], dict[str, Any]]:
    if scenario.name == "S0_SPY":
        first = bars["SPY"][dates[0]].close
        nav = [(d, initial_nav * bars["SPY"][d].close / first) for d in dates]
        return nav, metrics(nav, [1.0] * len(nav), 0.0)

    cash = initial_nav
    shares: dict[str, float] = {}
    nav: list[tuple[date, float]] = []
    exposures: list[float] = []
    turnover = 0.0
    peak = initial_nav

    for idx, d in enumerate(dates):
        # Decisions are lagged one complete session; trades execute at today's open.
        signal_date = dates[idx - 1] if idx else None
        pre_nav = cash + sum(q * bars[t][d].open for t, q in shares.items())
        peak = max(peak, pre_nav)
        dd = 1.0 - pre_nav / peak if peak else 0.0
        mult, lev_enabled = throttle_multiplier(dd) if scenario.throttle else (1.0, True)

        active_stocks = [t for t in stocks if signal_date and states[t].get(signal_date, False)]
        stock_budget = scenario.stock_cap * mult
        each_stock = min(0.075, stock_budget / len(active_stocks)) if active_stocks else 0.0
        targets = {t: each_stock for t in active_stocks}

        active_sectors = [
            t for t, pair in SECTOR_MAP.items()
            if signal_date and states[t].get(signal_date, False)
            and pair[0] in bars and (not scenario.allow_3x or pair[1] in bars)
        ]
        if scenario.lev_cap and lev_enabled and active_sectors:
            two_budget = scenario.lev_cap - (0.05 if scenario.allow_3x else 0.0)
            for base in active_sectors:
                two, three = SECTOR_MAP[base]
                targets[two] = targets.get(two, 0.0) + two_budget / len(active_sectors)
                if scenario.allow_3x:
                    targets[three] = targets.get(three, 0.0) + 0.05 / len(active_sectors)

        invested = sum(targets.values())
        reserve = max(0.0, 1.0 - invested)
        if scenario.use_sgov:
            targets["SGOV"] = reserve

        # Rebalance only changed targets; costs model estimated implementation shortfall.
        all_tickers = set(shares) | set(targets)
        for ticker in sorted(all_tickers):
            px = bars[ticker][d].open
            current_value = shares.get(ticker, 0.0) * px
            target_value = pre_nav * targets.get(ticker, 0.0)
            trade_value = target_value - current_value
            if abs(trade_value) < 1e-8:
                continue
            cost_bps = 3.0 if ticker in {x for pair in SECTOR_MAP.values() for x in pair[1:]} else 2.0 if ticker in {x for pair in SECTOR_MAP.values() for x in pair[:1]} else 1.0
            cost = abs(trade_value) * cost_bps / 10_000.0
            cash -= trade_value + cost
            turnover += abs(trade_value)
            shares[ticker] = target_value / px
            if abs(shares[ticker]) < 1e-12:
                shares.pop(ticker, None)

        close_nav = cash + sum(q * bars[t][d].close for t, q in shares.items())
        effective = sum(targets.get(t, 0.0) * (3 if t in {p[1] for p in SECTOR_MAP.values()} else 2 if t in {p[0] for p in SECTOR_MAP.values()} else 1) for t in targets if t != "SGOV")
        exposures.append(effective)
        nav.append((d, close_nav))
        peak = max(peak, close_nav)
    return nav, metrics(nav, exposures, turnover)


def run(args: argparse.Namespace) -> dict[str, Any]:
    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    stocks = [x.strip().upper() for x in args.stocks.split(",") if x.strip()]
    required = sorted(set(stocks) | set(SECTOR_MAP) | {x for pair in SECTOR_MAP.values() for x in pair} | {"SPY", "SGOV"})

    raw: dict[str, list[Bar]] = {}
    failures: dict[str, str] = {}
    def fetch(t: str) -> tuple[str, list[Bar]]:
        series, _ = fetch_orats_history(t, start=start, end=end, token=token)
        return t, series
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, t): t for t in required}
        for future in as_completed(futures):
            t = futures[future]
            try:
                _, raw[t] = future.result()
            except RuntimeError as exc:  # keep complete failure evidence
                failures[t] = f"{type(exc).__name__}: {exc}"
    essential = set(SECTOR_MAP) | {"SPY", "SGOV"}
    missing = sorted(essential - set(raw))
    if missing:
        raise RuntimeError(f"Missing essential history: {missing}; failures={failures}")
    stocks = [t for t in stocks if t in raw]
    if len(stocks) < 40:
        raise RuntimeError(f"Only {len(stocks)} of 50 stock histories available; failures={failures}")

    common = set.intersection(*({b.trade_date for b in raw[t]} for t in essential | set(stocks)))
    dates = sorted(d for d in common if start <= d <= end)
    if len(dates) < 252:
        raise RuntimeError(f"Only {len(dates)} common trading dates")
    by_date = {t: {b.trade_date: b for b in series} for t, series in raw.items()}
    states = {t: r2_states(raw[t]) for t in set(stocks) | set(SECTOR_MAP)}

    results: dict[str, Any] = {}
    curves: dict[str, list[dict[str, Any]]] = {}
    for scenario in SCENARIOS:
        curve, summary = simulate(scenario, by_date, states, dates, stocks, args.initial_nav)
        results[scenario.name] = summary
        curves[scenario.name] = [{"date": d.isoformat(), "nav": round(v, 2)} for d, v in curve]
    return {
        "performance_basis": "BACKTEST",
        "strategy": "R2_DAILY_ALPHA_V2_4_TURTLE_SHARES",
        "options_included": False,
        "start": start.isoformat(), "end": end.isoformat(),
        "initial_nav": args.initial_nav, "stock_count": len(stocks),
        "assumptions": {"stock_cap": 0.70, "single_stock_cap": 0.075, "leveraged_cap": 0.15, "three_x_cap": 0.05, "execution": "NEXT_SESSION_OPEN"},
        "data_failures_nonessential": failures,
        "results": results, "curves": curves,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--stocks", default=DEFAULT_STOCKS)
    parser.add_argument("--initial-nav", type=float, default=1_000_000.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--json-out", default="scenario-backtest.json")
    args = parser.parse_args()
    result = run(args)
    Path(args.json_out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("DAILY ALPHA UNIFIED R2 SCENARIO BACKTEST")
    for name, row in result["results"].items():
        print(f"{name}: CAGR={row['cagr_pct']}% DD={row['max_drawdown_pct']}% Sharpe={row['sharpe']} End=${row['ending_nav']:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
