"""Daily-NAV cash-secured put challenger for Daily Alpha R2 signals."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any
from urllib.parse import urlencode

from .backtest import _request_json, fetch_orats_history, indicators, run_strategy
from .backtest_options import _num, _rows
from .portfolio_options_backtest import OPTION_COHORT, contract_history
from .scenario_backtest import r2_scores


@dataclass
class PutTrade:
    ticker: str
    entry_date: date
    expiry: date
    strike: float
    entry_bid: float
    exit_date: date
    exit_ask: float
    collateral: float
    pnl: float
    exit_reason: str
    ask_marks: dict[date, float]


def fetch_put_chain(ticker: str, trade_date: date, token: str) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "token": token, "ticker": ticker,
            "tradeDate": trade_date.isoformat(), "dte": "30,60",
            "fields": (
                "ticker,tradeDate,expirDate,dte,strike,stockPrice,delta,"
                "putBidPrice,putAskPrice,putVolume,putOpenInterest"
            ),
        }
    )
    payload = _request_json(
        f"https://api.orats.io/datav2/hist/strikes?{query}",
        token=token, header_auth=False,
    )
    return _rows(payload)


def select_put(rows: list[dict[str, Any]], target_delta: float) -> dict[str, Any] | None:
    qualified: list[tuple[float, float, dict[str, Any]]] = []
    for row in rows:
        bid, ask = _num(row.get("putBidPrice")), _num(row.get("putAskPrice"))
        dte = int(_num(row.get("dte")))
        oi, volume = int(_num(row.get("putOpenInterest"))), int(_num(row.get("putVolume")))
        put_delta = abs(_num(row.get("delta")) - 1.0)
        mid = (bid + ask) / 2 if bid > 0 and ask >= bid else 0.0
        spread = (ask - bid) / mid if mid else 999.0
        if 30 <= dte <= 60 and bid >= 0.25 and ask >= bid and spread <= 0.25 and oi >= 100 and volume >= 10:
            qualified.append((abs(put_delta - target_delta), spread, row))
    return min(qualified, key=lambda item: item[:2])[2] if qualified else None


def r2_entries(start: date, end: date, token: str) -> list[tuple[str, Any]]:
    trades: list[tuple[str, Any]] = []
    scores: dict[str, dict[date, float]] = {}
    for ticker in OPTION_COHORT.split(","):
        bars, _ = fetch_orats_history(ticker, start=start, end=end, token=token)
        scores[ticker] = r2_scores(bars)
        rows = indicators(bars)
        ticker_trades, _ = run_strategy(bars, rows, version="2.4", start=start, end=end)
        trades.extend((ticker, trade) for trade in ticker_trades)
    grouped: dict[date, list[tuple[str, Any]]] = {}
    for ticker, trade in trades:
        grouped.setdefault(date.fromisoformat(trade.entry_date), []).append((ticker, trade))
    selected: list[tuple[str, Any]] = []
    for entry_date, rows in sorted(grouped.items()):
        selected.extend(
            sorted(rows, key=lambda item: scores[item[0]].get(entry_date, -999), reverse=True)[:2]
        )
    return selected


def build_put_trade(ticker: str, signal: Any, target: float, token: str) -> PutTrade | None:
    entry_date = date.fromisoformat(signal.entry_date)
    selected = select_put(fetch_put_chain(ticker, entry_date, token), target)
    if selected is None:
        return None
    expiry = date.fromisoformat(str(selected["expirDate"])[:10])
    strike, entry_bid = _num(selected.get("strike")), _num(selected.get("putBidPrice"))
    history = contract_history(ticker, expiry.isoformat(), strike, entry_date, expiry, token)
    daily = sorted(
        (
            date.fromisoformat(str(row["tradeDate"])[:10]),
            _num(row.get("putAskPrice")), _num(row.get("stockPrice")),
        )
        for row in history if row.get("tradeDate")
    )
    if not daily:
        return None
    strategy_exit = date.fromisoformat(signal.exit_date)
    deadline = min(strategy_exit, expiry - timedelta(days=21))
    exit_date, exit_ask, reason = daily[-1][0], daily[-1][1], "LAST_QUOTE"
    for mark_date, ask, _ in daily:
        if mark_date < entry_date:
            continue
        if ask <= entry_bid * 0.50:
            exit_date, exit_ask, reason = mark_date, ask, "PROFIT_50"
            break
        if mark_date >= deadline:
            exit_date, exit_ask = mark_date, ask
            reason = "R2_EXIT" if strategy_exit <= expiry - timedelta(days=21) else "21_DTE"
            break
    collateral = strike * 100
    pnl = (entry_bid - exit_ask) * 100
    marks = {mark_date: ask for mark_date, ask, _ in daily if entry_date <= mark_date <= exit_date}
    return PutTrade(ticker, entry_date, expiry, strike, entry_bid, exit_date, exit_ask, collateral, pnl, reason, marks)


def portfolio(trades: list[PutTrade], dates: list[date], initial: float) -> dict[str, Any]:
    cash = initial
    active: list[tuple[PutTrade, int]] = []
    nav_curve: list[tuple[date, float]] = []
    realized = 0.0
    accepted: list[PutTrade] = []
    for d in dates:
        for trade, contracts in list(active):
            if trade.exit_date == d:
                cost = trade.exit_ask * 100 * contracts
                cash -= cost
                realized += (trade.entry_bid - trade.exit_ask) * 100 * contracts
                active.remove((trade, contracts))
        used = sum(trade.collateral * contracts for trade, contracts in active)
        for trade in [t for t in trades if t.entry_date == d]:
            available = initial * 0.90 - used
            contracts = min(int((initial * 0.30) // trade.collateral), int(available // trade.collateral))
            if contracts < 1:
                continue
            cash += trade.entry_bid * 100 * contracts
            active.append((trade, contracts))
            used += trade.collateral * contracts
            accepted.append(trade)
        liability = 0.0
        for trade, contracts in active:
            available_marks = [value for mark_date, value in trade.ask_marks.items() if mark_date <= d]
            mark = available_marks[-1] if available_marks else trade.entry_bid
            liability += mark * 100 * contracts
        nav_curve.append((d, cash - liability))
    values = [value for _, value in nav_curve]
    returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]
    years = (dates[-1] - dates[0]).days / 365.25
    cagr = (values[-1] / values[0]) ** (1 / years) - 1
    vol = pstdev(returns) * 252**0.5 if len(returns) > 1 else 0.0
    downside = [min(r, 0) for r in returns]
    downvol = (mean([r * r for r in downside]) ** 0.5) * 252**0.5
    peak, drawdown = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    return {
        "ending_nav": round(values[-1], 2), "cagr_pct": round(cagr * 100, 2),
        "total_return_pct": round((values[-1] / values[0] - 1) * 100, 2),
        "max_drawdown_pct": round(drawdown * 100, 2),
        "annual_vol_pct": round(vol * 100, 2),
        "sharpe": round(cagr / vol, 2) if vol else None,
        "sortino": round(cagr / downvol, 2) if downvol else None,
        "calmar": round(cagr / drawdown, 2) if drawdown else None,
        "trades": len(accepted), "realized_premium_pnl": round(realized, 2),
        "win_rate_pct": round(100 * sum(t.pnl > 0 for t in accepted) / len(accepted), 2) if accepted else 0.0,
        "profit_50_exits": sum(t.exit_reason == "PROFIT_50" for t in accepted),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--json-out", default="cash-secured-puts.json")
    args = parser.parse_args()
    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    signals = r2_entries(start, end, token)
    dates = sorted({b.trade_date for b in fetch_orats_history("SPY", start=start, end=end, token=token)[0] if start <= b.trade_date <= end})
    report: dict[str, Any] = {}
    for target in (0.15, 0.20, 0.25):
        puts = [trade for ticker, signal in signals if (trade := build_put_trade(ticker, signal, target, token)) is not None]
        report[f"delta_{int(target * 100)}"] = portfolio(puts, dates, 1_000_000.0)
        print(f"DELTA_{int(target * 100)}", json.dumps(report[f"delta_{int(target * 100)}"], sort_keys=True))
    Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
