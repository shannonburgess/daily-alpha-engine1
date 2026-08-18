"""Research-only Daily Alpha R2 downside-overlay portfolio backtest.

This study freezes the current R2 Long-Runner alpha hypothesis and changes only
portfolio-level defensive overlays. It is intentionally disconnected from paper
and live execution.

Phase 1 tests:
- R2 core with idle cash
- R2 + SGOV treasury reserve
- R2 + monotonic drawdown de-risking + SGOV
- R2 + dynamic SPY beta hedge + SGOV
- R2 + drawdown de-risking + dynamic beta hedge + SGOV

Index-option tail hedges are deliberately excluded from this first run because a
credible test requires timestamp-aligned executable option quotes, explicit roll
costs, and stale/locked/crossed quote handling.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from daily_alpha.backtest import Bar, fetch_orats_history, indicators

SYMBOLS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN",
    "AMAT","KLAC","CRM","NOW","ORCL","IBM","CSCO","PANW","JPM","BAC","WFC",
    "GS","MS","AXP","SCHW","UNH","LLY","ABBV","TMO","DHR","ISRG","AMGN",
    "CAT","DE","GE","RTX","HON","ETN","EMR","PWR","XOM","CVX","COP","EOG",
    "SLB","MPC","WMT","COST","HD","LOW","MCD","BKNG","TSLA","NFLX","NEE",
    "AMT","PLD","EQIX","LIN","FCX",
]
REFERENCES = ["SPY", "SGOV"]
START = date(2022, 1, 1)
END = date(2026, 7, 31)
INITIAL_NAV = 1_000_000.0
RISK_PER_TRADE = 0.005
MAX_SYMBOL_WEIGHT = 0.10
MAX_ALPHA_GROSS = 0.90
OPERATIONAL_CASH_BUFFER = 0.02
COST_BPS = {"ALPHA": 1.5, "SGOV": 0.5, "HEDGE": 1.0}


@dataclass(frozen=True)
class SignalState:
    active: bool
    entry: float | None = None
    hard_stop: float | None = None
    units: float = 0.0


@dataclass(frozen=True)
class Scenario:
    name: str
    use_sgov: bool
    drawdown_throttle: bool
    beta_hedge: bool


SCENARIOS = [
    Scenario("R2_CORE_CASH", False, False, False),
    Scenario("R2_SGOV", True, False, False),
    Scenario("R2_DRAWDOWN_SGOV", True, True, False),
    Scenario("R2_BETA_HEDGE_SGOV", True, False, True),
    Scenario("R2_FULL_DEFENSE_PHASE1", True, True, True),
]


def prior_low(bars: list[Bar], i: int, n: int) -> float | None:
    if i < n:
        return None
    return min(x.low for x in bars[i - n : i])


def build_r2_states(bars: list[Bar]) -> dict[date, SignalState]:
    """Freeze the current research R2 Long-Runner hypothesis."""
    rows = indicators(bars)
    out: dict[date, SignalState] = {}
    active = False
    entry: float | None = None
    initial_atr: float | None = None
    hard_stop: float | None = None
    units = 0.0
    add1 = False
    add2 = False
    add1_i: int | None = None

    for i, (bar, row) in enumerate(zip(bars, rows)):
        l10 = prior_low(bars, i, 10)
        l55 = prior_low(bars, i, 55)
        atr = float(row["atr"]) if row.get("atr") is not None else None
        adx = float(row["adx"]) if row.get("adx") is not None else None
        eff = float(row["efficiency"]) if row.get("efficiency") is not None else None
        rsi = float(row["rsi"]) if row.get("rsi") is not None else None
        close_loc = (
            (bar.close - bar.low) / (bar.high - bar.low)
            if bar.high > bar.low
            else 0.5
        )
        adx_rising = (
            adx is not None
            and adx >= 17.0
            and i > 0
            and rows[i - 1].get("adx") is not None
            and adx > float(rows[i - 1]["adx"])
        )
        trend_mature = (
            i >= 2
            and int(rows[i - 1]["trend_state"]) == 1
            and int(rows[i - 2]["trend_state"]) == 1
        )
        fresh20 = bool(row.get("fresh_breakout"))
        normal_entry = (
            not active
            and fresh20
            and not bool(row.get("is_earnings_up_gap"))
            and int(row["trend_state"]) == 1
            and trend_mature
            and bar.close >= 25.0
            and eff is not None
            and eff >= 0.20
            and rsi is not None
            and rsi <= 80.0
            and adx_rising
            and close_loc >= 0.65
            and l10 is not None
            and atr is not None
            and atr > 0
        )
        gap_entry = (
            not active
            and bool(row.get("gap_go"))
            and fresh20
            and bar.close >= 25.0
            and l10 is not None
            and atr is not None
            and atr > 0
        )
        if normal_entry or gap_entry:
            risk_distance = max(bar.close - float(l10), 0.0)
            if risk_distance > 0:
                active = True
                entry = bar.close
                initial_atr = atr
                hard_stop = entry - 0.75 * risk_distance
                units = 2.0
                add1 = False
                add2 = False
                add1_i = None

        trend_ok = (
            active
            and int(row["trend_state"]) == 1
            and adx is not None
            and adx >= 17.0
        )
        if (
            active
            and not add1
            and entry is not None
            and initial_atr is not None
            and trend_ok
            and bar.close >= entry + initial_atr
        ):
            add1 = True
            add1_i = i
            units = 3.0
        if (
            active
            and add1
            and not add2
            and add1_i is not None
            and i > add1_i
            and entry is not None
            and initial_atr is not None
            and trend_ok
            and bar.close >= entry + 2.0 * initial_atr
        ):
            add2 = True
            units = 4.0

        hard_exit = active and hard_stop is not None and bar.close <= hard_stop
        trend_exit = active and l55 is not None and bar.close < float(l55)
        if hard_exit or trend_exit:
            active = False
            entry = None
            initial_atr = None
            hard_stop = None
            units = 0.0
            add1 = False
            add2 = False
            add1_i = None

        out[bar.trade_date] = SignalState(
            active=active,
            entry=entry,
            hard_stop=hard_stop,
            units=units,
        )
    return out


def trailing_returns(series: dict[date, Bar], dates: list[date], idx: int, n: int) -> list[float]:
    start = max(1, idx - n + 1)
    out: list[float] = []
    for j in range(start, idx + 1):
        d0, d1 = dates[j - 1], dates[j]
        if d0 not in series or d1 not in series:
            continue
        p0 = series[d0].close
        p1 = series[d1].close
        if p0 > 0:
            out.append(p1 / p0 - 1.0)
    return out


def covariance(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 20:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx, my = mean(xs), mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n


def beta_to_spy(
    symbol: str,
    by_date: dict[str, dict[date, Bar]],
    dates: list[date],
    idx: int,
    n: int = 60,
) -> float:
    xs = trailing_returns(by_date[symbol], dates, idx, n)
    ys = trailing_returns(by_date["SPY"], dates, idx, n)
    var = covariance(ys, ys)
    if var <= 1e-12:
        return 1.0
    beta = covariance(xs, ys) / var
    return min(2.5, max(-0.5, beta))


def drawdown_multiplier(drawdown: float) -> float:
    if drawdown >= 0.15:
        return 0.0
    if drawdown >= 0.12:
        return 0.25
    if drawdown >= 0.08:
        return 0.50
    if drawdown >= 0.05:
        return 0.75
    return 1.0


def rolling_sma(series: dict[date, Bar], dates: list[date], idx: int, n: int) -> float | None:
    if idx + 1 < n:
        return None
    vals = [series[d].close for d in dates[idx - n + 1 : idx + 1] if d in series]
    return mean(vals) if len(vals) == n else None


def market_risk_state(
    by_date: dict[str, dict[date, Bar]], dates: list[date], idx: int
) -> tuple[bool, bool]:
    """Return risk_off, crisis using only the prior-close decision state."""
    spy = by_date["SPY"]
    d = dates[idx]
    sma100 = rolling_sma(spy, dates, idx, 100)
    ret20 = 0.0
    if idx >= 20:
        p0 = spy[dates[idx - 20]].close
        ret20 = spy[d].close / p0 - 1.0 if p0 > 0 else 0.0
    high252 = max(spy[x].close for x in dates[max(0, idx - 251) : idx + 1])
    dd = 1.0 - spy[d].close / high252 if high252 > 0 else 0.0
    risk_off = sma100 is not None and spy[d].close < sma100 and ret20 < 0.0
    crisis = dd >= 0.10
    return risk_off, crisis


def target_weights(
    scenario: Scenario,
    signal_date: date | None,
    decision_idx: int | None,
    states: dict[str, dict[date, SignalState]],
    by_date: dict[str, dict[date, Bar]],
    dates: list[date],
    nav: float,
    peak_nav: float,
) -> dict[str, float]:
    if signal_date is None or decision_idx is None or nav <= 0:
        return {"SGOV": 1.0 - OPERATIONAL_CASH_BUFFER} if scenario.use_sgov else {}

    raw: dict[str, float] = {}
    for symbol in SYMBOLS:
        state = states[symbol].get(signal_date)
        if not state or not state.active or state.entry is None or state.hard_stop is None:
            continue
        stop_pct = max((state.entry - state.hard_stop) / state.entry, 1e-6)
        base = min(MAX_SYMBOL_WEIGHT, RISK_PER_TRADE / stop_pct)
        unit_mult = state.units / 2.0 if state.units > 0 else 1.0
        raw[symbol] = min(MAX_SYMBOL_WEIGHT, base * unit_mult)

    total = sum(raw.values())
    if total > MAX_ALPHA_GROSS and total > 0:
        scale = MAX_ALPHA_GROSS / total
        raw = {k: v * scale for k, v in raw.items()}

    dd = max(0.0, 1.0 - nav / peak_nav) if peak_nav > 0 else 0.0
    if scenario.drawdown_throttle:
        mult = drawdown_multiplier(dd)
        raw = {k: v * mult for k, v in raw.items()}

    alpha_gross = sum(raw.values())

    if scenario.beta_hedge and raw:
        portfolio_beta = 0.0
        for symbol, weight in raw.items():
            portfolio_beta += weight * beta_to_spy(symbol, by_date, dates, decision_idx)
        risk_off, crisis = market_risk_state(by_date, dates, decision_idx)
        target_beta = 0.0 if crisis else 0.25 if risk_off else None
        if target_beta is not None and portfolio_beta > target_beta:
            raw["SPY"] = -min(0.50, portfolio_beta - target_beta)

    if scenario.use_sgov:
        reserve = max(0.0, 1.0 - OPERATIONAL_CASH_BUFFER - alpha_gross)
        raw["SGOV"] = reserve
    return raw


def classify_asset(symbol: str, weight: float) -> str:
    if symbol == "SGOV":
        return "SGOV"
    if symbol == "SPY" and weight < 0:
        return "HEDGE"
    return "ALPHA"


def simulate(
    scenario: Scenario,
    by_date: dict[str, dict[date, Bar]],
    states: dict[str, dict[date, SignalState]],
    dates: list[date],
) -> dict[str, Any]:
    cash = INITIAL_NAV
    shares: dict[str, float] = {}
    nav_curve: list[tuple[date, float]] = []
    turnover = 0.0
    contrib: defaultdict[str, float] = defaultdict(float)
    peak_nav = INITIAL_NAV
    gross_series: list[float] = []
    net_series: list[float] = []

    for idx, d in enumerate(dates):
        signal_date = dates[idx - 1] if idx > 0 else None
        decision_idx = idx - 1 if idx > 0 else None

        open_nav = cash + sum(q * by_date[s][d].open for s, q in shares.items())
        peak_nav = max(peak_nav, open_nav)
        targets = target_weights(
            scenario, signal_date, decision_idx, states, by_date, dates, open_nav, peak_nav
        )

        all_symbols = set(shares) | set(targets)
        for symbol in sorted(all_symbols):
            px = by_date[symbol][d].open
            current = shares.get(symbol, 0.0) * px
            target = open_nav * targets.get(symbol, 0.0)
            trade = target - current
            if abs(trade) < 1e-6:
                continue
            kind = classify_asset(symbol, targets.get(symbol, 0.0))
            cost = abs(trade) * COST_BPS[kind] / 10_000.0
            cash -= trade + cost
            contrib[f"{kind}_COST"] -= cost
            turnover += abs(trade)
            new_q = target / px
            if abs(new_q) < 1e-12:
                shares.pop(symbol, None)
            else:
                shares[symbol] = new_q

        close_nav = cash + sum(q * by_date[s][d].close for s, q in shares.items())
        for symbol, q in shares.items():
            fallback_weight = q * by_date[symbol][d].open / open_nav if open_nav else 0.0
            kind = classify_asset(symbol, targets.get(symbol, fallback_weight))
            contrib[kind] += q * (by_date[symbol][d].close - by_date[symbol][d].open)

        gross_series.append(sum(abs(w) for s, w in targets.items() if s != "SGOV"))
        net_series.append(sum(w for s, w in targets.items() if s != "SGOV"))
        nav_curve.append((d, close_nav))
        peak_nav = max(peak_nav, close_nav)

    return summarize(nav_curve, gross_series, net_series, turnover, contrib, by_date)


def summarize(
    nav: list[tuple[date, float]],
    gross: list[float],
    net: list[float],
    turnover: float,
    contrib: dict[str, float],
    by_date: dict[str, dict[date, Bar]],
) -> dict[str, Any]:
    vals = [v for _, v in nav]
    rets = [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals))]
    years = max((nav[-1][0] - nav[0][0]).days / 365.25, 1 / 252)
    cagr = (vals[-1] / vals[0]) ** (1.0 / years) - 1.0
    vol = pstdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    downside = [min(x, 0.0) for x in rets]
    downvol = math.sqrt(mean(x * x for x in downside)) * math.sqrt(252) if downside else 0.0

    peak = vals[0]
    max_dd = 0.0
    max_dd_end = 0
    recovery_days = 0
    underwater_start: int | None = None
    for i, value in enumerate(vals):
        if value >= peak:
            peak = value
            if underwater_start is not None:
                recovery_days = max(recovery_days, i - underwater_start)
                underwater_start = None
        else:
            if underwater_start is None:
                underwater_start = i
            dd = 1.0 - value / peak
            if dd > max_dd:
                max_dd = dd
                max_dd_end = i
    if underwater_start is not None:
        recovery_days = max(recovery_days, len(vals) - 1 - underwater_start)

    monthly: dict[tuple[int, int], list[float]] = defaultdict(list)
    for i in range(1, len(nav)):
        d = nav[i][0]
        monthly[(d.year, d.month)].append(rets[i - 1])
    monthly_returns: list[tuple[tuple[int, int], float]] = []
    for key, rs in monthly.items():
        growth = 1.0
        for r in rs:
            growth *= 1.0 + r
        monthly_returns.append((key, growth - 1.0))
    worst_month = min((r for _, r in monthly_returns), default=0.0)

    sorted_rets = sorted(rets)
    tail_n = max(1, int(len(sorted_rets) * 0.05))
    expected_shortfall = mean(sorted_rets[:tail_n]) if sorted_rets else 0.0

    spy_rets: list[float] = []
    port_rets: list[float] = []
    for i in range(1, len(nav)):
        d0, d1 = nav[i - 1][0], nav[i][0]
        p0 = by_date["SPY"][d0].close
        p1 = by_date["SPY"][d1].close
        if p0 > 0:
            spy_rets.append(p1 / p0 - 1.0)
            port_rets.append(rets[i - 1])
    var_spy = covariance(spy_rets, spy_rets)
    beta = covariance(port_rets, spy_rets) / var_spy if var_spy > 1e-12 else 0.0

    return {
        "start": nav[0][0].isoformat(),
        "end": nav[-1][0].isoformat(),
        "ending_nav": round(vals[-1], 2),
        "total_return_pct": round((vals[-1] / vals[0] - 1.0) * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "annual_vol_pct": round(vol * 100.0, 2),
        "sharpe": round(cagr / vol, 3) if vol else None,
        "sortino": round(cagr / downvol, 3) if downvol else None,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "max_drawdown_end": nav[max_dd_end][0].isoformat(),
        "max_recovery_trading_days": recovery_days,
        "calmar": round(cagr / max_dd, 3) if max_dd else None,
        "worst_month_pct": round(worst_month * 100.0, 2),
        "expected_shortfall_5pct_daily_pct": round(expected_shortfall * 100.0, 3),
        "beta_to_spy": round(beta, 3),
        "avg_gross_exposure_pct": round(mean(gross) * 100.0, 2) if gross else 0.0,
        "avg_net_exposure_pct": round(mean(net) * 100.0, 2) if net else 0.0,
        "turnover_x_initial_nav": round(turnover / INITIAL_NAV, 2),
        "sleeve_pnl": {k: round(v, 2) for k, v in sorted(contrib.items())},
    }


def fetch_all(token: str) -> tuple[dict[str, list[Bar]], dict[str, str]]:
    required = SYMBOLS + REFERENCES
    data: dict[str, list[Bar]] = {}
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fetch_orats_history, s, start=START, end=END, token=token): s
            for s in required
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                bars, _ = future.result()
                data[symbol] = bars
            except Exception as exc:
                failures[symbol] = f"{type(exc).__name__}: {exc}"
    return data, failures


def main() -> None:
    global SYMBOLS
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")

    data, failures = fetch_all(token)
    missing_refs = [s for s in REFERENCES if s not in data]
    if missing_refs:
        raise RuntimeError(f"Missing required reference histories {missing_refs}; failures={failures}")

    available = [s for s in SYMBOLS if s in data]
    if len(available) < 50:
        raise RuntimeError(f"Only {len(available)} R2 symbols available; failures={failures}")
    SYMBOLS = available

    common = set.intersection(
        *({b.trade_date for b in data[s]} for s in SYMBOLS + REFERENCES)
    )
    dates = sorted(d for d in common if START <= d <= END)
    if len(dates) < 750:
        raise RuntimeError(f"Only {len(dates)} common trading dates")

    by_date = {s: {b.trade_date: b for b in data[s]} for s in SYMBOLS + REFERENCES}
    states = {s: build_r2_states(data[s]) for s in SYMBOLS}

    results: dict[str, Any] = {
        "methodology": {
            "alpha": "R2 Long-Runner 20D breakout / ADX17 rising / efficiency>=0.20 / close-location>=0.65 / 55D exit / 0.75 risk-distance close stop / +1,+2 ATR adds",
            "risk_per_trade": RISK_PER_TRADE,
            "max_symbol_weight": MAX_SYMBOL_WEIGHT,
            "max_alpha_gross": MAX_ALPHA_GROSS,
            "operational_cash_buffer": OPERATIONAL_CASH_BUFFER,
            "tail_hedge": "EXCLUDED_PHASE1_REQUIRES_EXECUTABLE_OPTION_QUOTES",
        },
        "universe_count": len(SYMBOLS),
        "failures": failures,
        "scenarios": {},
    }
    for scenario in SCENARIOS:
        results["scenarios"][scenario.name] = simulate(scenario, by_date, states, dates)

    Path("r2-downside-overlay.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
