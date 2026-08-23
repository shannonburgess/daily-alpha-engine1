from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_BLOB_SHA,
    PINE_V25_SOURCE_COMMIT,
    PINE_V25_SOURCE_PATH,
    PINE_V25_SOURCE_SHA256,
    PROCESS_ORDERS_ON_CLOSE,
    DailyBar,
    V25Parameters,
    run_v25_parity,
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


def _fast_params(**overrides) -> V25Parameters:
    values = {
        "entry_len": 3,
        "exit_len": 2,
        "structural_exit_len": 2,
        "atr_len": 2,
        "efficiency_len": 2,
        "min_prior_bull_bars": 1,
        "use_rsi_cap": False,
        "use_adx_filter": False,
        "use_efficiency_gate": False,
        "use_price_floor": False,
        "use_earnings_gap_sleeve": False,
        "use_failed_breakout_exit": False,
        "use_structural_runner_exit": False,
        "use_runner_management": False,
        "start_time": datetime(2025, 1, 1, tzinfo=UTC),
        "end_time": datetime(2027, 1, 1, tzinfo=UTC),
        "enable_shadow_forward_test": True,
        "shadow_forward_start": datetime(2025, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return V25Parameters(**values)


def test_v25_contract_is_bound_to_exact_audited_challenger_source():
    assert PINE_V25_MODEL_ID == "PAPER_SHADOW_V25"
    assert PINE_V25_SOURCE_PATH == "tradingview/da_turtle_20_10_v2_5_shadow_challenger.pine"
    assert PINE_V25_SOURCE_COMMIT == "b2a214c6b7a689453df5de7bb870c352456ebe8c"
    assert PINE_V25_SOURCE_BLOB_SHA == "2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5"
    assert PINE_V25_SOURCE_SHA256 == (
        "77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718"
    )
    assert PROCESS_ORDERS_ON_CLOSE is True


def test_same_bar_normal_entry_is_close_processed_without_redundant_arm():
    bars = [_bar(i, 100.0 + i) for i in range(7)]

    results = run_v25_parity("TEST", bars, _fast_params())

    entry = results[3]
    assert entry.entry_type == "NORMAL_BREAKOUT"
    assert [signal.action for signal in entry.signals] == ["ENTRY_LONG"]
    assert entry.signals[0].price == pytest.approx(103.0)
    assert entry.arm_events == ()
    assert entry.position_units_after_close == 2


def test_price_breakout_arms_then_confirms_when_quality_becomes_ready():
    bars = [_bar(i, close) for i, close in enumerate([100, 101, 102, 103, 104.2, 104.4])]
    params = _fast_params(
        use_price_floor=True,
        min_underlying_price=104.0,
        max_chase_atr=5.0,
    )

    results = run_v25_parity("TEST", bars, params)

    armed = results[3]
    confirmed = results[4]
    assert armed.signals == ()
    assert armed.arm_events == ("BREAKOUT_ARMED",)
    assert armed.breakout_armed is True
    assert "ARMED_WAIT_PRICE" in armed.rejection_reasons
    assert confirmed.entry_type == "ARMED_BREAKOUT_CONFIRM"
    assert confirmed.armed_age == 1
    assert [signal.action for signal in confirmed.signals] == ["ENTRY_LONG"]
    assert confirmed.position_units_after_close == 2


def test_arm_structural_invalidation_is_explicit_no_trade_lineage():
    bars = [_bar(i, close) for i, close in enumerate([100, 101, 102, 103, 100, 100.2])]
    params = _fast_params(
        use_price_floor=True,
        min_underlying_price=200.0,
        arm_invalidation_atr=0.25,
    )

    results = run_v25_parity("TEST", bars, params)

    assert results[3].arm_events == ("BREAKOUT_ARMED",)
    invalidated = results[4]
    assert "ARM_INVALIDATED" in invalidated.arm_events
    assert "ARM_INVALIDATED" in invalidated.rejection_reasons
    assert invalidated.signals == ()
    assert invalidated.breakout_armed is False


def test_arm_timeout_occurs_only_after_max_age():
    bars = [_bar(i, close) for i, close in enumerate([100, 101, 102, 103, 103.1, 103.2, 103.3, 103.4])]
    params = _fast_params(
        use_price_floor=True,
        min_underlying_price=200.0,
        armed_max_bars=2,
        arm_invalidation_atr=5.0,
    )

    results = run_v25_parity("TEST", bars, params)

    assert results[5].armed_age == 2
    assert results[5].breakout_armed is True
    expired = results[6]
    assert expired.armed_age == 3
    assert "ARM_EXPIRED" in expired.arm_events
    assert "ARM_EXPIRED" in expired.rejection_reasons
    assert expired.breakout_armed is False


def test_runner_adds_and_harvest_keep_v24_size_sequence():
    bars = [_bar(i, 100.0 + i) for i in range(10)]
    params = _fast_params(
        use_runner_management=True,
        add1_atr=0.25,
        add2_atr=0.50,
        harvest_atr=0.75,
    )

    results = run_v25_parity("TEST", bars, params)

    assert [signal.action for signal in results[3].signals] == ["ENTRY_LONG"]
    assert [(s.action, s.runner_stage) for s in results[4].signals] == [
        ("ADD", "ADD_1_ATR")
    ]
    assert [(s.action, s.runner_stage) for s in results[5].signals] == [
        ("ADD", "ADD_2_ATR")
    ]
    assert [(s.action, s.runner_stage) for s in results[6].signals] == [
        ("PARTIAL", "HARVEST_3_ATR")
    ]
    assert results[6].position_units_after_close == 3


def test_structural_runner_exit_replaces_legacy_exit_by_default():
    bars = [
        _bar(0, 100),
        _bar(1, 101),
        _bar(2, 102),
        _bar(3, 103),
        _bar(4, 100.0),
        _bar(5, 99.5),
    ]
    params = _fast_params(
        use_structural_runner_exit=True,
        structural_exit_len=2,
        structural_confirm_bars=1,
        use_legacy_turtle_exit=False,
        use_legacy_adaptive_exit=False,
    )

    results = run_v25_parity("TEST", bars, params)

    assert results[3].signals[0].action == "ENTRY_LONG"
    exit_signal = next(signal for signal in results[4].signals if signal.action == "EXIT")
    assert exit_signal.exit_reasons == ("STRUCTURAL_EXIT",)
    assert results[4].position_units_after_close == 0


def test_shadow_forward_gate_prevents_pre_boundary_entries():
    bars = [_bar(i, 100.0 + i) for i in range(7)]
    params = _fast_params(shadow_forward_start=datetime(2027, 1, 1, tzinfo=UTC))

    results = run_v25_parity("TEST", bars, params)

    assert all(not result.signals for result in results)
    assert all(not result.breakout_armed for result in results)


def test_input_bars_must_be_strictly_chronological():
    bar = _bar(0, 100)
    with pytest.raises(ValueError, match="strictly chronological"):
        run_v25_parity("TEST", [bar, bar], _fast_params())
