from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.pine_v24_parity import (
    PROCESS_ORDERS_ON_CLOSE,
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_PATH,
    DailyBar,
    V24Parameters,
    run_v24_parity,
)


def _bar(day: int, close: float, *, high_pad: float = 0.5, low_pad: float = 0.5) -> DailyBar:
    return DailyBar(
        time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
        open=close - 0.2,
        high=close + high_pad,
        low=close - low_pad,
        close=close,
        volume=1_000_000,
    )


def _fast_params(**overrides) -> V24Parameters:
    values = {
        "entry_len": 3,
        "exit_len": 2,
        "atr_len": 2,
        "efficiency_len": 2,
        "min_prior_bull_bars": 1,
        "use_rsi_cap": False,
        "use_adx_filter": False,
        "use_efficiency_gate": False,
        "use_price_floor": False,
        "use_earnings_gap_sleeve": False,
        "use_trend_exit": False,
        "add1_atr": 0.25,
        "add2_atr": 0.50,
        "harvest_atr": 0.75,
        "start_time": datetime(2025, 1, 1, tzinfo=UTC),
        "end_time": datetime(2027, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return V24Parameters(**values)


def test_v24_contract_is_the_frozen_sh24_close_processed_control():
    assert PINE_V24_SOURCE_PATH == "tradingview/da_turtle_20_10_v2_4.pine"
    assert PINE_V24_MODEL_ID == "PAPER_SHADOW_V24"
    assert PROCESS_ORDERS_ON_CLOSE is True


def test_entry_runner_adds_and_harvest_are_close_processed_on_separate_bars():
    bars = [_bar(i, 100.0 + i) for i in range(10)]

    results = run_v24_parity("TEST", bars, _fast_params())

    assert [signal.action for signal in results[3].signals] == ["ENTRY_LONG"]
    assert results[3].signals[0].price == pytest.approx(103.0)
    assert results[3].position_units_after_close == 2

    assert [(signal.action, signal.runner_stage) for signal in results[4].signals] == [
        ("ADD", "ADD_1_ATR")
    ]
    assert results[4].position_units_after_close == 3

    assert [(signal.action, signal.runner_stage) for signal in results[5].signals] == [
        ("ADD", "ADD_2_ATR")
    ]
    assert results[5].position_units_after_close == 4

    assert [(signal.action, signal.runner_stage) for signal in results[6].signals] == [
        ("PARTIAL", "HARVEST_3_ATR")
    ]
    assert results[6].position_units_after_close == 3


def test_fresh_entry_does_not_add_on_the_same_bar():
    bars = [_bar(i, close) for i, close in enumerate([100, 100.5, 101, 105, 110])]

    results = run_v24_parity("TEST", bars, _fast_params())

    entry = next(result for result in results if result.entry_type == "NORMAL_BREAKOUT")
    assert [signal.action for signal in entry.signals] == ["ENTRY_LONG"]
    assert entry.position_units_after_close == 2


def test_failed_breakout_exits_during_three_bar_window():
    bars = [
        _bar(0, 100),
        _bar(1, 101),
        _bar(2, 102),
        _bar(3, 103),
        _bar(4, 102.25),
        _bar(5, 100.5),
    ]

    results = run_v24_parity(
        "TEST",
        bars,
        _fast_params(
            use_runner_management=False,
            use_failed_breakout_exit=True,
            failed_breakout_bars=3,
        ),
    )

    assert results[3].signals[0].action == "ENTRY_LONG"
    assert [signal.action for signal in results[4].signals] == ["EXIT"]
    assert results[4].signals[0].exit_reasons == ("FAILED_BREAKOUT_EXIT",)
    assert results[4].position_units_after_close == 0


def test_price_gate_preserves_no_trade_rejection_lineage():
    bars = [_bar(i, close) for i, close in enumerate([20, 21, 22, 23, 24])]

    results = run_v24_parity(
        "TEST",
        bars,
        _fast_params(use_price_floor=True, min_underlying_price=25.0),
    )

    blocked = results[3]
    assert blocked.fresh_long_breakout is True
    assert blocked.entry_type == "NONE"
    assert blocked.signals == ()
    assert "PRICE_BELOW_FLOOR" in blocked.rejection_reasons
    assert blocked.position_units_after_close == 0


def test_input_bars_must_be_strictly_chronological():
    bar = _bar(0, 100)
    with pytest.raises(ValueError, match="strictly chronological"):
        run_v24_parity("TEST", [bar, bar], _fast_params())
