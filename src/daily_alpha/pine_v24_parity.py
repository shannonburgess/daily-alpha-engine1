from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from math import isfinite
from typing import Literal

PINE_V24_SOURCE_PATH = "tradingview/da_turtle_20_10_v2_4.pine"
PINE_V24_SOURCE_BLOB_SHA = "33091e312ad3069ff7d82825b370f2a73d93107c"
PINE_V24_STRATEGY_VERSION = "2.4"
PINE_V24_MODEL_ID = "PAPER_SHADOW_V24"
PROCESS_ORDERS_ON_CLOSE = True

Action = Literal["ENTRY_LONG", "ADD", "PARTIAL", "EXIT"]


@dataclass(frozen=True, slots=True)
class DailyBar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    earnings_actual: float | None = None

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            raise ValueError("DailyBar.time must be timezone-aware")
        for name in ("open", "high", "low", "close", "volume"):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.high < self.low:
            raise ValueError("high cannot be below low")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.earnings_actual is not None and not isfinite(float(self.earnings_actual)):
            raise ValueError("earnings_actual must be finite when provided")


@dataclass(frozen=True, slots=True)
class V24Parameters:
    entry_len: int = 20
    exit_len: int = 10
    breakout_mode: Literal["Close", "High"] = "Close"
    atr_len: int = 10
    min_factor: float = 2.0
    max_factor: float = 4.0
    efficiency_len: int = 20
    require_fresh_bull_flip: bool = False
    max_bull_flip_age: int = 5
    min_prior_bull_bars: int = 2
    use_trend_exit: bool = True
    use_rsi_cap: bool = True
    rsi_len: int = 14
    max_entry_rsi: float = 80.0
    use_failed_breakout_exit: bool = True
    failed_breakout_bars: int = 3
    use_adx_filter: bool = True
    adx_di_len: int = 14
    adx_smooth: int = 14
    min_adx: float = 25.0
    use_efficiency_gate: bool = True
    min_trend_efficiency: float = 0.20
    use_price_floor: bool = True
    min_underlying_price: float = 25.0
    use_earnings_gap_sleeve: bool = True
    min_earnings_gap_pct: float = 5.0
    min_earnings_gap_atr: float = 1.5
    min_gap_close_location: float = 0.70
    min_early_gap_close_location: float = 0.60
    min_gap_retention: float = 0.70
    min_gap_relative_volume: float = 1.5
    max_earnings_rsi: float = 85.0
    crap_close_location: float = 0.50
    crap_gap_retention: float = 0.50
    use_runner_management: bool = True
    add1_atr: float = 1.0
    add2_atr: float = 2.0
    harvest_atr: float = 3.0
    use_break_even_after_harvest: bool = True
    start_time: datetime = field(
        default_factory=lambda: datetime(2024, 1, 1, 5, tzinfo=UTC)
    )
    end_time: datetime = field(
        default_factory=lambda: datetime(2100, 1, 1, 4, 59, tzinfo=UTC)
    )

    def __post_init__(self) -> None:
        for name in (
            "entry_len",
            "exit_len",
            "atr_len",
            "efficiency_len",
            "rsi_len",
            "failed_breakout_bars",
            "adx_di_len",
            "adx_smooth",
            "min_prior_bull_bars",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if self.breakout_mode not in {"Close", "High"}:
            raise ValueError("breakout_mode must be Close or High")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("start_time/end_time must be timezone-aware")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")


@dataclass(frozen=True, slots=True)
class ParitySignal:
    symbol: str
    bar_index: int
    bar_time: datetime
    action: Action
    price: float
    entry_type: str
    quantity_units: int
    runner_stage: str | None = None
    position_fraction: float | None = None
    stock_stop_price: float | None = None
    average_daily_dollar_volume: float | None = None
    earnings_gap_class: str = "NONE"
    earnings_gap_pct: float = 0.0
    earnings_gap_atr: float = 0.0
    earnings_close_location: float = 0.0
    earnings_gap_retention: float = 0.0
    earnings_relative_volume: float = 0.0
    exit_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class V24BarResult:
    symbol: str
    bar_index: int
    bar_time: datetime
    upper20: float | None
    lower10: float | None
    atr: float | None
    efficiency: float | None
    rsi: float | None
    adx: float | None
    trend_state: int
    trend_stop: float | None
    fresh_long_breakout: bool
    earnings_gap_class: str
    entry_type: str
    rejection_reasons: tuple[str, ...]
    signals: tuple[ParitySignal, ...]
    position_units_after_close: int
    position_avg_price_after_close: float | None


def _sma(values: Sequence[float | None], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0:
        raise ValueError("length must be positive")
    for i in range(len(values)):
        if i + 1 < length:
            continue
        window = values[i - length + 1 : i + 1]
        if any(value is None for value in window):
            continue
        out[i] = sum(float(value) for value in window if value is not None) / length
    return out


def _rma(values: Sequence[float | None], length: int) -> list[float | None]:
    """TradingView-style Wilder RMA: SMA seed over first `length` valid values."""
    out: list[float | None] = [None] * len(values)
    seed: list[float] = []
    previous: float | None = None
    for i, value in enumerate(values):
        if value is None:
            continue
        current = float(value)
        if previous is None:
            seed.append(current)
            if len(seed) == length:
                previous = sum(seed) / length
                out[i] = previous
        else:
            previous = (previous * (length - 1) + current) / length
            out[i] = previous
    return out


def _true_range(bars: Sequence[DailyBar]) -> list[float]:
    out: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append(bar.high - bar.low)
            continue
        previous_close = bars[i - 1].close
        out.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    return out


def _atr(bars: Sequence[DailyBar], length: int) -> list[float | None]:
    return _rma(_true_range(bars), length)


def _rsi(bars: Sequence[DailyBar], length: int) -> list[float | None]:
    gains: list[float | None] = [None]
    losses: list[float | None] = [None]
    for i in range(1, len(bars)):
        change = bars[i].close - bars[i - 1].close
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = _rma(gains, length)
    avg_loss = _rma(losses, length)
    out: list[float | None] = [None] * len(bars)
    for i, (up, down) in enumerate(zip(avg_gain, avg_loss, strict=True)):
        if up is None or down is None:
            continue
        if down == 0:
            out[i] = 100.0 if up > 0 else 50.0
        elif up == 0:
            out[i] = 0.0
        else:
            rs = up / down
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _dmi_adx(
    bars: Sequence[DailyBar], di_length: int, adx_smoothing: int
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    plus_dm: list[float | None] = [None]
    minus_dm: list[float | None] = [None]
    for i in range(1, len(bars)):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    tr_rma = _rma(_true_range(bars), di_length)
    plus_rma = _rma(plus_dm, di_length)
    minus_rma = _rma(minus_dm, di_length)
    plus_di: list[float | None] = [None] * len(bars)
    minus_di: list[float | None] = [None] * len(bars)
    dx: list[float | None] = [None] * len(bars)

    last_plus: float | None = None
    last_minus: float | None = None
    for i in range(len(bars)):
        tr = tr_rma[i]
        plus = plus_rma[i]
        minus = minus_rma[i]
        if tr is None or plus is None or minus is None:
            continue
        if tr == 0:
            current_plus = 0.0
            current_minus = 0.0
        else:
            current_plus = 100.0 * plus / tr
            current_minus = 100.0 * minus / tr
        if isfinite(current_plus):
            last_plus = current_plus
        if isfinite(current_minus):
            last_minus = current_minus
        plus_di[i] = last_plus
        minus_di[i] = last_minus
        if last_plus is not None and last_minus is not None:
            total = last_plus + last_minus
            dx[i] = 100.0 * abs(last_plus - last_minus) / (total if total else 1.0)

    return plus_di, minus_di, _rma(dx, adx_smoothing)


def _prior_highest(bars: Sequence[DailyBar], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    for i in range(length, len(bars)):
        out[i] = max(bar.high for bar in bars[i - length : i])
    return out


def _prior_lowest(bars: Sequence[DailyBar], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    for i in range(length, len(bars)):
        out[i] = min(bar.low for bar in bars[i - length : i])
    return out


def _efficiency(bars: Sequence[DailyBar], length: int) -> list[float | None]:
    changes: list[float | None] = [None]
    changes.extend(abs(bars[i].close - bars[i - 1].close) for i in range(1, len(bars)))
    mean_changes = _sma(changes, length)
    out: list[float | None] = [None] * len(bars)
    for i in range(length, len(bars)):
        mean = mean_changes[i]
        if mean is None:
            continue
        path_length = mean * length
        direction = abs(bars[i].close - bars[i - length].close)
        out[i] = min(direction / path_length, 1.0) if path_length > 0 else 0.0
    return out


def _average_volume_prior(bars: Sequence[DailyBar], length: int = 20) -> list[float | None]:
    volumes = [bar.volume for bar in bars]
    average = _sma(volumes, length)
    return [None] + average[:-1]


def _average_dollar_volume(bars: Sequence[DailyBar], length: int = 20) -> list[float | None]:
    return _sma([bar.close * bar.volume for bar in bars], length)


def run_v24_parity(
    symbol: str,
    bars: Sequence[DailyBar],
    parameters: V24Parameters | None = None,
) -> tuple[V24BarResult, ...]:
    """Replay the frozen v2.4 Pine state machine with close-processed order semantics."""
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    if not bars:
        return ()
    params = parameters or V24Parameters()
    for previous, current in pairwise(bars):
        if current.time <= previous.time:
            raise ValueError("bars must be strictly chronological")

    upper = _prior_highest(bars, params.entry_len)
    lower = _prior_lowest(bars, params.exit_len)
    atr_values = _atr(bars, params.atr_len)
    efficiency_values = _efficiency(bars, params.efficiency_len)
    rsi_values = _rsi(bars, params.rsi_len)
    _, _, adx_values = _dmi_adx(bars, params.adx_di_len, params.adx_smooth)
    average_volume_prior = _average_volume_prior(bars)
    average_dollar_volume = _average_dollar_volume(bars)

    final_upper: float | None = None
    final_lower: float | None = None
    trend_state = 1
    bullish_trend_bars = 0
    last_bull_flip_index: int | None = None

    position_units = 0
    position_avg_price: float | None = None
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
    active_entry_type = "NONE"

    results: list[V24BarResult] = []
    previous_breakout = False

    for i, bar in enumerate(bars):
        pre_position_units = position_units
        pre_position_avg = position_avg_price
        previous_trend = trend_state
        previous_bullish_bars = bullish_trend_bars

        atr = atr_values[i]
        efficiency = efficiency_values[i]
        rsi = rsi_values[i]
        adx = adx_values[i]

        basic_upper = (
            (bar.high + bar.low) / 2.0
            + atr * (params.max_factor - efficiency * (params.max_factor - params.min_factor))
            if atr is not None and efficiency is not None
            else None
        )
        basic_lower = (
            (bar.high + bar.low) / 2.0
            - atr * (params.max_factor - efficiency * (params.max_factor - params.min_factor))
            if atr is not None and efficiency is not None
            else None
        )

        previous_final_upper = final_upper
        previous_final_lower = final_lower
        previous_close = bars[i - 1].close if i > 0 else None

        if basic_upper is not None:
            if (
                previous_final_upper is None
                or basic_upper < previous_final_upper
                or (previous_close is not None and previous_close > previous_final_upper)
            ):
                final_upper = basic_upper
            else:
                final_upper = previous_final_upper
        else:
            final_upper = None if previous_final_upper is None else previous_final_upper

        if basic_lower is not None:
            if (
                previous_final_lower is None
                or basic_lower > previous_final_lower
                or (previous_close is not None and previous_close < previous_final_lower)
            ):
                final_lower = basic_lower
            else:
                final_lower = previous_final_lower
        else:
            final_lower = None if previous_final_lower is None else previous_final_lower

        if (
            previous_trend == -1
            and previous_final_upper is not None
            and bar.close > previous_final_upper
        ):
            trend_state = 1
        elif (
            previous_trend == 1
            and previous_final_lower is not None
            and bar.close < previous_final_lower
        ):
            trend_state = -1
        else:
            trend_state = previous_trend

        bull_flip = trend_state == 1 and previous_trend == -1
        bear_flip = trend_state == -1 and previous_trend == 1
        if bull_flip:
            last_bull_flip_index = i
        bars_since_bull_flip = (
            i - last_bull_flip_index if last_bull_flip_index is not None else None
        )
        fresh_trend_ok = (
            not params.require_fresh_bull_flip
            or (
                bars_since_bull_flip is not None
                and bars_since_bull_flip <= params.max_bull_flip_age
            )
        )
        bullish_trend_bars = previous_bullish_bars + 1 if trend_state == 1 else 0
        normal_trend_mature = previous_bullish_bars >= params.min_prior_bull_bars
        trend_stop = final_lower if trend_state == 1 else final_upper

        upper20 = upper[i]
        lower10 = lower[i]
        breakout_now = upper20 is not None and (
            bar.close > upper20 if params.breakout_mode == "Close" else bar.high > upper20
        )
        fresh_long_breakout = bool(breakout_now and not previous_breakout)
        previous_breakout = bool(breakout_now)

        gap_pct = 0.0
        gap_atr = 0.0
        close_location = 0.0
        gap_retention = 0.0
        relative_volume = 0.0
        is_earnings_upside_gap = False
        earnings_gap_go = False
        earnings_gap_go_early = False
        earnings_gap_crap = False
        earnings_wait = False

        if i > 0:
            prev_close = bars[i - 1].close
            previous_atr = atr_values[i - 1]
            gap_dollars = bar.open - prev_close
            gap_pct = gap_dollars / prev_close * 100.0 if prev_close > 0 else 0.0
            gap_atr = (
                gap_dollars / previous_atr
                if previous_atr is not None and previous_atr > 0
                else 0.0
            )
            day_range = bar.high - bar.low
            close_location = (bar.close - bar.low) / day_range if day_range > 0 else 0.0
            gap_retention = (bar.close - prev_close) / gap_dollars if gap_dollars > 0 else 0.0
            prior_avg_volume = average_volume_prior[i]
            relative_volume = (
                bar.volume / prior_avg_volume
                if prior_avg_volume is not None and prior_avg_volume > 0
                else 0.0
            )
            earnings_window = bar.earnings_actual is not None or (
                bars[i - 1].earnings_actual is not None
            )
            is_earnings_upside_gap = (
                params.use_earnings_gap_sleeve
                and earnings_window
                and gap_dollars > 0
                and (
                    gap_pct >= params.min_earnings_gap_pct
                    or gap_atr >= params.min_earnings_gap_atr
                )
            )
            earnings_breakout = upper20 is not None and bar.close > upper20
            common_quality = (
                bar.close >= bar.open
                and gap_retention >= params.min_gap_retention
                and relative_volume >= params.min_gap_relative_volume
                and rsi is not None
                and rsi <= params.max_earnings_rsi
                and trend_state == 1
                and earnings_breakout
            )
            epsilon = 0.000001
            earnings_gap_go = (
                is_earnings_upside_gap
                and common_quality
                and close_location >= params.min_gap_close_location - epsilon
            )
            earnings_gap_go_early = (
                is_earnings_upside_gap
                and common_quality
                and close_location >= params.min_early_gap_close_location - epsilon
                and close_location < params.min_gap_close_location - epsilon
            )
            earnings_gap_crap = (
                is_earnings_upside_gap
                and not earnings_gap_go
                and not earnings_gap_go_early
                and (
                    bar.close < prev_close
                    or gap_retention < params.crap_gap_retention
                    or (bar.close < bar.open and close_location < params.crap_close_location)
                )
            )
            earnings_wait = (
                is_earnings_upside_gap
                and not earnings_gap_go
                and not earnings_gap_go_early
                and not earnings_gap_crap
            )

        earnings_gap_class = (
            "EARNINGS_GAP_GO"
            if earnings_gap_go
            else "EARNINGS_GAP_GO_EARLY"
            if earnings_gap_go_early
            else "EARNINGS_GAP_CRAP"
            if earnings_gap_crap
            else "EARNINGS_WAIT"
            if earnings_wait
            else "NONE"
        )

        in_window = params.start_time <= bar.time <= params.end_time
        price_ok = not params.use_price_floor or bar.close >= params.min_underlying_price
        efficiency_ok = not params.use_efficiency_gate or (
            efficiency is not None and efficiency >= params.min_trend_efficiency
        )
        rsi_ok = not params.use_rsi_cap or (rsi is not None and rsi <= params.max_entry_rsi)
        adx_ok = not params.use_adx_filter or (adx is not None and adx >= params.min_adx)

        normal_base_setup = (
            in_window
            and pre_position_units == 0
            and fresh_long_breakout
            and not is_earnings_upside_gap
            and trend_state == 1
            and normal_trend_mature
            and fresh_trend_ok
        )
        normal_long_entry = normal_base_setup and price_ok and efficiency_ok and rsi_ok and adx_ok
        earnings_gap_go_entry = (
            in_window
            and pre_position_units == 0
            and earnings_gap_go
            and fresh_long_breakout
            and price_ok
        )
        long_entry = normal_long_entry or earnings_gap_go_entry
        entry_type = (
            "EARNINGS_GAP_GO"
            if earnings_gap_go_entry
            else "NORMAL_BREAKOUT"
            if normal_long_entry
            else "NONE"
        )

        rejection_reasons: list[str] = []
        if in_window and pre_position_units == 0 and fresh_long_breakout and not long_entry:
            if is_earnings_upside_gap:
                if not earnings_gap_go:
                    rejection_reasons.append(earnings_gap_class)
                if not price_ok:
                    rejection_reasons.append("PRICE_BELOW_FLOOR")
            else:
                if trend_state != 1:
                    rejection_reasons.append("TREND_NOT_BULLISH")
                if not normal_trend_mature:
                    rejection_reasons.append("TREND_NOT_MATURE")
                if not fresh_trend_ok:
                    rejection_reasons.append("BULL_FLIP_TOO_OLD")
                if normal_base_setup and not price_ok:
                    rejection_reasons.append("PRICE_BELOW_FLOOR")
                if normal_base_setup and price_ok and not efficiency_ok:
                    rejection_reasons.append("LOW_TREND_EFFICIENCY")
                if normal_base_setup and price_ok and efficiency_ok and not rsi_ok:
                    rejection_reasons.append("RSI_EXTENDED")
                if (
                    normal_base_setup
                    and price_ok
                    and efficiency_ok
                    and rsi_ok
                    and not adx_ok
                ):
                    rejection_reasons.append("ADX_TOO_LOW")

        if long_entry:
            entry_breakout_level = upper20
            entry_signal_bar = i
            runner_base_entry = bar.close
            runner_base_atr = atr
            active_entry_type = entry_type
            add1_done = False
            add2_done = False
            harvest_done = False
            add1_bar = None
            add2_bar = None
            break_even_level = None

        bars_since_entry = i - entry_signal_bar if entry_signal_bar is not None else None
        failed_breakout_exit = (
            pre_position_units > 0
            and params.use_failed_breakout_exit
            and entry_breakout_level is not None
            and bars_since_entry is not None
            and 1 <= bars_since_entry <= params.failed_breakout_bars
            and bar.close < entry_breakout_level
        )
        runner_trend_ok = trend_state == 1 and (
            not params.use_adx_filter or (adx is not None and adx >= params.min_adx)
        )

        add1_signal = (
            params.use_runner_management
            and pre_position_units > 0
            and not add1_done
            and runner_base_entry is not None
            and runner_base_atr is not None
            and runner_trend_ok
            and bar.close >= runner_base_entry + runner_base_atr * params.add1_atr
        )
        if add1_signal:
            add1_done = True
            add1_bar = i

        add2_signal = (
            params.use_runner_management
            and pre_position_units > 0
            and add1_done
            and not add2_done
            and add1_bar is not None
            and i > add1_bar
            and runner_base_entry is not None
            and runner_base_atr is not None
            and runner_trend_ok
            and bar.close >= runner_base_entry + runner_base_atr * params.add2_atr
        )
        if add2_signal:
            add2_done = True
            add2_bar = i

        harvest_signal = (
            params.use_runner_management
            and pre_position_units > 0
            and add2_done
            and not harvest_done
            and add2_bar is not None
            and i > add2_bar
            and runner_base_entry is not None
            and runner_base_atr is not None
            and bar.close >= runner_base_entry + runner_base_atr * params.harvest_atr
        )
        if harvest_signal:
            break_even_level = pre_position_avg
            harvest_done = True

        break_even_exit = (
            pre_position_units > 0
            and params.use_runner_management
            and params.use_break_even_after_harvest
            and harvest_done
            and break_even_level is not None
            and bar.close <= break_even_level
        )
        turtle_exit = pre_position_units > 0 and lower10 is not None and bar.close < lower10
        trend_exit = pre_position_units > 0 and params.use_trend_exit and bear_flip
        exit_reasons = tuple(
            reason
            for reason, triggered in (
                ("BREAK_EVEN_EXIT", break_even_exit),
                ("FAILED_BREAKOUT_EXIT", failed_breakout_exit),
                ("TURTLE_EXIT", turtle_exit),
                ("TREND_EXIT", trend_exit),
            )
            if triggered
        )
        long_exit = in_window and bool(exit_reasons)

        signals: list[ParitySignal] = []
        if long_entry:
            signals.append(
                ParitySignal(
                    symbol=symbol,
                    bar_index=i,
                    bar_time=bar.time,
                    action="ENTRY_LONG",
                    price=bar.close,
                    entry_type=entry_type,
                    quantity_units=2,
                    stock_stop_price=lower10,
                    average_daily_dollar_volume=average_dollar_volume[i],
                    earnings_gap_class=earnings_gap_class,
                    earnings_gap_pct=gap_pct,
                    earnings_gap_atr=gap_atr,
                    earnings_close_location=close_location,
                    earnings_gap_retention=gap_retention,
                    earnings_relative_volume=relative_volume,
                )
            )
        if add1_signal:
            signals.append(
                ParitySignal(
                    symbol=symbol,
                    bar_index=i,
                    bar_time=bar.time,
                    action="ADD",
                    price=bar.close,
                    entry_type=active_entry_type,
                    quantity_units=1,
                    runner_stage="ADD_1_ATR",
                    position_fraction=0.25,
                )
            )
        if add2_signal:
            signals.append(
                ParitySignal(
                    symbol=symbol,
                    bar_index=i,
                    bar_time=bar.time,
                    action="ADD",
                    price=bar.close,
                    entry_type=active_entry_type,
                    quantity_units=1,
                    runner_stage="ADD_2_ATR",
                    position_fraction=0.25,
                )
            )
        if harvest_signal:
            signals.append(
                ParitySignal(
                    symbol=symbol,
                    bar_index=i,
                    bar_time=bar.time,
                    action="PARTIAL",
                    price=bar.close,
                    entry_type=active_entry_type,
                    quantity_units=1,
                    runner_stage="HARVEST_3_ATR",
                    position_fraction=0.25,
                )
            )
        if long_exit:
            signals.append(
                ParitySignal(
                    symbol=symbol,
                    bar_index=i,
                    bar_time=bar.time,
                    action="EXIT",
                    price=bar.close,
                    entry_type=active_entry_type,
                    quantity_units=pre_position_units,
                    exit_reasons=exit_reasons,
                )
            )

        # Pine computes conditions before filling market orders. process_orders_on_close=true
        # therefore applies emitted market orders at this confirmed bar's close.
        if long_entry:
            position_units = 2
            position_avg_price = bar.close
        if add1_signal and position_units > 0:
            old_notional = float(position_avg_price or 0.0) * position_units
            position_units += 1
            position_avg_price = (old_notional + bar.close) / position_units
        if add2_signal and position_units > 0:
            old_notional = float(position_avg_price or 0.0) * position_units
            position_units += 1
            position_avg_price = (old_notional + bar.close) / position_units
        if harvest_signal and position_units > 0:
            position_units = max(position_units - 1, 0)
            if position_units == 0:
                position_avg_price = None
        if long_exit and position_units > 0:
            position_units = 0
            position_avg_price = None
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

        if bar.time > params.end_time and pre_position_units > 0 and not long_exit:
            signals.append(
                ParitySignal(
                    symbol=symbol,
                    bar_index=i,
                    bar_time=bar.time,
                    action="EXIT",
                    price=bar.close,
                    entry_type=active_entry_type,
                    quantity_units=pre_position_units,
                    exit_reasons=("BACKTEST_END",),
                )
            )
            position_units = 0
            position_avg_price = None
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
            position_units == 0
            and not long_entry
            and entry_signal_bar is not None
            and i > entry_signal_bar + params.failed_breakout_bars
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
            active_entry_type = "NONE"

        results.append(
            V24BarResult(
                symbol=symbol,
                bar_index=i,
                bar_time=bar.time,
                upper20=upper20,
                lower10=lower10,
                atr=atr,
                efficiency=efficiency,
                rsi=rsi,
                adx=adx,
                trend_state=trend_state,
                trend_stop=trend_stop,
                fresh_long_breakout=fresh_long_breakout,
                earnings_gap_class=earnings_gap_class,
                entry_type=entry_type,
                rejection_reasons=tuple(rejection_reasons),
                signals=tuple(signals),
                position_units_after_close=position_units,
                position_avg_price_after_close=position_avg_price,
            )
        )

    return tuple(results)
