from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise

from .pine_v24_parity import (
    DailyBar,
    ParitySignal,
    _atr,
    _average_dollar_volume,
    _average_volume_prior,
    _dmi_adx,
    _efficiency,
    _prior_highest,
    _prior_lowest,
    _rsi,
)
from .pine_v25_armed_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_COMMIT,
    PINE_V25_SOURCE_SHA256,
    PINE_V25_STRATEGY_VERSION,
    V25ArmedBreakoutMachine,
    V25ArmedInputs,
    V25ArmedParameters,
)

PINE_V25_SOURCE_PATH = "tradingview/da_turtle_20_10_v2_5_shadow_challenger.pine"
PINE_V25_SOURCE_BLOB_SHA = "2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5"
PROCESS_ORDERS_ON_CLOSE = True


@dataclass(frozen=True, slots=True)
class V25Parameters:
    entry_len: int = 20
    exit_len: int = 10
    breakout_mode: str = "Close"
    atr_len: int = 10
    min_factor: float = 2.0
    max_factor: float = 4.0
    efficiency_len: int = 20
    require_fresh_bull_flip: bool = False
    max_bull_flip_age: int = 5
    min_prior_bull_bars: int = 2
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
    use_persistent_armed_entry: bool = True
    armed_max_bars: int = 10
    max_chase_atr: float = 1.0
    arm_invalidation_atr: float = 0.50
    use_runner_management: bool = True
    add1_atr: float = 1.0
    add2_atr: float = 2.0
    harvest_atr: float = 3.0
    use_structural_runner_exit: bool = True
    structural_exit_len: int = 20
    structural_confirm_bars: int = 1
    use_break_even_after_harvest: bool = False
    use_legacy_adaptive_exit: bool = False
    use_legacy_turtle_exit: bool = False
    start_time: datetime = field(
        default_factory=lambda: datetime(2024, 1, 1, 5, tzinfo=UTC)
    )
    end_time: datetime = field(
        default_factory=lambda: datetime(2100, 1, 1, 4, 59, tzinfo=UTC)
    )
    enable_shadow_forward_test: bool = True
    shadow_forward_start: datetime = field(
        default_factory=lambda: datetime(2026, 8, 19, 4, tzinfo=UTC)
    )

    def __post_init__(self) -> None:
        for name in (
            "entry_len",
            "exit_len",
            "atr_len",
            "efficiency_len",
            "min_prior_bull_bars",
            "rsi_len",
            "failed_breakout_bars",
            "adx_di_len",
            "adx_smooth",
            "armed_max_bars",
            "structural_exit_len",
            "structural_confirm_bars",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if self.breakout_mode not in {"Close", "High"}:
            raise ValueError("breakout_mode must be Close or High")
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("start_time/end_time must be timezone-aware")
        if self.shadow_forward_start.tzinfo is None:
            raise ValueError("shadow_forward_start must be timezone-aware")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.max_chase_atr < 0 or self.arm_invalidation_atr < 0:
            raise ValueError("armed ATR distances cannot be negative")


@dataclass(frozen=True, slots=True)
class V25BarResult:
    symbol: str
    bar_index: int
    bar_time: datetime
    upper20: float | None
    lower10: float | None
    structural_lower: float | None
    atr: float | None
    efficiency: float | None
    rsi: float | None
    adx: float | None
    trend_state: int
    trend_stop: float | None
    fresh_long_breakout: bool
    earnings_gap_class: str
    entry_type: str
    breakout_armed: bool
    armed_age: int | None
    armed_breakout_level: float | None
    armed_max_price: float | None
    armed_invalidation_level: float | None
    arm_events: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    entry_selected_breakout_level: float | None
    entry_armed_age: int | None
    entry_replay_max_price: float | None
    signals: tuple[ParitySignal, ...]
    position_units_after_close: int
    position_avg_price_after_close: float | None


def _earnings_state(
    bars: Sequence[DailyBar],
    i: int,
    *,
    atr_values: Sequence[float | None],
    average_volume_prior: Sequence[float | None],
    upper20: float | None,
    rsi: float | None,
    trend_state: int,
    params: V25Parameters,
) -> tuple[str, bool, bool, float, float, float, float, float]:
    if i == 0:
        return "NONE", False, False, 0.0, 0.0, 0.0, 0.0, 0.0
    bar = bars[i]
    previous_close = bars[i - 1].close
    previous_atr = atr_values[i - 1]
    gap_dollars = bar.open - previous_close
    gap_pct = gap_dollars / previous_close * 100.0 if previous_close > 0 else 0.0
    gap_atr = (
        gap_dollars / previous_atr
        if previous_atr is not None and previous_atr > 0
        else 0.0
    )
    day_range = bar.high - bar.low
    close_location = (bar.close - bar.low) / day_range if day_range > 0 else 0.0
    gap_retention = (
        (bar.close - previous_close) / gap_dollars if gap_dollars > 0 else 0.0
    )
    prior_average_volume = average_volume_prior[i]
    relative_volume = (
        bar.volume / prior_average_volume
        if prior_average_volume is not None and prior_average_volume > 0
        else 0.0
    )
    earnings_window = (
        bar.earnings_actual is not None or bars[i - 1].earnings_actual is not None
    )
    is_upside_gap = (
        params.use_earnings_gap_sleeve
        and earnings_window
        and gap_dollars > 0
        and (
            gap_pct >= params.min_earnings_gap_pct
            or gap_atr >= params.min_earnings_gap_atr
        )
    )
    common_quality = (
        bar.close >= bar.open
        and gap_retention >= params.min_gap_retention
        and relative_volume >= params.min_gap_relative_volume
        and rsi is not None
        and rsi <= params.max_earnings_rsi
        and trend_state == 1
        and upper20 is not None
        and bar.close > upper20
    )
    epsilon = 0.000001
    gap_go = (
        is_upside_gap
        and common_quality
        and close_location >= params.min_gap_close_location - epsilon
    )
    gap_early = (
        is_upside_gap
        and common_quality
        and close_location >= params.min_early_gap_close_location - epsilon
        and close_location < params.min_gap_close_location - epsilon
    )
    gap_crap = (
        is_upside_gap
        and not gap_go
        and not gap_early
        and (
            bar.close < previous_close
            or gap_retention < params.crap_gap_retention
            or (bar.close < bar.open and close_location < params.crap_close_location)
        )
    )
    earnings_wait = is_upside_gap and not gap_go and not gap_early and not gap_crap
    gap_class = (
        "EARNINGS_GAP_GO"
        if gap_go
        else "EARNINGS_GAP_GO_EARLY"
        if gap_early
        else "EARNINGS_GAP_CRAP"
        if gap_crap
        else "EARNINGS_WAIT"
        if earnings_wait
        else "NONE"
    )
    return (
        gap_class,
        is_upside_gap,
        gap_go,
        gap_pct,
        gap_atr,
        close_location,
        gap_retention,
        relative_volume,
    )


def run_v25_parity(
    symbol: str,
    bars: Sequence[DailyBar],
    parameters: V25Parameters | None = None,
) -> tuple[V25BarResult, ...]:
    """Replay the audited SH25 Pine challenger with close-processed order semantics."""
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    if not bars:
        return ()
    params = parameters or V25Parameters()
    for previous, current in pairwise(bars):
        if current.time <= previous.time:
            raise ValueError("bars must be strictly chronological")

    upper = _prior_highest(bars, params.entry_len)
    lower = _prior_lowest(bars, params.exit_len)
    structural_lower_values = _prior_lowest(bars, params.structural_exit_len)
    atr_values = _atr(bars, params.atr_len)
    efficiency_values = _efficiency(bars, params.efficiency_len)
    rsi_values = _rsi(bars, params.rsi_len)
    _, _, adx_values = _dmi_adx(bars, params.adx_di_len, params.adx_smooth)
    average_volume_prior = _average_volume_prior(bars)
    average_dollar_volume = _average_dollar_volume(bars)
    arm_machine = V25ArmedBreakoutMachine(
        V25ArmedParameters(
            use_persistent_armed_entry=params.use_persistent_armed_entry,
            armed_max_bars=params.armed_max_bars,
            max_chase_atr=params.max_chase_atr,
            arm_invalidation_atr=params.arm_invalidation_atr,
        )
    )

    final_upper: float | None = None
    final_lower: float | None = None
    trend_state = 1
    bullish_trend_bars = 0
    last_bull_flip_index: int | None = None
    previous_breakout = False
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
    structural_break_count = 0
    results: list[V25BarResult] = []

    for i, bar in enumerate(bars):
        pre_position_units = position_units
        pre_position_avg = position_avg_price
        previous_trend = trend_state
        previous_bullish_bars = bullish_trend_bars
        atr = atr_values[i]
        efficiency = efficiency_values[i]
        rsi = rsi_values[i]
        adx = adx_values[i]
        adaptive_factor = (
            params.max_factor - efficiency * (params.max_factor - params.min_factor)
            if efficiency is not None
            else None
        )
        basic_upper = (
            (bar.high + bar.low) / 2.0 + atr * adaptive_factor
            if atr is not None and adaptive_factor is not None
            else None
        )
        basic_lower = (
            (bar.high + bar.low) / 2.0 - atr * adaptive_factor
            if atr is not None and adaptive_factor is not None
            else None
        )
        previous_final_upper = final_upper
        previous_final_lower = final_lower
        previous_close = bars[i - 1].close if i > 0 else None
        if basic_upper is not None:
            final_upper = (
                basic_upper
                if previous_final_upper is None
                or basic_upper < previous_final_upper
                or (previous_close is not None and previous_close > previous_final_upper)
                else previous_final_upper
            )
        elif previous_final_upper is not None:
            final_upper = previous_final_upper
        if basic_lower is not None:
            final_lower = (
                basic_lower
                if previous_final_lower is None
                or basic_lower > previous_final_lower
                or (previous_close is not None and previous_close < previous_final_lower)
                else previous_final_lower
            )
        elif previous_final_lower is not None:
            final_lower = previous_final_lower

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
        structural_lower = structural_lower_values[i]
        breakout_now = upper20 is not None and (
            bar.close > upper20 if params.breakout_mode == "Close" else bar.high > upper20
        )
        fresh_long_breakout = bool(breakout_now and not previous_breakout)
        previous_breakout = bool(breakout_now)
        (
            earnings_gap_class,
            is_earnings_upside_gap,
            earnings_gap_go,
            gap_pct,
            gap_atr,
            close_location,
            gap_retention,
            relative_volume,
        ) = _earnings_state(
            bars,
            i,
            atr_values=atr_values,
            average_volume_prior=average_volume_prior,
            upper20=upper20,
            rsi=rsi,
            trend_state=trend_state,
            params=params,
        )

        in_window = (
            params.start_time <= bar.time <= params.end_time
            and params.enable_shadow_forward_test
            and bar.time >= params.shadow_forward_start
        )
        price_ok = not params.use_price_floor or bar.close >= params.min_underlying_price
        efficiency_ok = not params.use_efficiency_gate or (
            efficiency is not None and efficiency >= params.min_trend_efficiency
        )
        rsi_ok = not params.use_rsi_cap or (rsi is not None and rsi <= params.max_entry_rsi)
        adx_ok = not params.use_adx_filter or (adx is not None and adx >= params.min_adx)
        quality_entry_ok = price_ok and efficiency_ok and rsi_ok and adx_ok
        normal_breakout_candidate = (
            in_window
            and pre_position_units == 0
            and fresh_long_breakout
            and not is_earnings_upside_gap
        )
        same_bar_normal_entry = (
            normal_breakout_candidate
            and trend_state == 1
            and fresh_trend_ok
            and normal_trend_mature
            and quality_entry_ok
        )
        armed = arm_machine.step(
            V25ArmedInputs(
                bar_index=i,
                close=bar.close,
                upper20=upper20,
                atr=atr,
                position_is_flat=pre_position_units == 0,
                normal_breakout_candidate=normal_breakout_candidate,
                same_bar_normal_entry=same_bar_normal_entry,
                trend_state=trend_state,
                normal_trend_mature=normal_trend_mature,
                fresh_trend_ok=fresh_trend_ok,
                quality_entry_ok=quality_entry_ok,
                bar_confirmed=True,
            )
        )
        armed_confirmed_entry = armed.armed_confirmed_entry
        earnings_gap_go_entry = (
            in_window
            and pre_position_units == 0
            and earnings_gap_go
            and fresh_long_breakout
            and price_ok
        )
        long_entry = same_bar_normal_entry or armed_confirmed_entry or earnings_gap_go_entry
        entry_type = (
            "EARNINGS_GAP_GO"
            if earnings_gap_go_entry
            else "ARMED_BREAKOUT_CONFIRM"
            if armed_confirmed_entry
            else "NORMAL_BREAKOUT"
            if same_bar_normal_entry
            else "NONE"
        )
        selected_breakout_level = (
            armed.armed_breakout_level if armed_confirmed_entry else upper20
        )
        selected_armed_age = armed.armed_age if armed_confirmed_entry else 0
        selected_replay_atr = armed.armed_atr if armed_confirmed_entry else atr
        replay_max_price = (
            max(
                bar.close,
                selected_breakout_level + selected_replay_atr * params.max_chase_atr,
            )
            if selected_breakout_level is not None and selected_replay_atr is not None
            else None
        )
        entry_selected_breakout_level = selected_breakout_level if long_entry else None
        entry_armed_age = selected_armed_age if long_entry else None
        entry_replay_max_price = replay_max_price if long_entry else None

        if long_entry:
            entry_breakout_level = selected_breakout_level
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
            arm_machine.reset()

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

        structural_break_now = (
            pre_position_units > 0
            and structural_lower is not None
            and bar.close < structural_lower
        )
        structural_break_count = structural_break_count + 1 if structural_break_now else 0
        structural_exit = (
            pre_position_units > 0
            and params.use_structural_runner_exit
            and structural_break_count >= params.structural_confirm_bars
        )
        break_even_exit = (
            pre_position_units > 0
            and params.use_break_even_after_harvest
            and harvest_done
            and break_even_level is not None
            and bar.close <= break_even_level
        )
        legacy_turtle_exit = (
            pre_position_units > 0
            and params.use_legacy_turtle_exit
            and lower10 is not None
            and bar.close < lower10
        )
        legacy_trend_exit = (
            pre_position_units > 0 and params.use_legacy_adaptive_exit and bear_flip
        )
        exit_reason = (
            "STRUCTURAL_EXIT"
            if structural_exit
            else "FAILED_BREAKOUT_EXIT"
            if failed_breakout_exit
            else "BREAK_EVEN_EXIT"
            if break_even_exit
            else "TURTLE_EXIT"
            if legacy_turtle_exit
            else "ADAPTIVE_TREND_EXIT"
            if legacy_trend_exit
            else "NONE"
        )
        long_exit = in_window and exit_reason != "NONE"

        arm_events = tuple(
            event
            for event, triggered in (
                ("BREAKOUT_ARMED", armed.new_arm),
                ("ARM_EXPIRED", armed.arm_expired_event),
                ("ARM_INVALIDATED", armed.arm_invalidated_event),
            )
            if triggered
        )
        rejection_reasons: list[str] = []
        if armed.armed_active and not armed_confirmed_entry:
            if armed.armed_max_price is not None and bar.close > armed.armed_max_price:
                rejection_reasons.append("ARMED_EXTENDED_NO_CHASE")
            if trend_state != 1 or not normal_trend_mature:
                rejection_reasons.append("ARMED_WAIT_TREND")
            if trend_state == 1 and normal_trend_mature and not price_ok:
                rejection_reasons.append("ARMED_WAIT_PRICE")
            if trend_state == 1 and normal_trend_mature and price_ok and not efficiency_ok:
                rejection_reasons.append("ARMED_WAIT_EFFICIENCY")
            if (
                trend_state == 1
                and normal_trend_mature
                and price_ok
                and efficiency_ok
                and not rsi_ok
            ):
                rejection_reasons.append("ARMED_WAIT_RSI")
            if (
                trend_state == 1
                and normal_trend_mature
                and price_ok
                and efficiency_ok
                and rsi_ok
                and not adx_ok
            ):
                rejection_reasons.append("ARMED_WAIT_ADX")
            if trend_state == 1 and normal_trend_mature and not fresh_trend_ok:
                rejection_reasons.append("ARMED_BULL_FLIP_TOO_OLD")
            if not armed.armed_above_breakout:
                rejection_reasons.append("ARMED_WAIT_ABOVE_BREAKOUT")
        if armed.arm_expired_event:
            rejection_reasons.append("ARM_EXPIRED")
        if armed.arm_invalidated_event:
            rejection_reasons.append("ARM_INVALIDATED")
        if (
            normal_breakout_candidate
            and not same_bar_normal_entry
            and not armed.new_arm
            and not params.use_persistent_armed_entry
        ):
            rejection_reasons.append("PERSISTENT_ARM_DISABLED")
        if is_earnings_upside_gap and fresh_long_breakout and not earnings_gap_go_entry:
            rejection_reasons.append(earnings_gap_class)
            if not price_ok:
                rejection_reasons.append("PRICE_BELOW_FLOOR")

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
                    stock_stop_price=structural_lower,
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
                    exit_reasons=(exit_reason,),
                )
            )

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
            active_entry_type = "NONE"
            structural_break_count = 0

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

        breakout_armed_after_close = armed.breakout_armed and not long_entry
        results.append(
            V25BarResult(
                symbol=symbol,
                bar_index=i,
                bar_time=bar.time,
                upper20=upper20,
                lower10=lower10,
                structural_lower=structural_lower,
                atr=atr,
                efficiency=efficiency,
                rsi=rsi,
                adx=adx,
                trend_state=trend_state,
                trend_stop=trend_stop,
                fresh_long_breakout=fresh_long_breakout,
                earnings_gap_class=earnings_gap_class,
                entry_type=entry_type,
                breakout_armed=breakout_armed_after_close,
                armed_age=armed.armed_age,
                armed_breakout_level=armed.armed_breakout_level,
                armed_max_price=armed.armed_max_price,
                armed_invalidation_level=armed.armed_invalidation_level,
                arm_events=arm_events,
                rejection_reasons=tuple(rejection_reasons),
                entry_selected_breakout_level=entry_selected_breakout_level,
                entry_armed_age=entry_armed_age,
                entry_replay_max_price=entry_replay_max_price,
                signals=tuple(signals),
                position_units_after_close=position_units,
                position_avg_price_after_close=position_avg_price,
            )
        )

    return tuple(results)


__all__ = [
    "PINE_V25_MODEL_ID",
    "PINE_V25_SOURCE_BLOB_SHA",
    "PINE_V25_SOURCE_COMMIT",
    "PINE_V25_SOURCE_PATH",
    "PINE_V25_SOURCE_SHA256",
    "PINE_V25_STRATEGY_VERSION",
    "PROCESS_ORDERS_ON_CLOSE",
    "DailyBar",
    "V25BarResult",
    "V25Parameters",
    "run_v25_parity",
]
