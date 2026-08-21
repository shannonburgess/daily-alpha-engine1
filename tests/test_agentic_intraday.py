from datetime import UTC, datetime

import pytest

from daily_alpha.agentic_intraday import (
    AGENTIC_INTRADAY_ACCOUNT,
    IntradayAction,
    IntradayPhase,
    IntradayPortfolioState,
    IntradaySignalEvent,
    IntradayState,
    advance_intraday_state,
    evaluate_intraday_entry,
    intraday_phase,
    management_timeframe,
    must_flatten,
    required_entry_timeframe,
    validate_event_identity,
)


def at_utc(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 21, hour, minute, tzinfo=UTC)


def entry_event(**overrides):
    payload = {
        "event_id": "MU-INTRADAY-1",
        "action": IntradayAction.ENTRY_LONG,
        "timeframe": "2M",
        "price": 130.0,
        "observed_at": at_utc(13, 45),
        "daily_context_approved": True,
        "context_15m_approved": True,
        "stock_stop_price": 128.0,
        "average_daily_share_volume": 25_000_000.0,
    }
    payload.update(overrides)
    return IntradaySignalEvent(**payload)


def portfolio(**overrides):
    payload = {
        "nav": 1_000_000.0,
        "trades_opened_today": 0,
        "daily_new_risk_dollars": 0.0,
        "open_symbols": (),
    }
    payload.update(overrides)
    return IntradayPortfolioState(**payload)


def test_session_clock_routes_first_30_minutes_to_two_minute_engine():
    assert intraday_phase(at_utc(13, 30)) == IntradayPhase.OPENING_2M
    assert intraday_phase(at_utc(13, 59)) == IntradayPhase.OPENING_2M
    assert required_entry_timeframe(IntradayPhase.OPENING_2M) == "2M"
    assert management_timeframe(at_utc(13, 45)) == "2M"


def test_session_clock_switches_to_five_minute_engine_at_ten_et():
    assert intraday_phase(at_utc(14, 0)) == IntradayPhase.STANDARD_5M
    assert required_entry_timeframe(IntradayPhase.STANDARD_5M) == "5M"
    assert management_timeframe(at_utc(14, 0)) == "5M"


def test_late_session_becomes_management_then_flatten_only():
    assert intraday_phase(at_utc(19, 30)) == IntradayPhase.MANAGEMENT_ONLY
    assert intraday_phase(at_utc(19, 50)) == IntradayPhase.FLATTEN_ONLY
    assert management_timeframe(at_utc(19, 45)) == "5M"
    assert must_flatten(at_utc(19, 50), has_open_position=True) is True
    assert must_flatten(at_utc(19, 50), has_open_position=False) is False


def test_weekend_is_closed():
    saturday = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)
    assert intraday_phase(saturday) == IntradayPhase.CLOSED


def test_opening_entry_requires_two_minute_signal():
    result = evaluate_intraday_entry(
        entry_event(timeframe="5M"),
        portfolio(),
    )

    assert result.approved is False
    assert "ENTRY_REQUIRES_2M" in result.reasons


def test_standard_session_entry_requires_five_minute_signal():
    result = evaluate_intraday_entry(
        entry_event(timeframe="2M", observed_at=at_utc(15, 0)),
        portfolio(),
    )

    assert result.approved is False
    assert "ENTRY_REQUIRES_5M" in result.reasons


def test_management_only_and_flatten_only_reject_new_entries():
    management = evaluate_intraday_entry(
        entry_event(timeframe="5M", observed_at=at_utc(19, 35)),
        portfolio(),
    )
    flatten = evaluate_intraday_entry(
        entry_event(timeframe="5M", observed_at=at_utc(19, 55)),
        portfolio(),
    )

    assert management.approved is False
    assert "ENTRY_NOT_ALLOWED_IN_MANAGEMENT_ONLY" in management.reasons
    assert flatten.approved is False
    assert "ENTRY_NOT_ALLOWED_IN_FLATTEN_ONLY" in flatten.reasons


