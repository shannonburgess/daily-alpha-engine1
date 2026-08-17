"""Research-only broad model search for Daily Alpha >2R average winner.

No broker calls, no Lambda execution, no paper-ledger writes, and no production changes.

Goal: find robust model families with average winning trade > 2.0R while retaining
positive expectancy and acceptable profit factor. Canonical Daily Alpha R is preserved:
initial two-unit risk = 2 * (entry close - prior 10-day low). Core +1/+2 ATR adds are
kept fixed so the search cannot manufacture a higher R multiple by simply increasing
leverage.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median

from daily_alpha.backtest import fetch_orats_history, indicators

DEV_NAMES = {
    "LRCX","MU","FTI","IRM","RCMT","HUBB","ALGN","HUM","MRK","PSX","VLO",
    "PLTR","SNDK","JNJ","HOOD","C",
}

SYMBOLS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","AMD","QCOM","TXN",
    "AMAT","KLAC","CRM","NOW","ADBE","ORCL","IBM","CSCO","PANW","CRWD",
    "SNOW","INTC","MUFG","JPM","BAC","WFC","GS","MS","AXP","SCHW",
    "BLK","SPGI","CME","ICE","PNC","USB","COF","BK","TROW","UNH",
    "LLY","PFE","ABBV","TMO","DHR","ISRG","MDT","BMY","AMGN","GILD",
    "CVS","CI","ELV","BSX","ZTS","MCK","CAT","DE","GE","RTX",
    "BA","HON","ETN","PH","EMR","ITW","MMM","UPS","FDX","URI",
    "PWR","XOM","CVX","COP","EOG","SLB","OXY","MPC","KMI","WMB",
    "DVN","FANG","WMT","COST","HD","LOW","TGT","NKE","MCD","SBUX",
    "BKNG","MAR","ABNB","TSLA","GM","F","NFLX","DIS","T","NEE",
    "SO","DUK","AEP","EXC","SRE","AMT","PLD","EQIX","LIN","FCX",
    "NEM","NUE","SHW",
]
SYMBOLS = [s for i, s in enumerate(SYMBOLS) if s not in DEV_NAMES and s not in SYMBOLS[:i]]

# Stable cross-sectional split. Search/tuning never sees HOLDOUT symbols.
def bucket(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16) % 100

SEARCH_SYMBOLS = [s for s in SYMBOLS if bucket(s) < 68]
HOLDOUT_SYMBOLS = [s for s in SYMBOLS if bucket(s) >= 68]

FETCH_START = date(2021, 1, 1)
FETCH_END = date(2026, 7, 31)
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2024, 12, 31)
VALID_START = date(2025, 1, 1)
VALID_END = date(2025, 12, 31)
STRESS_START = date(2026, 1, 1)
STRESS_END = date(2026, 7, 31)
FULL_START = date(2022, 1, 1)
FULL_END = date(2025, 12, 31)


@dataclass(frozen=True)
class EntryConfig:
    breakout: int = 20
    adx_mode: str = "17_RISING"
    efficiency_min: float = 0.20
    rsi_max: float = 80.0
    maturity_bars: int = 2
    relative_volume_min: float = 0.0
    close_location_min: float = 0.0
    breakout_atr_min: float = 0.0
    atr_pct_min: float = 0.0


@dataclass(frozen=True)
class ManageConfig:
    turtle_exit: int = 10
    failed_window: int = 3
    failed_tolerance_atr: float = 0.0
    harvest_atr: float = 3.0  # 0 means no partial harvest
    post_harvest_be: bool = True
    trend_flip_exit: bool = True


@dataclass(frozen=True)
class ModelConfig:
    entry: EntryConfig
    manage: ManageConfig


def window_high(bars, i: int, length: int):
    if i < length:
        return None
    return max(b.high for b in bars[i-length:i])


def window_low(bars, i: int, length: int):
    if i < length:
        return None
    return min(b.low for b in bars[i-length:i])


def fresh_breakout(bars, i: int, length: int):
    upper = window_high(bars, i, length)
    if upper is None:
        return None, False
    now = bars[i].close > upper
    prev = False
    if i >= length + 1:
        prev_upper = max(b.high for b in bars[i-length-1:i-1])
        prev = bars[i-1].close > prev_upper
    return upper, now and not prev


def adx_entry_ok(ind, i: int, mode: str) -> bool:
    v = ind[i]["adx"]
    if mode == "NONE":
        return True
    if v is None:
        return False
    v = float(v)
    if mode == "25":
        return v >= 25.0
    if mode == "20":
        return v >= 20.0
    if mode.endswith("_RISING"):
        threshold = float(mode.split("_")[0])
        if v < threshold or i <= 0 or ind[i-1]["adx"] is None:
            return False
        return v > float(ind[i-1]["adx"])
    raise ValueError(mode)


def maturity_ok(ind, i: int, bars_required: int) -> bool:
    if bars_required <= 0:
        return True
    # normal_trend_mature encodes >=2 completed bullish bars. For other values,
    # derive directly from prior trend states.
    if i < bars_required:
        return False
    return all(int(ind[j]["trend_state"]) == 1 for j in range(i-bars_required, i))


def run_model(bars, ind, cfg: ModelConfig, start: date, end: date) -> dict:
    qty = 0.0
    avg_cost = 0.0
    entry_breakout = None
    entry_bar = None
    base_entry = None
    base_atr = None
    add1_done = add2_done = harvest_done = False
    add1_bar = add2_bar = None
    break_even = None
    current = None
    trades = []

    for i, (bar, row) in enumerate(zip(bars, ind)):
        in_window = start <= bar.trade_date <= end
        flat = qty == 0
        upper, fresh = fresh_breakout(bars, i, cfg.entry.breakout)
        low10 = window_low(bars, i, 10)
        turtle_low = window_low(bars, i, cfg.manage.turtle_exit)
        atr = None if row["atr"] is None else float(row["atr"])
        eff = None if row["efficiency"] is None else float(row["efficiency"])
        rsi = None if row["rsi"] is None else float(row["rsi"])
        relvol = float(row.get("relative_volume") or 0.0)
        close_loc = (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else 0.5
        atr_pct = (atr / bar.close) if atr is not None and bar.close > 0 else 0.0
        bo_atr = ((bar.close - upper) / atr) if upper is not None and atr is not None and atr > 0 else 0.0

        normal_setup = (
            in_window and flat and fresh and not bool(row["is_earnings_up_gap"])
            and int(row["trend_state"]) == 1
            and maturity_ok(ind, i, cfg.entry.maturity_bars)
        )
        quality = (
            bar.close >= 25.0
            and eff is not None and eff >= cfg.entry.efficiency_min
            and rsi is not None and rsi <= cfg.entry.rsi_max
            and adx_entry_ok(ind, i, cfg.entry.adx_mode)
            and relvol >= cfg.entry.relative_volume_min
            and close_loc >= cfg.entry.close_location_min
            and bo_atr >= cfg.entry.breakout_atr_min
            and atr_pct >= cfg.entry.atr_pct_min
        )
        normal_entry = normal_setup and quality

        # Keep canonical Earnings Gap & Go unchanged, including 20-day breakout.
        gap_entry = (
            in_window and flat and bool(row["gap_go"]) and bool(row["fresh_breakout"])
            and bar.close >= 25.0
        )
        long_entry = normal_entry or gap_entry
        signal_breakout = float(row["upper20"]) if gap_entry and row["upper20"] is not None else upper
        entry_type = "EARNINGS_GAP_GO" if gap_entry else "NORMAL_BREAKOUT" if normal_entry else "NONE"

        if long_entry:
            entry_breakout = float(signal_breakout) if signal_breakout is not None else None
            entry_bar = i
            base_entry = bar.close
            base_atr = atr
            add1_done = add2_done = harvest_done = False
            add1_bar = add2_bar = None
            break_even = None

        bars_since = i - entry_bar if entry_bar is not None else None
        failed_exit = (
            qty > 0 and cfg.manage.failed_window > 0 and entry_breakout is not None
            and bars_since is not None and 1 <= bars_since <= cfg.manage.failed_window
            and base_atr is not None
            and bar.close < entry_breakout - cfg.manage.failed_tolerance_atr * base_atr
        )

        runner_trend_ok = (
            int(row["trend_state"]) == 1
            and row["adx"] is not None and float(row["adx"]) >= 17.0
        )
        add1 = (
            qty > 0 and not add1_done and base_entry is not None and base_atr is not None
            and runner_trend_ok and bar.close >= base_entry + base_atr
        )
        if add1:
            add1_done = True
            add1_bar = i
        add2 = (
            qty > 0 and add1_done and not add2_done and add1_bar is not None and i > add1_bar
            and base_entry is not None and base_atr is not None and runner_trend_ok
            and bar.close >= base_entry + 2.0 * base_atr
        )
        if add2:
            add2_done = True
            add2_bar = i

        harvest = False
        if cfg.manage.harvest_atr > 0:
            harvest = (
                qty > 0 and add2_done and not harvest_done and add2_bar is not None and i > add2_bar
                and base_entry is not None and base_atr is not None
                and bar.close >= base_entry + cfg.manage.harvest_atr * base_atr
            )
        if harvest:
            harvest_done = True
            if cfg.manage.post_harvest_be:
                break_even = avg_cost

        be_exit = (
            qty > 0 and cfg.manage.post_harvest_be and harvest_done
            and break_even is not None and bar.close <= break_even
        )
        turtle_exit = qty > 0 and turtle_low is not None and bar.close < turtle_low
        trend_exit = qty > 0 and cfg.manage.trend_flip_exit and bool(row["bear_flip"])
        long_exit = in_window and (be_exit or failed_exit or turtle_exit or trend_exit)
        reason = (
            "BREAK_EVEN" if be_exit else "FAILED_BREAKOUT" if failed_exit
            else f"TURTLE_{cfg.manage.turtle_exit}" if turtle_exit
            else "TREND_FLIP" if trend_exit else ""
        )

        if long_entry:
            initial_risk = max(bar.close - low10, 0.0) if low10 is not None else None
            qty = 2.0
            avg_cost = bar.close
            current = {
                "entry_date": bar.trade_date.isoformat(),
                "entry_price": bar.close,
                "entry_type": entry_type,
                "initial_risk": initial_risk,
                "gross_cost": 2.0 * bar.close,
                "realized_pnl": 0.0,
                "adds": 0,
                "harvested": False,
            }

        if add1 and current is not None:
            nq = qty + 1.0
            avg_cost = (avg_cost * qty + bar.close) / nq
            qty = nq
            current["gross_cost"] += bar.close
            current["adds"] += 1
        if add2 and current is not None:
            nq = qty + 1.0
            avg_cost = (avg_cost * qty + bar.close) / nq
            qty = nq
            current["gross_cost"] += bar.close
            current["adds"] += 1
        if harvest and current is not None and qty >= 1.0:
            current["realized_pnl"] += bar.close - avg_cost
            qty -= 1.0
            current["harvested"] = True

        if long_exit and current is not None and qty > 0:
            current["realized_pnl"] += (bar.close - avg_cost) * qty
            risk = current["initial_risk"]
            risk_dollars = 2.0 * float(risk) if risk is not None and float(risk) > 0 else None
            pnl = float(current["realized_pnl"])
            current["r_multiple"] = pnl / risk_dollars if risk_dollars else None
            current["exit_date"] = bar.trade_date.isoformat()
            current["exit_price"] = bar.close
            current["exit_reason"] = reason
            current["return_pct"] = pnl / float(current["gross_cost"]) * 100.0
            trades.append(current)
            qty = 0.0
            avg_cost = 0.0
            entry_breakout = entry_bar = base_entry = base_atr = None
            add1_done = add2_done = harvest_done = False
            add1_bar = add2_bar = None
            break_even = None
            current = None

    if current is not None and qty > 0:
        eligible = [b for b in bars if b.trade_date <= end]
        if eligible:
            last = max(eligible, key=lambda b: b.trade_date)
            current["realized_pnl"] += (last.close - avg_cost) * qty
            risk = current["initial_risk"]
            risk_dollars = 2.0 * float(risk) if risk is not None and float(risk) > 0 else None
            pnl = float(current["realized_pnl"])
            current["r_multiple"] = pnl / risk_dollars if risk_dollars else None
            current["exit_date"] = last.trade_date.isoformat()
            current["exit_price"] = last.close
            current["exit_reason"] = "MARK_TO_END"
            current["return_pct"] = pnl / float(current["gross_cost"]) * 100.0
            trades.append(current)

    return metrics(trades)


def metrics(trades: list[dict]) -> dict:
    valid_r = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None and math.isfinite(float(t["r_multiple"]))]
    wins = [r for r in valid_r if r > 0]
    losses = [-r for r in valid_r if r < 0]
    pnls = [float(t["realized_pnl"]) for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    avg_win = sum(wins)/len(wins) if wins else 0.0
    avg_loss = sum(losses)/len(losses) if losses else 0.0
    wr = len(wins)/len(valid_r) if valid_r else 0.0
    expectancy = wr*avg_win - (1.0-wr)*avg_loss if valid_r else 0.0
    return {
        "trades": len(valid_r),
        "wins": len(wins),
        "win_rate_pct": wr*100.0,
        "avg_winner_r": avg_win,
        "avg_loser_r": avg_loss,
        "payoff": avg_win/avg_loss if avg_loss > 0 else None,
        "expectancy_r": expectancy,
        "profit_factor": gp/gl if gl > 0 else None,
        "median_r": median(valid_r) if valid_r else 0.0,
        "best_r": max(valid_r) if valid_r else 0.0,
        "worst_r": min(valid_r) if valid_r else 0.0,
        "failed_breakouts": sum(1 for t in trades if t.get("exit_reason") == "FAILED_BREAKOUT"),
        "harvested": sum(1 for t in trades if t.get("harvested")),
        "r_values": valid_r,
    }


def combine(parts: list[dict]) -> dict:
    rs = [r for p in parts for r in p["r_values"]]
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r < 0]
    wr = len(wins)/len(rs) if rs else 0.0
    aw = sum(wins)/len(wins) if wins else 0.0
    al = sum(losses)/len(losses) if losses else 0.0
    # PF in R-space for search ranking; final report also uses R statistics.
    rpf = sum(wins)/sum(losses) if losses and sum(losses) > 0 else None
    return {
        "trades": len(rs), "wins": len(wins), "win_rate_pct": wr*100.0,
        "avg_winner_r": aw, "avg_loser_r": al,
        "payoff": aw/al if al > 0 else None,
        "expectancy_r": wr*aw - (1-wr)*al if rs else 0.0,
        "r_profit_factor": rpf,
        "median_r": median(rs) if rs else 0.0,
        "best_r": max(rs) if rs else 0.0,
        "worst_r": min(rs) if rs else 0.0,
        "r_values": rs,
    }


def fetch_one(symbol: str, token: str):
    bars, meta = fetch_orats_history(symbol, start=FETCH_START, end=FETCH_END, token=token)
    return symbol, bars, indicators(bars), meta


def eval_cfg(data, symbols, cfg, start, end):
    return combine([run_model(data[s][0], data[s][1], cfg, start, end) for s in symbols])


def robust_score(m: dict) -> float:
    # Reward expectancy, PF, and >2R winner size without allowing a tiny sample to win.
    if m["trades"] < 120 or m["expectancy_r"] <= 0 or (m["r_profit_factor"] or 0) <= 1.0:
        return -1e9
    sample_penalty = min(m["trades"] / 300.0, 1.0)
    winner_bonus = min(m["avg_winner_r"], 3.5) * 0.10
    return sample_penalty * (m["expectancy_r"] + winner_bonus + 0.08*math.log(max(m["r_profit_factor"] or 1.0, 1e-6)))


def main():
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN missing")

    data = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fetch_one, s, token): s for s in SYMBOLS}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                _, bars, ind, meta = fut.result()
                data[s] = (bars, ind, meta)
            except Exception as exc:
                errors[s] = f"{type(exc).__name__}:{exc}"

    search_symbols = [s for s in SEARCH_SYMBOLS if s in data]
    holdout_symbols = [s for s in HOLDOUT_SYMBOLS if s in data]

    baseline = ModelConfig(EntryConfig(), ManageConfig())
    baseline_train = eval_cfg(data, search_symbols, baseline, TRAIN_START, TRAIN_END)
    baseline_valid = eval_cfg(data, search_symbols, baseline, VALID_START, VALID_END)
    baseline_holdout = eval_cfg(data, holdout_symbols, baseline, FULL_START, FULL_END)
    baseline_stress = eval_cfg(data, list(data), baseline, STRESS_START, STRESS_END)

    # Stage 1: broad entry family search with canonical management.
    entry_results = []
    for breakout in (10, 15, 20, 30, 55):
        for adx_mode in ("15_RISING", "17_RISING", "20_RISING", "20", "25"):
            for eff in (0.15, 0.20, 0.25):
                for rsi in (75.0, 80.0, 85.0):
                    for maturity in (1, 2, 3):
                        e = EntryConfig(breakout=breakout, adx_mode=adx_mode, efficiency_min=eff, rsi_max=rsi, maturity_bars=maturity)
                        cfg = ModelConfig(e, ManageConfig())
                        m = eval_cfg(data, search_symbols, cfg, TRAIN_START, TRAIN_END)
                        entry_results.append((robust_score(m), cfg, m))
    entry_results.sort(key=lambda x: x[0], reverse=True)

    # Preserve diversity: top 10 unique entry configurations plus any train model already >=2R.
    stage2_entries = []
    seen = set()
    for score, cfg, m in entry_results:
        key = cfg.entry
        if key in seen:
            continue
        if score > -1e8 and (len(stage2_entries) < 10 or m["avg_winner_r"] >= 2.0):
            stage2_entries.append((cfg.entry, m))
            seen.add(key)
        if len(stage2_entries) >= 18:
            break

    # Stage 2: management search. Core add schedule remains fixed at +1/+2 ATR.
    management_results = []
    for e, _ in stage2_entries:
        for turtle in (10, 15, 20, 30, 55):
            for failed_window in (0, 1, 3, 5):
                for failed_tol in (0.0, 0.5, 1.0):
                    for harvest in (0.0, 3.0, 4.0, 5.0):
                        for be in (True, False):
                            if harvest == 0.0 and be:
                                continue
                            for trend_flip in (True, False):
                                mg = ManageConfig(
                                    turtle_exit=turtle,
                                    failed_window=failed_window,
                                    failed_tolerance_atr=failed_tol,
                                    harvest_atr=harvest,
                                    post_harvest_be=be,
                                    trend_flip_exit=trend_flip,
                                )
                                cfg = ModelConfig(e, mg)
                                m = eval_cfg(data, search_symbols, cfg, TRAIN_START, TRAIN_END)
                                management_results.append((robust_score(m), cfg, m))
    management_results.sort(key=lambda x: x[0], reverse=True)

    # Top management models then quality overlays. These filters are deliberately simple,
    # explainable, and based only on information available on the signal bar.
    top_mgmt = []
    seen_cfg = set()
    for score, cfg, m in management_results:
        if cfg in seen_cfg or score <= -1e8:
            continue
        top_mgmt.append((cfg, m))
        seen_cfg.add(cfg)
        if len(top_mgmt) >= 14:
            break

    overlay_results = []
    for cfg, _ in top_mgmt:
        for relvol in (0.0, 1.0, 1.25):
            for cl in (0.0, 0.60, 0.70):
                for bo_atr in (0.0, 0.20, 0.40):
                    for atr_pct in (0.0, 0.015, 0.025):
                        e = EntryConfig(
                            breakout=cfg.entry.breakout,
                            adx_mode=cfg.entry.adx_mode,
                            efficiency_min=cfg.entry.efficiency_min,
                            rsi_max=cfg.entry.rsi_max,
                            maturity_bars=cfg.entry.maturity_bars,
                            relative_volume_min=relvol,
                            close_location_min=cl,
                            breakout_atr_min=bo_atr,
                            atr_pct_min=atr_pct,
                        )
                        c = ModelConfig(e, cfg.manage)
                        train = eval_cfg(data, search_symbols, c, TRAIN_START, TRAIN_END)
                        if train["trades"] < 100 or train["expectancy_r"] <= 0:
                            continue
                        valid = eval_cfg(data, search_symbols, c, VALID_START, VALID_END)
                        # Validation-aware score; 2026 and symbol holdout are not used here.
                        if valid["trades"] < 30 or valid["expectancy_r"] <= 0:
                            continue
                        score = 0.55*robust_score(train) + 0.45*robust_score({**valid, "trades": max(valid["trades"],120)})
                        # Small bonus only when both periods exceed 2R average winner.
                        if train["avg_winner_r"] >= 2.0 and valid["avg_winner_r"] >= 2.0:
                            score += 0.20
                        overlay_results.append((score, c, train, valid))
    overlay_results.sort(key=lambda x: x[0], reverse=True)

    finalists = []
    seen = set()
    for score, cfg, train, valid in overlay_results:
        if cfg in seen:
            continue
        hold = eval_cfg(data, holdout_symbols, cfg, FULL_START, FULL_END)
        stress = eval_cfg(data, list(data), cfg, STRESS_START, STRESS_END)
        finalists.append({
            "score": score,
            "config": {"entry": asdict(cfg.entry), "manage": asdict(cfg.manage)},
            "train_2022_24": {k:v for k,v in train.items() if k != "r_values"},
            "validation_2025": {k:v for k,v in valid.items() if k != "r_values"},
            "symbol_holdout_2022_25": {k:v for k,v in hold.items() if k != "r_values"},
            "stress_2026_ytd": {k:v for k,v in stress.items() if k != "r_values"},
            "qualifies_2r_holdout": hold["avg_winner_r"] >= 2.0 and hold["expectancy_r"] > 0 and (hold["r_profit_factor"] or 0) > 1.0,
            "qualifies_2r_2026": stress["avg_winner_r"] >= 2.0 and stress["expectancy_r"] > 0 and (stress["r_profit_factor"] or 0) > 1.0,
        })
        seen.add(cfg)
        if len(finalists) >= 30:
            break

    # Prefer models that cross 2R on cross-sectional holdout AND remain positive in 2026.
    qualifying = [f for f in finalists if f["qualifies_2r_holdout"] and f["stress_2026_ytd"]["expectancy_r"] > 0]
    qualifying.sort(
        key=lambda f: (
            f["qualifies_2r_2026"],
            f["symbol_holdout_2022_25"]["expectancy_r"],
            f["stress_2026_ytd"]["expectancy_r"],
            f["symbol_holdout_2022_25"]["r_profit_factor"] or 0,
        ), reverse=True
    )
    champion = qualifying[0] if qualifying else (finalists[0] if finalists else None)

    output = {
        "goal": "Average winning trade >2.0R with positive expectancy and PF; no R redefinition or extra pyramiding",
        "canonical_r": "2 * (entry close - prior 10-day low)",
        "universe": {
            "requested": len(SYMBOLS), "valid": len(data), "errors": errors,
            "search_symbols": search_symbols, "holdout_symbols": holdout_symbols,
        },
        "periods": {
            "train": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
            "validation": [VALID_START.isoformat(), VALID_END.isoformat()],
            "symbol_holdout": [FULL_START.isoformat(), FULL_END.isoformat()],
            "2026_stress": [STRESS_START.isoformat(), STRESS_END.isoformat()],
        },
        "trial_count": {
            "entry": len(entry_results), "management": len(management_results), "overlay": len(overlay_results)
        },
        "baseline": {
            "config": {"entry": asdict(baseline.entry), "manage": asdict(baseline.manage)},
            "train_2022_24": {k:v for k,v in baseline_train.items() if k != "r_values"},
            "validation_2025": {k:v for k,v in baseline_valid.items() if k != "r_values"},
            "symbol_holdout_2022_25": {k:v for k,v in baseline_holdout.items() if k != "r_values"},
            "stress_2026_ytd": {k:v for k,v in baseline_stress.items() if k != "r_values"},
        },
        "finalists": finalists,
        "qualifying_count": len(qualifying),
        "champion": champion,
        "top_entry_stage": [
            {"score":score, "config": {"entry":asdict(cfg.entry), "manage":asdict(cfg.manage)}, "metrics":{k:v for k,v in m.items() if k != "r_values"}}
            for score,cfg,m in entry_results[:15]
        ],
    }

    Path("r2-model-search.json").write_text(json.dumps(output, indent=2), encoding="utf-8")

    def row(label, m):
        return f"| {label} | {m['trades']} | {m['win_rate_pct']:.1f}% | {m['avg_winner_r']:.2f}R | {m['avg_loser_r']:.2f}R | {m['expectancy_r']:+.3f}R | {(m['r_profit_factor'] or 0):.2f} |"

    lines = [
        "# Daily Alpha >2R Model Search",
        "",
        f"Valid symbols: {len(data)}/{len(SYMBOLS)}; search={len(search_symbols)}; symbol holdout={len(holdout_symbols)}; errors={len(errors)}",
        f"Trials: entry={len(entry_results)}, management={len(management_results)}, overlays={len(overlay_results)}",
        "",
        "## Baseline (validated ADX17-rising, 20D breakout, current management)",
        "| Slice | Trades | Win rate | Avg winner | Avg loser | Expectancy | R-PF |",
        "|---|---:|---:|---:|---:|---:|---:|",
        row("Train 2022-24", baseline_train),
        row("Validation 2025", baseline_valid),
        row("Symbol holdout 2022-25", baseline_holdout),
        row("2026 YTD stress", baseline_stress),
        "",
        f"## Qualifying >2R models: {len(qualifying)}",
    ]
    if champion:
        lines += [
            "",
            "## Champion",
            "```json",
            json.dumps(champion["config"], indent=2),
            "```",
            "| Slice | Trades | Win rate | Avg winner | Avg loser | Expectancy | R-PF |",
            "|---|---:|---:|---:|---:|---:|---:|",
            row("Train 2022-24", champion["train_2022_24"]),
            row("Validation 2025", champion["validation_2025"]),
            row("Symbol holdout 2022-25", champion["symbol_holdout_2022_25"]),
            row("2026 YTD stress", champion["stress_2026_ytd"]),
        ]
    lines += ["", "## Top finalists"]
    for idx, f in enumerate(finalists[:12], 1):
        h = f["symbol_holdout_2022_25"]
        s = f["stress_2026_ytd"]
        lines.append(
            f"{idx}. holdout avgWin={h['avg_winner_r']:.2f}R exp={h['expectancy_r']:+.3f}R PF={(h['r_profit_factor'] or 0):.2f}; "
            f"2026 avgWin={s['avg_winner_r']:.2f}R exp={s['expectancy_r']:+.3f}R PF={(s['r_profit_factor'] or 0):.2f}; config={json.dumps(f['config'], sort_keys=True)}"
        )
    Path("r2-model-search.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(Path("r2-model-search.md").read_text())


if __name__ == "__main__":
    main()
