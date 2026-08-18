"""Price/volume-only Minervini-inspired concentrated swing backtest.

This is an independent research model.  It does not reuse R2 signals, options,
fundamentals, social data, or live execution.  Signals are known at the close
and orders execute no earlier than the following session.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .backtest import Bar, fetch_orats_history


DEFAULT_UNIVERSE = (
    "AAPL,MSFT,NVDA,AMZN,GOOGL,META,AVGO,TSLA,BRK.B,LLY,JPM,V,WMT,ORCL,"
    "MA,NFLX,COST,XOM,JNJ,HD,PG,BAC,ABBV,KO,PLTR,CRM,CVX,AMD,TMUS,CSCO,"
    "PM,IBM,GE,UNH,ABT,MS,GS,MCD,AXP,TMO,INTU,ISRG,NOW,QCOM,TXN,AMGN,"
    "CAT,RTX,DIS,PEP,UBER,AMAT,SPGI,BLK,NEE,LOW,PANW,HON,PFE,BA,SBUX,"
    "BKNG,ANET,CRWD,ADBE,DE,APP,MU,GILD,ADI,KLAC,LRCX,SNOW,MRVL,ARM,"
    "MELI,SHOP,COIN,HOOD,DASH,ABNB,DDOG,NET,FTNT,CEG,VST,ETN,PH,TT,"
    "CAVA,RDDT,DUOL,DKNG,ROKU,ZS,TEAM,WDAY,DELL,SMCI,MSTR"
)


@dataclass(frozen=True)
class Feature:
    eligible: bool
    breakout: bool
    score: float
    pivot: float
    atr: float
    ema10: float
    ema20: float
    sma50: float
    close: float
    avg_dollar_volume: float


@dataclass
class Position:
    ticker: str
    shares: int
    entry_date: date
    entry_price: float
    average_price: float
    stop: float
    pivot: float
    initial_risk_per_share: float
    highest: float
    days: int = 0
    adds: int = 0
    partial_taken: bool = False
    scheduled_exit: str | None = None
    realized_pnl: float = 0.0


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= n:
            running -= values[i - n]
        if i >= n - 1:
            out[i] = running / n
    return out


def ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < n:
        return out
    seed = sum(values[:n]) / n
    out[n - 1] = seed
    alpha = 2.0 / (n + 1.0)
    previous = seed
    for i in range(n, len(values)):
        previous = alpha * values[i] + (1.0 - alpha) * previous
        out[i] = previous
    return out


def atr(bars: list[Bar], n: int = 14) -> list[float | None]:
    tr: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            tr.append(bar.high - bar.low)
        else:
            prior = bars[i - 1].close
            tr.append(max(bar.high - bar.low, abs(bar.high - prior), abs(bar.low - prior)))
    return sma(tr, n)


def _window_range(bars: list[Bar], start: int, end: int, denominator: float) -> float:
    window = bars[start:end]
    return (max(b.high for b in window) - min(b.low for b in window)) / denominator


def build_features(bars: list[Bar], benchmark: dict[date, Bar]) -> dict[date, Feature]:
    """Create close-known features; breakout pivot excludes the signal bar."""
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    ma50, ma150, ma200 = sma(closes, 50), sma(closes, 150), sma(closes, 200)
    av50 = sma(volumes, 50)
    e10, e20 = ema(closes, 10), ema(closes, 20)
    a14 = atr(bars, 14)
    bench_dates = sorted(benchmark)
    bench_index = {d: i for i, d in enumerate(bench_dates)}
    rows: dict[date, Feature] = {}
    for i, bar in enumerate(bars):
        if i < 252 or any(x is None for x in (ma50[i], ma150[i], ma200[i], av50[i], e10[i], e20[i], a14[i])):
            continue
        bd = bench_index.get(bar.trade_date)
        if bd is None or bd < 126:
            continue
        high52 = max(b.high for b in bars[i - 251 : i + 1])
        low52 = min(b.low for b in bars[i - 251 : i + 1])
        stock63 = bar.close / bars[i - 63].close - 1.0
        stock126 = bar.close / bars[i - 126].close - 1.0
        spy63 = benchmark[bench_dates[bd]].close / benchmark[bench_dates[bd - 63]].close - 1.0
        spy126 = benchmark[bench_dates[bd]].close / benchmark[bench_dates[bd - 126]].close - 1.0
        dollar_volume = float(av50[i]) * bar.close
        trend = (
            bar.close > float(ma50[i]) > float(ma150[i]) > float(ma200[i])
            and float(ma200[i]) > float(ma200[i - 20])
            and bar.close >= 0.75 * high52
            and bar.close >= 1.30 * low52
            and stock63 > spy63
            and stock126 > spy126
            and bar.close >= 15.0
            and dollar_volume >= 50_000_000.0
        )
        # Contraction is measured through yesterday so today's breakout cannot
        # manufacture its own setup.
        r40 = _window_range(bars, i - 40, i, bars[i - 1].close)
        r20 = _window_range(bars, i - 20, i, bars[i - 1].close)
        r10 = _window_range(bars, i - 10, i, bars[i - 1].close)
        vol10 = mean(b.volume for b in bars[i - 10 : i])
        pivot = max(b.high for b in bars[i - 20 : i])
        contraction = r20 <= 0.80 * r40 and r10 <= 0.80 * r20 and vol10 < float(av50[i])
        breakout = trend and contraction and bar.close > pivot and bar.volume >= 1.50 * float(av50[i])
        score = (
            100.0 * (stock63 - spy63)
            + 60.0 * (stock126 - spy126)
            - 100.0 * r10
            + 10.0 * min(bar.volume / float(av50[i]), 3.0)
        )
        rows[bar.trade_date] = Feature(
            eligible=trend and contraction,
            breakout=breakout,
            score=score,
            pivot=pivot,
            atr=float(a14[i]),
            ema10=float(e10[i]),
            ema20=float(e20[i]),
            sma50=float(ma50[i]),
            close=bar.close,
            avg_dollar_volume=dollar_volume,
        )
    return rows


def market_regime(spy: list[Bar], qqq: list[Bar]) -> dict[date, float]:
    """Return maximum gross exposure known at each close."""
    out: dict[date, float] = {}
    series: dict[str, tuple[list[Bar], list[float | None], list[float | None]]] = {}
    for ticker, bars in (("SPY", spy), ("QQQ", qqq)):
        closes = [b.close for b in bars]
        series[ticker] = (bars, sma(closes, 50), sma(closes, 200))
    q_by_date = {b.trade_date: i for i, b in enumerate(qqq)}
    for i, bar in enumerate(spy):
        qi = q_by_date.get(bar.trade_date)
        if qi is None or i < 199 or qi < 199:
            continue
        spy50, spy200 = series["SPY"][1][i], series["SPY"][2][i]
        q50, q200 = series["QQQ"][1][qi], series["QQQ"][2][qi]
        assert spy50 is not None and spy200 is not None and q50 is not None and q200 is not None
        spy_good = bar.close > spy50 > spy200
        q_good = qqq[qi].close > q50 > q200
        out[bar.trade_date] = 1.0 if spy_good and q_good else 0.50 if spy_good or q_good else 0.0
    return out


def _metrics(nav: list[tuple[date, float]], trades: list[dict[str, Any]], exposure: list[float], benchmark: list[float]) -> dict[str, Any]:
    values = [v for _, v in nav]
    daily = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values))]
    years = max((nav[-1][0] - nav[0][0]).days / 365.25, 1 / 252)
    cagr = (values[-1] / values[0]) ** (1.0 / years) - 1.0
    vol = pstdev(daily) * math.sqrt(252) if len(daily) > 1 else 0.0
    downside = math.sqrt(mean(min(r, 0.0) ** 2 for r in daily)) * math.sqrt(252) if daily else 0.0
    peak, max_dd = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        max_dd = max(max_dd, 1.0 - value / peak)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] < 0]
    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = -sum(t["net_pnl"] for t in losses)
    bench_total = benchmark[-1] / benchmark[0] - 1.0 if benchmark else 0.0
    return {
        "ending_nav": round(values[-1], 2),
        "total_return_pct": round((values[-1] / values[0] - 1.0) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "annual_vol_pct": round(vol * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(cagr / vol, 2) if vol else None,
        "sortino": round(cagr / downside, 2) if downside else None,
        "calmar": round(cagr / max_dd, 2) if max_dd else None,
        "closed_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else None,
        "average_win": round(mean(t["net_pnl"] for t in wins), 2) if wins else None,
        "average_loss": round(mean(t["net_pnl"] for t in losses), 2) if losses else None,
        "payoff_ratio": round(mean(t["net_pnl"] for t in wins) / -mean(t["net_pnl"] for t in losses), 2) if wins and losses else None,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else None,
        "average_exposure_pct": round(mean(exposure) * 100, 2) if exposure else 0.0,
        "spy_total_return_pct": round(bench_total * 100, 2),
    }


def simulate(
    raw: dict[str, list[Bar]],
    features: dict[str, dict[date, Feature]],
    regime: dict[date, float],
    *,
    start: date,
    end: date,
    initial_nav: float,
    max_positions: int = 6,
    base_risk: float = 0.0075,
    slippage_bps: float = 5.0,
) -> tuple[list[tuple[date, float]], list[dict[str, Any]], dict[str, Any]]:
    by_date = {t: {b.trade_date: b for b in bars} for t, bars in raw.items()}
    dates = [b.trade_date for b in raw["SPY"] if start <= b.trade_date <= end and b.trade_date in regime]
    positions: dict[str, Position] = {}
    cash = initial_nav
    nav: list[tuple[date, float]] = []
    exposures: list[float] = []
    trades: list[dict[str, Any]] = []
    peak = initial_nav
    slip = slippage_bps / 10_000.0

    def sell(ticker: str, qty: int, price: float, reason: str, d: date) -> None:
        nonlocal cash
        pos = positions[ticker]
        qty = min(qty, pos.shares)
        fill = price * (1.0 - slip)
        pnl = qty * (fill - pos.average_price)
        cash += qty * fill
        pos.realized_pnl += pnl
        pos.shares -= qty
        if pos.shares == 0:
            trades.append({
                "ticker": ticker,
                "entry_date": pos.entry_date.isoformat(),
                "exit_date": d.isoformat(),
                "entry_price": round(pos.entry_price, 4),
                "exit_price": round(fill, 4),
                "net_pnl": round(pos.realized_pnl, 2),
                "return_on_initial_risk": round(pos.realized_pnl / max(pos.initial_risk_per_share, 1e-9), 4),
                "exit_reason": reason,
                "adds": pos.adds,
            })
            del positions[ticker]

    for idx, d in enumerate(dates):
        bars_today = {t: by_date[t][d] for t in by_date if d in by_date[t]}
        if "SPY" not in bars_today:
            continue
        open_nav = cash + sum(p.shares * bars_today[t].open for t, p in positions.items() if t in bars_today)
        peak = max(peak, open_nav)
        drawdown = 1.0 - open_nav / peak if peak else 0.0

        # Execute close-known exits and overnight gap stops first.
        for ticker in list(positions):
            if ticker not in bars_today:
                continue
            pos, bar = positions[ticker], bars_today[ticker]
            if pos.scheduled_exit:
                sell(ticker, pos.shares, bar.open, pos.scheduled_exit, d)
                continue
            if bar.open <= pos.stop:
                sell(ticker, pos.shares, bar.open, "GAP_STOP", d)
                continue
            if bar.low <= pos.stop:
                sell(ticker, pos.shares, pos.stop, "STOP", d)

        prior = dates[idx - 1] if idx else None
        max_exposure = regime.get(prior, 0.0) if prior else 0.0
        if drawdown >= 0.08:
            max_exposure = 0.0
        elif drawdown >= 0.05:
            max_exposure = min(max_exposure, 0.50)
        risk_fraction = 0.005 if drawdown >= 0.03 else base_risk

        # Add only after a profitable close confirmation; execute next open.
        if prior:
            for ticker in list(positions):
                pos = positions[ticker]
                signal = features.get(ticker, {}).get(prior)
                bar = bars_today.get(ticker)
                if not signal or not bar or pos.adds >= 2 or signal.close < pos.entry_price * (1.025 + 0.025 * pos.adds):
                    continue
                gross = sum(p.shares * bars_today[t].open for t, p in positions.items() if t in bars_today)
                room_total = max(0.0, open_nav * max_exposure - gross)
                room_name = max(0.0, open_nav * 0.25 - pos.shares * bar.open)
                add_value = min(pos.shares * bar.open * 0.50, room_total, room_name, cash)
                qty = int(add_value / (bar.open * (1.0 + slip)))
                if qty > 0:
                    fill = bar.open * (1.0 + slip)
                    cash -= qty * fill
                    old_value = pos.average_price * pos.shares
                    pos.average_price = (old_value + qty * fill) / (pos.shares + qty)
                    pos.shares += qty
                    pos.adds += 1
                    pos.stop = max(pos.stop, pos.average_price)

        # Rank yesterday's breakouts and buy at today's open.
        if prior and max_exposure > 0 and len(positions) < max_positions:
            candidates = [
                (ticker, rows[prior])
                for ticker, rows in features.items()
                if ticker not in positions and prior in rows and rows[prior].breakout and ticker in bars_today
            ]
            candidates.sort(key=lambda item: item[1].score, reverse=True)
            for ticker, signal in candidates:
                if len(positions) >= max_positions:
                    break
                bar = bars_today[ticker]
                fill = bar.open * (1.0 + slip)
                stop_distance = min(max(1.5 * signal.atr, fill * 0.04), fill * 0.07)
                stop = fill - stop_distance
                risk_budget = open_nav * risk_fraction
                qty_risk = int(risk_budget / stop_distance)
                gross = sum(p.shares * bars_today[t].open for t, p in positions.items() if t in bars_today)
                room_total = max(0.0, open_nav * max_exposure - gross)
                room_name = open_nav * 0.15
                qty = min(qty_risk, int(room_total / fill), int(room_name / fill), int(cash / fill))
                if qty <= 0:
                    continue
                cash -= qty * fill
                positions[ticker] = Position(
                    ticker=ticker, shares=qty, entry_date=d, entry_price=fill,
                    average_price=fill, stop=stop, pivot=signal.pivot,
                    initial_risk_per_share=qty * stop_distance, highest=bar.high,
                )

        # Intraday 2R partials, then set close-known exits for next session.
        for ticker in list(positions):
            if ticker not in bars_today:
                continue
            pos, bar = positions[ticker], bars_today[ticker]
            pos.days += 1
            pos.highest = max(pos.highest, bar.high)
            target = pos.entry_price + 2.0 * (pos.entry_price - (pos.entry_price - pos.initial_risk_per_share / max(pos.shares, 1)))
            if not pos.partial_taken and bar.high >= target and pos.shares >= 3:
                sell(ticker, max(1, pos.shares // 3), target, "PARTIAL_2R", d)
                if ticker not in positions:
                    continue
                positions[ticker].partial_taken = True
                positions[ticker].stop = max(positions[ticker].stop, positions[ticker].average_price)
                pos = positions[ticker]
            signal = features.get(ticker, {}).get(d)
            if not signal:
                continue
            if pos.days <= 5 and signal.close < pos.pivot:
                pos.scheduled_exit = "FAILED_BREAKOUT"
            elif pos.partial_taken and signal.close < signal.ema10:
                pos.scheduled_exit = "EMA10_TRAIL"
            elif pos.days >= 10 and signal.close < signal.ema20:
                pos.scheduled_exit = "EMA20_EXIT"
            elif signal.close < signal.sma50:
                pos.scheduled_exit = "SMA50_EXIT"

        close_nav = cash + sum(p.shares * bars_today[t].close for t, p in positions.items() if t in bars_today)
        gross_close = sum(p.shares * bars_today[t].close for t, p in positions.items() if t in bars_today)
        nav.append((d, close_nav))
        exposures.append(gross_close / close_nav if close_nav > 0 else 0.0)
        peak = max(peak, close_nav)

    spy_values = [by_date["SPY"][d].close for d, _ in nav]
    return nav, trades, _metrics(nav, trades, exposures, spy_values)


def run(args: argparse.Namespace) -> dict[str, Any]:
    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    universe = [x.strip().upper() for x in args.universe.split(",") if x.strip()]
    required = sorted(set(universe) | {"SPY", "QQQ"})
    raw: dict[str, list[Bar]] = {}
    failures: dict[str, str] = {}

    def fetch(ticker: str) -> tuple[str, list[Bar]]:
        bars, _ = fetch_orats_history(ticker, start=start, end=end, token=token)
        return ticker, bars

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, ticker): ticker for ticker in required}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                _, raw[ticker] = future.result()
            except Exception as exc:  # preserve complete research evidence
                failures[ticker] = f"{type(exc).__name__}: {exc}"
    if "SPY" not in raw or "QQQ" not in raw:
        raise RuntimeError(f"Missing benchmark history: {failures}")
    available = [ticker for ticker in universe if ticker in raw]
    if len(available) < args.minimum_stocks:
        raise RuntimeError(f"Only {len(available)} stock histories available; failures={failures}")
    benchmark = {b.trade_date: b for b in raw["SPY"]}
    features = {ticker: build_features(raw[ticker], benchmark) for ticker in available}
    regime = market_regime(raw["SPY"], raw["QQQ"])
    nav, trades, summary = simulate(
        raw, features, regime, start=start, end=end,
        initial_nav=args.initial_nav, max_positions=args.max_positions,
        base_risk=args.risk_per_trade, slippage_bps=args.slippage_bps,
    )
    return {
        "performance_basis": "BACKTEST",
        "research_only": True,
        "strategy": "MINERVINI_INSPIRED_PRICE_VOLUME_V1",
        "start": args.start,
        "end": args.end,
        "initial_nav": args.initial_nav,
        "available_stock_count": len(available),
        "assumptions": {
            "signals": "CLOSE_KNOWN_NEXT_SESSION_EXECUTION",
            "max_positions": args.max_positions,
            "initial_position_cap_pct": 15.0,
            "completed_position_cap_pct": 25.0,
            "risk_per_trade_pct": args.risk_per_trade * 100.0,
            "slippage_bps_each_side": args.slippage_bps,
            "fundamentals_options_events": "EXCLUDED",
            "universe_warning": "Fixed present-day liquid universe; survivorship bias remains until point-in-time membership is supplied",
        },
        "data_failures": failures,
        "metrics": summary,
        "trades": trades,
        "curve": [{"date": d.isoformat(), "nav": round(v, 2)} for d, v in nav],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--initial-nav", type=float, default=1_000_000.0)
    parser.add_argument("--max-positions", type=int, default=6)
    parser.add_argument("--risk-per-trade", type=float, default=0.0075)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--minimum-stocks", type=int, default=75)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--json-out", default="minervini-backtest.json")
    args = parser.parse_args()
    result = run(args)
    Path(args.json_out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    m = result["metrics"]
    print("MINERVINI-INSPIRED PRICE/VOLUME BACKTEST")
    print(f"CAGR={m['cagr_pct']}% DD={m['max_drawdown_pct']}% Sharpe={m['sharpe']} PF={m['profit_factor']} End=${m['ending_nav']:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
