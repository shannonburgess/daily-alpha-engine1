from daily_alpha.pine_v25_armed_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_COMMIT,
    PINE_V25_SOURCE_SHA256,
    PROCESS_ORDERS_ON_CLOSE,
    V25ArmedBreakoutMachine,
    V25ArmedInputs,
    V25ArmedParameters,
)


def _inputs(bar_index: int, **overrides) -> V25ArmedInputs:
    values = {
        "bar_index": bar_index,
        "close": 100.0,
        "upper20": 100.0,
        "atr": 2.0,
        "position_is_flat": True,
        "normal_breakout_candidate": False,
        "same_bar_normal_entry": False,
        "trend_state": -1,
        "normal_trend_mature": False,
        "fresh_trend_ok": True,
        "quality_entry_ok": False,
        "bar_confirmed": True,
    }
    values.update(overrides)
    return V25ArmedInputs(**values)


def test_sh25_contract_uses_exact_audited_source_lineage():
    assert PINE_V25_MODEL_ID == "PAPER_SHADOW_V25"
    assert PINE_V25_SOURCE_COMMIT == "b2a214c6b7a689453df5de7bb870c352456ebe8c"
    assert PINE_V25_SOURCE_SHA256 == (
        "77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718"
    )
    assert PROCESS_ORDERS_ON_CLOSE is True


def test_price_breakout_arms_even_when_trend_and_quality_are_not_ready():
    machine = V25ArmedBreakoutMachine()

    snapshot = machine.step(
        _inputs(
            10,
            close=101.0,
            normal_breakout_candidate=True,
            same_bar_normal_entry=False,
            trend_state=-1,
            normal_trend_mature=False,
            quality_entry_ok=False,
        )
    )

    assert snapshot.new_arm is True
    assert snapshot.breakout_armed is True
    assert snapshot.armed_age == 0
    assert snapshot.armed_breakout_level == 100.0
    assert snapshot.armed_max_price == 102.0
    assert snapshot.armed_invalidation_level == 99.0
    assert snapshot.armed_confirmed_entry is False


def test_arm_survives_unready_trend_then_confirms_later_within_chase_envelope():
    machine = V25ArmedBreakoutMachine()
    machine.step(
        _inputs(
            10,
            close=101.0,
            normal_breakout_candidate=True,
        )
    )

    waiting = machine.step(
        _inputs(
            11,
            close=101.5,
            trend_state=-1,
            normal_trend_mature=False,
            quality_entry_ok=False,
        )
    )
    confirmed = machine.step(
        _inputs(
            12,
            close=101.75,
            trend_state=1,
            normal_trend_mature=True,
            fresh_trend_ok=True,
            quality_entry_ok=True,
        )
    )

    assert waiting.breakout_armed is True
    assert waiting.armed_confirmed_entry is False
    assert confirmed.armed_age == 2
    assert confirmed.armed_above_breakout is True
    assert confirmed.armed_within_chase is True
    assert confirmed.armed_trend_ready is True
    assert confirmed.armed_confirmed_entry is True

    after_entry = machine.step(_inputs(13, close=101.5, trend_state=1))
    assert after_entry.breakout_armed is False


def test_arm_does_not_confirm_when_price_exceeds_plus_one_atr_no_chase_ceiling():
    machine = V25ArmedBreakoutMachine()
    machine.step(_inputs(20, close=100.5, normal_breakout_candidate=True))

    snapshot = machine.step(
        _inputs(
            21,
            close=102.01,
            trend_state=1,
            normal_trend_mature=True,
            quality_entry_ok=True,
        )
    )

    assert snapshot.armed_active is True
    assert snapshot.armed_above_breakout is True
    assert snapshot.armed_within_chase is False
    assert snapshot.armed_confirmed_entry is False
    assert snapshot.breakout_armed is True


def test_structural_invalidation_clears_arm_without_waiting_for_trend_quality():
    machine = V25ArmedBreakoutMachine()
    machine.step(_inputs(30, close=100.5, normal_breakout_candidate=True))

    snapshot = machine.step(_inputs(31, close=98.99))

    assert snapshot.arm_invalidated_event is True
    assert snapshot.arm_expired_event is False
    assert snapshot.breakout_armed is False
    assert snapshot.armed_active is False


def test_arm_is_valid_through_max_age_and_expires_only_after_it():
    machine = V25ArmedBreakoutMachine(V25ArmedParameters(armed_max_bars=2))
    machine.step(_inputs(40, close=100.5, normal_breakout_candidate=True))

    at_limit = machine.step(_inputs(42, close=100.5))
    expired = machine.step(_inputs(43, close=100.5))

    assert at_limit.armed_age == 2
    assert at_limit.armed_active is True
    assert at_limit.arm_expired_event is False
    assert expired.armed_age == 3
    assert expired.arm_expired_event is True
    assert expired.breakout_armed is False


def test_same_bar_normal_entry_does_not_create_redundant_arm():
    machine = V25ArmedBreakoutMachine()

    snapshot = machine.step(
        _inputs(
            50,
            close=101.0,
            normal_breakout_candidate=True,
            same_bar_normal_entry=True,
            trend_state=1,
            normal_trend_mature=True,
            quality_entry_ok=True,
        )
    )

    assert snapshot.new_arm is False
    assert snapshot.breakout_armed is False
    assert snapshot.armed_confirmed_entry is False
