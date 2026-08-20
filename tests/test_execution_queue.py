from datetime import UTC, datetime

from daily_alpha.execution_queue import (
    CANCEL_STATUS,
    EXECUTE_STATUS,
    RETRY_STATUS,
    WAIT_STATUS,
    build_pending_action,
    merge_pending_actions,
    prepare_next_session_signal,
)
from daily_alpha.execution_universe import ScannerState


def _state() -> ScannerState:
    return ScannerState(
        symbol="MU",
        entry_date="2026-08-17",
        runner_base_entry=100.0,
        runner_base_atr=5.0,
        entry_breakout_level=98.0,
    )


def _entry_pending():
    return build_pending_action(
        symbol="MU",
        action="ENTRY_LONG",
        reason="NORMAL_BREAKOUT",
        signal={
            "source": "DAILY_ALPHA_SCANNER",
            "signal_id": "DA-SCAN-MU-2026-08-17-ENTRY_LONG",
            "symbol": "MU",
            "action": "ENTRY_LONG",
            "strategy": "DA_TURTLE_ADAPTIVE_TREND",
            "strategy_version": "2.4",
            "timeframe": "D",
            "price": 100.0,
            "bar_time": "2026-08-17T20:20:00+00:00",
            "entry_type": "NORMAL_BREAKOUT",
            "stock_stop_price": 95.0,
            "average_daily_dollar_volume": 100_000_000.0,
        },
        market_date="2026-08-17",
        created_at=datetime(2026, 8, 17, 20, 20, tzinfo=UTC),
        state_before=None,
        state_after=_state(),
    )


def test_same_day_pending_action_cannot_execute():
    decision = prepare_next_session_signal(
        _entry_pending(),
        stock_price=101.0,
        now=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
    )
    assert decision.status == WAIT_STATUS
    assert decision.signal is None


def test_next_session_entry_executes_only_inside_starter_zone():
    decision = prepare_next_session_signal(
        _entry_pending(),
        stock_price=101.0,
        now=datetime(2026, 8, 18, 13, 45, tzinfo=UTC),
    )
    assert decision.status == EXECUTE_STATUS
    assert decision.should_execute is True
    assert decision.signal["price"] == 101.0
    assert decision.signal["origin_signal_price"] == 100.0
    assert decision.signal["execution_timing"] == "NEXT_REGULAR_SESSION"


def test_next_session_entry_cancels_when_breakout_fails():
    decision = prepare_next_session_signal(
        _entry_pending(),
        stock_price=97.0,
        now=datetime(2026, 8, 18, 13, 45, tzinfo=UTC),
    )
    assert decision.status == CANCEL_STATUS
    assert decision.reason == "CANCEL_BREAKOUT_NO_LONGER_VALID"


def test_next_session_entry_cancels_when_price_is_already_at_add1():
    decision = prepare_next_session_signal(
        _entry_pending(),
        stock_price=105.0,
        now=datetime(2026, 8, 18, 13, 45, tzinfo=UTC),
    )
    assert decision.status == CANCEL_STATUS
    assert decision.reason == "CANCEL_CHASE_ALREADY_AT_ADD1_LEVEL"


def test_continuation_entry_honors_explicit_replay_max_price():
    pending = _entry_pending()
    pending["signal"]["entry_variant"] = "ACTIVE_BUY_CONTINUATION"
    pending["signal"]["replay_max_price"] = 102.0

    decision = prepare_next_session_signal(
        pending,
        stock_price=102.5,
        now=datetime(2026, 8, 18, 13, 45, tzinfo=UTC),
    )

    assert decision.status == CANCEL_STATUS
    assert decision.reason == "CANCEL_CONTINUATION_REPLAY_MAX_PRICE"
    assert decision.signal is None


def test_pending_exit_is_executable_next_session_without_price_trigger_recheck():
    state = _state()
    pending = build_pending_action(
        symbol="MU",
        action="EXIT",
        reason="TURTLE_EXIT",
        signal={
            "source": "DAILY_ALPHA_SCANNER",
            "signal_id": "DA-SCAN-MU-2026-08-17-EXIT",
            "symbol": "MU",
            "action": "EXIT",
            "strategy": "DA_TURTLE_ADAPTIVE_TREND",
            "strategy_version": "2.4",
            "timeframe": "D",
            "price": 96.0,
            "bar_time": "2026-08-17T20:20:00+00:00",
        },
        market_date="2026-08-17",
        created_at=datetime(2026, 8, 17, 20, 20, tzinfo=UTC),
        state_before=state,
        state_after=None,
    )
    decision = prepare_next_session_signal(
        pending,
        stock_price=99.0,
        now=datetime(2026, 8, 18, 13, 45, tzinfo=UTC),
    )
    assert decision.status == EXECUTE_STATUS
    assert decision.signal["action"] == "EXIT"


def test_retry_action_survives_market_holiday_when_no_new_close_confirmed():
    pending = _entry_pending()
    pending["status"] = RETRY_STATUS
    merged = merge_pending_actions(
        [pending],
        [],
        now=datetime(2026, 8, 18, 20, 20, tzinfo=UTC),
        confirmed_market_date=None,
    )
    assert len(merged) == 1
    assert merged[0]["symbol"] == "MU"


def test_old_pending_action_drops_after_a_new_regular_close_is_confirmed():
    merged = merge_pending_actions(
        [_entry_pending()],
        [],
        now=datetime(2026, 8, 18, 20, 20, tzinfo=UTC),
        confirmed_market_date="2026-08-18",
    )
    assert merged == []


def test_pending_action_expires_after_seven_days():
    decision = prepare_next_session_signal(
        _entry_pending(),
        stock_price=101.0,
        now=datetime(2026, 8, 25, 20, 21, tzinfo=UTC),
    )
    assert decision.status == CANCEL_STATUS
    assert decision.reason == "CANCEL_PENDING_ACTION_EXPIRED"