def test_entry_requires_daily_and_fifteen_minute_context():
    result = evaluate_intraday_entry(
        entry_event(daily_context_approved=False, context_15m_approved=False),
        portfolio(),
    )

    assert result.approved is False
    assert "DAILY_CONTEXT_NOT_APPROVED" in result.reasons
    assert "CONTEXT_15M_NOT_APPROVED" in result.reasons


def test_company_liquidity_gate_remains_strictly_above_one_point_five_million():
    equal = evaluate_intraday_entry(
        entry_event(average_daily_share_volume=1_500_000.0),
        portfolio(),
    )
    above = evaluate_intraday_entry(
        entry_event(average_daily_share_volume=1_500_001.0),
        portfolio(),
    )

    assert equal.approved is False
    assert "LIQUIDITY_FILTERED" in equal.reasons
    assert above.approved is True


def test_valid_entry_is_sized_by_risk_and_existing_two_percent_notional_cap():
    result = evaluate_intraday_entry(entry_event(), portfolio())

    assert result.approved is True
    assert result.reasons == ()
    assert result.share_quantity == 153
    assert result.planned_risk_dollars == 306.0
    assert result.planned_notional_dollars == 19_890.0


def test_daily_trade_limit_and_daily_risk_limit_fail_closed():
    trade_limit = evaluate_intraday_entry(
        entry_event(),
        portfolio(trades_opened_today=2),
    )
    risk_limit = evaluate_intraday_entry(
        entry_event(),
        portfolio(daily_new_risk_dollars=5_000.0),
    )

    assert "INTRADAY_DAILY_TRADE_LIMIT" in trade_limit.reasons
    assert "INTRADAY_DAILY_RISK_LIMIT" in risk_limit.reasons
    assert trade_limit.share_quantity == 0
    assert risk_limit.share_quantity == 0


def test_existing_mu_position_blocks_a_second_entry():
    result = evaluate_intraday_entry(
        entry_event(),
        portfolio(open_symbols=("MU",)),
    )

    assert result.approved is False
    assert "OPEN_INTRADAY_POSITION_ALREADY_EXISTS" in result.reasons


def test_pilot_is_mu_stock_only_and_cannot_use_shadow_account():
    with pytest.raises(ValueError, match="INTRADAY_PILOT_SYMBOL_INVALID"):
        validate_event_identity(entry_event(symbol="SNDK"))

    with pytest.raises(ValueError, match="INTRADAY_SHARES_ONLY"):
        validate_event_identity(entry_event(instrument="OPTION"))

    with pytest.raises(ValueError, match="INTRADAY_ACCOUNT_ID_INVALID"):
        validate_event_identity(entry_event(account_id="PAPER_SHADOW_V24"))

    assert entry_event().account_id == AGENTIC_INTRADAY_ACCOUNT


def test_live_authorization_is_impossible_at_the_event_boundary():
    with pytest.raises(ValueError, match="INTRADAY_LIVE_AUTHORIZATION_FORBIDDEN"):
        validate_event_identity(entry_event(trading_authorized=True))

    with pytest.raises(ValueError, match="INTRADAY_LIVE_TRADING_FORBIDDEN"):
        validate_event_identity(entry_event(live_trading_enabled=True))


def test_state_machine_allows_two_to_five_minute_handoff_but_rejects_skips():
    assert (
        advance_intraday_state(IntradayState.WATCHING_2M, IntradayState.WATCHING_5M)
        == IntradayState.WATCHING_5M
    )
    assert (
        advance_intraday_state(IntradayState.PAPER_OPEN, IntradayState.MANAGED_5M)
        == IntradayState.MANAGED_5M
    )
    with pytest.raises(ValueError, match="INTRADAY_STATE_TRANSITION_INVALID"):
        advance_intraday_state(IntradayState.DISCOVERED, IntradayState.PAPER_OPEN)
