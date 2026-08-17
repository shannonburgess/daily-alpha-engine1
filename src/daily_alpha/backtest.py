"""Event-aware Daily Alpha v2.3 vs v2.4 historical backtest.

Uses ORATS daily OHLCV and earnings history. This runner is research-only and
does not place, route, or authorize trades.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CANONICAL_GAP_GO_CLOSE_LOCATION = 0.70
EARLY_GAP_GO_CLOSE_LOCATION = 0.60


@dataclass
class Bar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    earnings_event: bool = False


@dataclass
class Trade:
    version: str
    entry_type: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    units_bought: float
    realized_pnl: float
    gross_entry_cost: float
    return_pct: float
    r_multiple: float | None
    exit_reason: str
    adds: int
    harvested: bool


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def gap_go_close_location_band(close_location: float) -> str:
    """Classify the canonical v2.4 close-location band.

    FULL is paper/backtest eligible when all other Gap & Go quality gates pass.
    EARLY is research/watch-only and must never authorize an entry by itself.
    """
    if close_location >= CANONICAL_GAP_GO_CLOSE_LOCATION:
        return "FULL"
    if close_location >= EARLY_GAP_GO_CLOSE_LOCATION:
        return "EARLY"
    return "BELOW"


def _request_json(url: str, *, token: str, header_auth: bool) -> Any:
    headers = {"Accept": "application/json"}
    if header_auth:
        headers["Authorization"] = token
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read(400).decode("utf-8", errors="replace")
        raise RuntimeError(f"ORATS HTTP {exc.code}: {body[:200]}") from exc
    except URLError as exc:
        raise RuntimeError(f"ORATS network error: {type(exc.reason).__name__}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ORATS returned invalid JSON") from exc


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [r for r in payload["data"] if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    raise RuntimeError("Unexpected ORATS response shape")


def fetch_orats_history(
    ticker: str,
    *,
    start: date,
    end: date,
    token: str,
) -> tuple[list[Bar], list[dict[str, Any]]]:
    warm_start = start - timedelta(days=730)
    base = "https://api.orats.io/data"
    daily_query = urlencode(
        {
            "tickers": ticker,
            "tradeDate": f"{warm_start.isoformat()},{end.isoformat()}",
            "fields[dailies]": "ticker,tradeDate,clsPx,hiPx,loPx,open,stockVolume",
        }
    )
    earnings_query = urlencode(
        {
            "tickers": ticker,
            "fields[earnings]": "ticker,earnDate,anncTod",
        }
    )
    try:
        daily_payload = _request_json(
            f"{base}/hist/dailies?{daily_query}", token=token, header_auth=True
        )
        earnings_payload = _request_json(
            f"{base}/hist/earnings?{earnings_query}", token=token, header_auth=True
        )
        source = "ORATS_DATA_API"
    except RuntimeError:
        # Compatibility fallback for accounts provisioned on the datav2 route.
        base2 = "https://api.orats.io/datav2"
        daily_query2 = urlencode(
            {
                "token": token,
                "ticker": ticker,
                "fields": "ticker,tradeDate,clsPx,hiPx,loPx,open,stockVolume",
            }
        )
        earnings_query2 = urlencode({"token": token, "ticker": ticker})
        daily_payload = _request_json(
            f"{base2}/hist/dailies?{daily_query2}", token=token, header_auth=False
        )
        earnings_payload = _request_json(
            f"{base2}/hist/earnings?{earnings_query2}", token=token, header_auth=False
        )
        source = "ORATS_DATAV2_API"

    earnings = _rows(earnings_payload)
    earnings_dates = {
        date.fromisoformat(str(row["earnDate"])[:10])
        for row in earnings
        if row.get("earnDate")
    }

    bars: list[Bar] = []
    for row in _rows(daily_payload):
        raw_date = row.get("tradeDate")
        if not raw_date:
            continue
        trade_date = date.fromisoformat(str(raw_date)[:10])
        if trade_date < warm_start or trade_date > end:
            continue
        opn = _number(row.get("open"))
        high = _number(row.get("hiPx"))
        low = _number(row.get("loPx"))
        close = _number(row.get("clsPx"))
        volume = _number(row.get("stockVolume"))
        if min(opn, high, low, close) <= 0:
            continue
        bars.append(
            Bar(
                trade_date=trade_date,
                open=opn,
                high=high,
                low=low,
                close=close,
                volume=volume,
                earnings_event=trade_date in earnings_dates,
            )
        )
    bars.sort(key=lambda b: b.trade_date)
    if len(bars) < 80:
        raise RuntimeError(f"Insufficient ORATS bars for {ticker}: {len(bars)}")
    return bars, [{"source": source, **row} for row in earnings]


def sma(values: list[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(float(v) for v in window) / length
    return out


def rma(values: list[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    seed_vals: list[float] = []
    seed_idx = None
    for i, value in enumerate(values):
        if value is None:
            continue
        seed_vals.append(float(value))
        if len(seed_vals) == length:
            seed_idx = i
            out[i] = sum(seed_vals) / length
            break
    if seed_idx is None:
        return out
    prev = out[seed_idx]
    assert prev is not None
    alpha = 1.0 / length
    for i in range(seed_idx + 1, len(values)):
        value = values[i]
        if value is None:
            out[i] = prev
            continue
        prev = alpha * float(value) + (1.0 - alpha) * prev
        out[i] = prev
    return out


def indicators(bars: list[Bar]) -> list[dict[str, Any]]:
    n = len(bars)
    close = [b.close for b in bars]
    high = [b.high for b in bars]
    low = [b.low for b in bars]
    volume = [b.volume for b in bars]

    changes: list[float | None] = [None]
    abs_changes: list[float | None] = [None]
    ups: list[float | None] = [None]
    downs: list[float | None] = [None]
    tr: list[float | None] = []
    plus_dm: list[float | None] = [None]
    minus_dm: list[float | None] = [None]
    for i in range(n):
        if i == 0:
            tr.append(high[i] - low[i])
            continue
        chg = close[i] - close[i - 1]
        changes.append(chg)
        abs_changes.append(abs(chg))
        ups.append(max(chg, 0.0))
        downs.append(max(-chg, 0.0))
        tr.append(
            max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        )
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    atr = rma(tr, 10)
    avg_gain = rma(ups, 14)
    avg_loss = rma(downs, 14)
    rsi: list[float | None] = [None] * n
    for i in range(n):
        if avg_gain[i] is None or avg_loss[i] is None:
            continue
        if avg_loss[i] == 0:
            rsi[i] = 100.0
        else:
            rs = float(avg_gain[i]) / float(avg_loss[i])
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    tr14 = rma(tr, 14)
    pdm14 = rma(plus_dm, 14)
    mdm14 = rma(minus_dm, 14)
    plus_di: list[float | None] = [None] * n
    minus_di: list[float | None] = [None] * n
    dx: list[float | None] = [None] * n
    for i in range(n):
        if tr14[i] in (None, 0) or pdm14[i] is None or mdm14[i] is None:
            continue
        plus_di[i] = 100.0 * float(pdm14[i]) / float(tr14[i])
        minus_di[i] = 100.0 * float(mdm14[i]) / float(tr14[i])
        denom = float(plus_di[i]) + float(minus_di[i])
        dx[i] = (
            0.0
            if denom == 0
            else 100.0 * abs(float(plus_di[i]) - float(minus_di[i])) / denom
        )
    adx = rma(dx, 14)

    path_sma = sma(abs_changes, 20)
    volume_sma = sma([float(v) for v in volume], 20)

    rows: list[dict[str, Any]] = []
    final_upper_prev: float | None = None
    final_lower_prev: float | None = None
    trend_prev = 1
    bull_bars_prev = 0

    for i, bar in enumerate(bars):
        upper20 = max(high[i - 20 : i]) if i >= 20 else None
        lower10 = min(low[i - 10 : i]) if i >= 10 else None

        efficiency = None
        adaptive_factor = None
        if i >= 20 and path_sma[i] is not None:
            path_length = float(path_sma[i]) * 20.0
            direction = abs(close[i] - close[i - 20])
            efficiency = min(direction / path_length, 1.0) if path_length > 0 else 0.0
            adaptive_factor = 4.0 - efficiency * 2.0

        final_upper = None
        final_lower = None
        trend_state = trend_prev
        bear_flip = False
        if atr[i] is not None and adaptive_factor is not None:
            basic_upper = (high[i] + low[i]) / 2.0 + float(atr[i]) * adaptive_factor
            basic_lower = (high[i] + low[i]) / 2.0 - float(atr[i]) * adaptive_factor
            if final_upper_prev is None:
                final_upper = basic_upper
            else:
                final_upper = (
                    basic_upper
                    if basic_upper < final_upper_prev or close[i - 1] > final_upper_prev
                    else final_upper_prev
                )
            if final_lower_prev is None:
                final_lower = basic_lower
            else:
                final_lower = (
                    basic_lower
                    if basic_lower > final_lower_prev or close[i - 1] < final_lower_prev
                    else final_lower_prev
                )

            if final_upper_prev is not None and final_lower_prev is not None:
                if trend_prev == -1 and close[i] > final_upper_prev:
                    trend_state = 1
                elif trend_prev == 1 and close[i] < final_lower_prev:
                    trend_state = -1
            bear_flip = trend_state == -1 and trend_prev == 1

        bull_bars = bull_bars_prev + 1 if trend_state == 1 else 0
        normal_trend_mature = bull_bars_prev >= 2

        breakout_now = upper20 is not None and close[i] > upper20
        breakout_prev = False
        if i >= 21:
            prev_upper20 = max(high[i - 21 : i - 1])
            breakout_prev = close[i - 1] > prev_upper20
        fresh_breakout = breakout_now and not breakout_prev

        earnings_window = bar.earnings_event or (i > 0 and bars[i - 1].earnings_event)
        prev_close = close[i - 1] if i > 0 else None
        prev_atr = atr[i - 1] if i > 0 else None
        gap_dollars = (bar.open - prev_close) if prev_close is not None else 0.0
        gap_pct = gap_dollars / prev_close * 100.0 if prev_close and prev_close > 0 else 0.0
        gap_atr = gap_dollars / float(prev_atr) if prev_atr and prev_atr > 0 else 0.0
        day_range = bar.high - bar.low
        close_location = (bar.close - bar.low) / day_range if day_range > 0 else 0.0
        gap_retention = (
            (bar.close - prev_close) / gap_dollars
            if prev_close is not None and gap_dollars > 0
            else 0.0
        )
        avg_vol_prior = volume_sma[i - 1] if i > 0 else None
        relative_volume = (
            bar.volume / float(avg_vol_prior) if avg_vol_prior and avg_vol_prior > 0 else 0.0
        )

        is_earnings_up_gap = (
            earnings_window and gap_dollars > 0 and (gap_pct >= 5.0 or gap_atr >= 1.5)
        )
        earnings_breakout = upper20 is not None and bar.close > upper20
        close_location_band = gap_go_close_location_band(close_location)
        gap_go_core_quality = (
            bar.close >= bar.open
            and gap_retention >= 0.70
            and relative_volume >= 1.5
            and rsi[i] is not None
            and float(rsi[i]) <= 85.0
            and trend_state == 1
            and earnings_breakout
        )
        gap_go = (
            is_earnings_up_gap
            and close_location_band == "FULL"
            and gap_go_core_quality
        )
        gap_go_early = (
            is_earnings_up_gap
            and close_location_band == "EARLY"
            and gap_go_core_quality
        )
        gap_crap = (
            is_earnings_up_gap
            and not gap_go
            and not gap_go_early
            and (
                (prev_close is not None and bar.close < prev_close)
                or gap_retention < 0.50
                or (bar.close < bar.open and close_location < 0.50)
            )
        )
        gap_wait = (
            is_earnings_up_gap
            and not gap_go
            and not gap_go_early
            and not gap_crap
        )

        rows.append(
            {
                "atr": atr[i],
                "rsi": rsi[i],
                "adx": adx[i],
                "efficiency": efficiency,
                "upper20": upper20,
                "lower10": lower10,
                "fresh_breakout": fresh_breakout,
                "trend_state": trend_state,
                "bear_flip": bear_flip,
                "normal_trend_mature": normal_trend_mature,
                "earnings_window": earnings_window,
                "gap_dollars": gap_dollars,
                "gap_pct": gap_pct,
                "gap_atr": gap_atr,
                "close_location": close_location,
                "gap_retention": gap_retention,
                "relative_volume": relative_volume,
                "is_earnings_up_gap": is_earnings_up_gap,
                "gap_go": gap_go,
                "gap_go_early": gap_go_early,
                "gap_crap": gap_crap,
                "gap_wait": gap_wait,
            }
        )

        if final_upper is not None:
            final_upper_prev = final_upper
        if final_lower is not None:
            final_lower_prev = final_lower
        trend_prev = trend_state
        bull_bars_prev = bull_bars

    return rows


def run_strategy(
    bars: list[Bar],
    ind: list[dict[str, Any]],
    *,
    version: str,
    start: date,
    end: date,
) -> tuple[list[Trade], list[dict[str, Any]]]:
    if version not in {"2.3", "2.4"}:
        raise ValueError("version must be 2.3 or 2.4")

    position_qty = 0.0
    avg_cost = 0.0
    entry_breakout_level: float | None = None
    entry_signal_bar: int | None = None
    runner_base_entry: float | None = None
    runner_base_atr: float | None = None
    add1_done = False
    add2_done = False
    harvest_done = False
    add1_bar: int | None = None
    add2_bar: int | None = None
    break_even_level: float | None = None

    current: dict[str, Any] | None = None
    trades: list[Trade] = []
    events: list[dict[str, Any]] = []

    for i, (bar, row) in enumerate(zip(bars, ind)):
        in_window = start <= bar.trade_date <= end
        flat_at_start = position_qty == 0
        price_ok = bar.close >= 25.0
        eff_ok = row["efficiency"] is not None and float(row["efficiency"]) >= 0.20
        rsi_ok = row["rsi"] is not None and float(row["rsi"]) <= 80.0
        adx_ok = row["adx"] is not None and float(row["adx"]) >= 25.0

        if version == "2.3":
            base_setup = (
                in_window
                and flat_at_start
                and row["fresh_breakout"]
                and row["trend_state"] == 1
            )
            long_entry = base_setup and price_ok and eff_ok and rsi_ok and adx_ok
            entry_type = "NORMAL_BREAKOUT" if long_entry else "NONE"
        else:
            normal_setup = (
                in_window
                and flat_at_start
                and row["fresh_breakout"]
                and not row["is_earnings_up_gap"]
                and row["trend_state"] == 1
                and row["normal_trend_mature"]
            )
            normal_entry = normal_setup and price_ok and eff_ok and rsi_ok and adx_ok
            gap_entry = (
                in_window
                and flat_at_start
                and row["gap_go"]
                and row["fresh_breakout"]
                and price_ok
            )
            long_entry = normal_entry or gap_entry
            entry_type = (
                "EARNINGS_GAP_GO"
                if gap_entry
                else "NORMAL_BREAKOUT"
                if normal_entry
                else "NONE"
            )

        if row["is_earnings_up_gap"] and in_window:
            classification = (
                "EARNINGS_GAP_GO"
                if row["gap_go"]
                else "EARNINGS_GAP_GO_EARLY"
                if row.get("gap_go_early", False)
                else "EARNINGS_GAP_CRAP"
                if row["gap_crap"]
                else "EARNINGS_WAIT"
            )
            events.append(
                {
                    "date": bar.trade_date.isoformat(),
                    "classification": classification,
                    "gap_pct": round(float(row["gap_pct"]), 2),
                    "gap_atr": round(float(row["gap_atr"]), 2),
                    "close_location": round(float(row["close_location"]), 2),
                    "gap_retention": round(float(row["gap_retention"]), 2),
                    "relative_volume": round(float(row["relative_volume"]), 2),
                    "fresh_breakout": bool(row["fresh_breakout"]),
                    "adx": None if row["adx"] is None else round(float(row["adx"]), 2),
                    "rsi": None if row["rsi"] is None else round(float(row["rsi"]), 2),
                    "v23_entry": bool(version == "2.3" and long_entry),
                    "v24_entry": bool(version == "2.4" and long_entry),
                }
            )

        # Pine mutates entry variables on the signal bar before later signal expressions.
        if long_entry:
            entry_breakout_level = float(row["upper20"])
            entry_signal_bar = i
            runner_base_entry = bar.close
            runner_base_atr = float(row["atr"]) if row["atr"] is not None else None
            add1_done = False
            add2_done = False
            harvest_done = False
            add1_bar = None
            add2_bar = None
            break_even_level = None

        bars_since_entry = i - entry_signal_bar if entry_signal_bar is not None else None
        failed_exit = (
            position_qty > 0
            and entry_breakout_level is not None
            and bars_since_entry is not None
            and 1 <= bars_since_entry <= 3
            and bar.close < entry_breakout_level
        )
        runner_trend_ok = row["trend_state"] == 1 and adx_ok
        add1_signal = (
            position_qty > 0
            and not add1_done
            and runner_base_entry is not None
            and runner_base_atr is not None
            and runner_trend_ok
            and bar.close >= runner_base_entry + runner_base_atr
        )
        if add1_signal:
            add1_done = True
            add1_bar = i

        add2_signal = (
            position_qty > 0
            and add1_done
            and not add2_done
            and add1_bar is not None
            and i > add1_bar
            and runner_base_entry is not None
            and runner_base_atr is not None
            and runner_trend_ok
            and bar.close >= runner_base_entry + 2.0 * runner_base_atr
        )
        if add2_signal:
            add2_done = True
            add2_bar = i

        harvest_signal = (
            position_qty > 0
            and add2_done
            and not harvest_done
            and add2_bar is not None
            and i > add2_bar
            and runner_base_entry is not None
            and runner_base_atr is not None
            and bar.close >= runner_base_entry + 3.0 * runner_base_atr
        )
        if harvest_signal:
            break_even_level = avg_cost
            harvest_done = True

        break_even_exit = (
            position_qty > 0
            and harvest_done
            and break_even_level is not None
            and bar.close <= break_even_level
        )
        turtle_exit = (
            position_qty > 0
            and row["lower10"] is not None
            and bar.close < float(row["lower10"])
        )
        trend_exit = position_qty > 0 and bool(row["bear_flip"])
        long_exit = in_window and (break_even_exit or failed_exit or turtle_exit or trend_exit)

        exit_reason = ""
        if break_even_exit:
            exit_reason = "BREAK_EVEN"
        elif failed_exit:
            exit_reason = "FAILED_BREAKOUT"
        elif turtle_exit:
            exit_reason = "TURTLE_10"
        elif trend_exit:
            exit_reason = "TREND_FLIP"

        # Orders execute at the close, matching process_orders_on_close=true.
        if long_entry:
            qty = 2.0
            position_qty = qty
            avg_cost = bar.close
            initial_risk = (
                max(bar.close - float(row["lower10"]), 0.0)
                if row["lower10"] is not None
                else None
            )
            current = {
                "entry_type": entry_type,
                "entry_date": bar.trade_date.isoformat(),
                "entry_price": bar.close,
                "units_bought": qty,
                "gross_entry_cost": qty * bar.close,
                "realized_pnl": 0.0,
                "initial_risk": initial_risk,
                "adds": 0,
                "harvested": False,
            }

        if add1_signal and current is not None:
            qty = 1.0
            new_qty = position_qty + qty
            avg_cost = (avg_cost * position_qty + bar.close * qty) / new_qty
            position_qty = new_qty
            current["units_bought"] += qty
            current["gross_entry_cost"] += qty * bar.close
            current["adds"] += 1

        if add2_signal and current is not None:
            qty = 1.0
            new_qty = position_qty + qty
            avg_cost = (avg_cost * position_qty + bar.close * qty) / new_qty
            position_qty = new_qty
            current["units_bought"] += qty
            current["gross_entry_cost"] += qty * bar.close
            current["adds"] += 1

        if harvest_signal and current is not None and position_qty >= 1.0:
            qty = 1.0
            current["realized_pnl"] += (bar.close - avg_cost) * qty
            position_qty -= qty
            current["harvested"] = True

        if long_exit and current is not None and position_qty > 0:
            current["realized_pnl"] += (bar.close - avg_cost) * position_qty
            position_qty = 0.0
            gross = float(current["gross_entry_cost"])
            pnl = float(current["realized_pnl"])
            initial_risk = current["initial_risk"]
            risk_dollars = (
                2.0 * float(initial_risk)
                if initial_risk is not None and float(initial_risk) > 0
                else None
            )
            trades.append(
                Trade(
                    version=version,
                    entry_type=str(current["entry_type"]),
                    entry_date=str(current["entry_date"]),
                    exit_date=bar.trade_date.isoformat(),
                    entry_price=float(current["entry_price"]),
                    exit_price=bar.close,
                    units_bought=float(current["units_bought"]),
                    realized_pnl=pnl,
                    gross_entry_cost=gross,
                    return_pct=(pnl / gross * 100.0) if gross else 0.0,
                    r_multiple=(pnl / risk_dollars) if risk_dollars else None,
                    exit_reason=exit_reason or "EXIT",
                    adds=int(current["adds"]),
                    harvested=bool(current["harvested"]),
                )
            )
            current = None
            avg_cost = 0.0
            entry_breakout_level = None
            entry_signal_bar = None
            runner_base_entry = None
            runner_base_atr = None
            add1_done = False
            add2_done = False
            harvest_done = False
            add1_bar = None
            add2_bar = None
            break_even_level = None

        if (
            position_qty == 0
            and not long_entry
            and entry_signal_bar is not None
            and i > entry_signal_bar + 3
        ):
            entry_breakout_level = None
            entry_signal_bar = None
            runner_base_entry = None
            runner_base_atr = None
            add1_done = False
            add2_done = False
            harvest_done = False
            add1_bar = None
            add2_bar = None
            break_even_level = None

    # Mark an open trade to the final close so the comparison is complete as of end date.
    if current is not None and position_qty > 0:
        last_idx = max(i for i, b in enumerate(bars) if b.trade_date <= end)
        bar = bars[last_idx]
        current["realized_pnl"] += (bar.close - avg_cost) * position_qty
        gross = float(current["gross_entry_cost"])
        pnl = float(current["realized_pnl"])
        initial_risk = current["initial_risk"]
        risk_dollars = (
            2.0 * float(initial_risk)
            if initial_risk is not None and float(initial_risk) > 0
            else None
        )
        trades.append(
            Trade(
                version=version,
                entry_type=str(current["entry_type"]),
                entry_date=str(current["entry_date"]),
                exit_date=bar.trade_date.isoformat(),
                entry_price=float(current["entry_price"]),
                exit_price=bar.close,
                units_bought=float(current["units_bought"]),
                realized_pnl=pnl,
                gross_entry_cost=gross,
                return_pct=(pnl / gross * 100.0) if gross else 0.0,
                r_multiple=(pnl / risk_dollars) if risk_dollars else None,
                exit_reason="MARK_TO_END",
                adds=int(current["adds"]),
                harvested=bool(current["harvested"]),
            )
        )

    return trades, events


def summarize(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "sum_return_pct": 0.0,
            "profit_factor": None,
            "avg_r": None,
            "total_r": 0.0,
            "max_cumulative_r_drawdown": 0.0,
            "gap_go_trades": 0,
            "normal_trades": 0,
        }
    wins = [t for t in trades if t.realized_pnl > 0]
    gross_profit = sum(t.realized_pnl for t in trades if t.realized_pnl > 0)
    gross_loss = -sum(t.realized_pnl for t in trades if t.realized_pnl < 0)
    rs = [
        float(t.r_multiple)
        for t in trades
        if t.r_multiple is not None and math.isfinite(float(t.r_multiple))
    ]
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cumulative += r
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 2),
        "avg_return_pct": round(sum(t.return_pct for t in trades) / len(trades), 2),
        "sum_return_pct": round(sum(t.return_pct for t in trades), 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
        "total_r": round(sum(rs), 2),
        "max_cumulative_r_drawdown": round(max_dd, 2),
        "gap_go_trades": sum(t.entry_type == "EARNINGS_GAP_GO" for t in trades),
        "normal_trades": sum(t.entry_type == "NORMAL_BREAKOUT" for t in trades),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="MRVL")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")

    ticker = args.ticker.strip().upper()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars, earnings = fetch_orats_history(ticker, start=start, end=end, token=token)
    ind = indicators(bars)

    v23, events23 = run_strategy(bars, ind, version="2.3", start=start, end=end)
    v24, events24 = run_strategy(bars, ind, version="2.4", start=start, end=end)
    summary23 = summarize(v23)
    summary24 = summarize(v24)

    event_by_date: dict[str, dict[str, Any]] = {}
    for event in events23:
        event_by_date.setdefault(event["date"], {}).update(
            {k: v for k, v in event.items() if k != "v24_entry"}
        )
    for event in events24:
        existing = event_by_date.setdefault(event["date"], {})
        existing.update({k: v for k, v in event.items() if k != "v23_entry"})

    result = {
        "ticker": ticker,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bars": sum(start <= b.trade_date <= end for b in bars),
        "earnings_records": len(earnings),
        "v2_3": summary23,
        "v2_4": summary24,
        "delta": {
            "trades": summary24["trades"] - summary23["trades"],
            "win_rate_pct_points": round(
                summary24["win_rate_pct"] - summary23["win_rate_pct"], 2
            ),
            "sum_return_pct": round(
                summary24["sum_return_pct"] - summary23["sum_return_pct"], 2
            ),
            "total_r": round(summary24["total_r"] - summary23["total_r"], 2),
            "max_cumulative_r_drawdown": round(
                summary24["max_cumulative_r_drawdown"]
                - summary23["max_cumulative_r_drawdown"],
                2,
            ),
        },
        "earnings_gap_events": list(event_by_date.values()),
        "trades_v2_3": [asdict(t) for t in v23],
        "trades_v2_4": [asdict(t) for t in v24],
    }

    print("DAILY ALPHA EVENT-AWARE BACKTEST")
    print(
        f"{ticker} | {start.isoformat()} to {end.isoformat()} | "
        f"{result['bars']} trading bars"
    )
    print("")
    for label, summary in (("v2.3", summary23), ("v2.4", summary24)):
        print(
            f"{label}: trades={summary['trades']} wins={summary['wins']} "
            f"win_rate={summary['win_rate_pct']:.2f}% "
            f"sum_return={summary['sum_return_pct']:.2f}% "
            f"avg_return={summary['avg_return_pct']:.2f}% "
            f"total_R={summary['total_r']:.2f} "
            f"avg_R={summary['avg_r']} "
            f"profit_factor={summary['profit_factor']} "
            f"max_R_DD={summary['max_cumulative_r_drawdown']:.2f} "
            f"gap_go={summary['gap_go_trades']}"
        )
    print("")
    print("DELTA v2.4 - v2.3")
    print(json.dumps(result["delta"], sort_keys=True))
    print("")
    print("EARNINGS UPSIDE-GAP EVENTS")
    if result["earnings_gap_events"]:
        for event in result["earnings_gap_events"]:
            print(json.dumps(event, sort_keys=True))
    else:
        print("none")
    print("")
    print("V2.3 TRADES")
    for trade in result["trades_v2_3"]:
        print(json.dumps(trade, sort_keys=True))
    print("")
    print("V2.4 TRADES")
    for trade in result["trades_v2_4"]:
        print(json.dumps(trade, sort_keys=True))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
