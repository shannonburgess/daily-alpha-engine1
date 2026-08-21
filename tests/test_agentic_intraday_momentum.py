from datetime import UTC, datetime

import pytest

from daily_alpha.agentic_intraday import (
    IntradayPortfolioState,
    evaluate_intraday_entry,
)
from daily_alpha.agentic_intraday_momentum import (
    IntradayMomentumObservation,
    build_intraday_entry_event,
    evaluate_mu_momentum_signal,
)

OPENING_TIME = datetime(2026, 8, 21, 13, 45, tzinfo=UTC)
STANDARD_TIME = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


def opening_observation(**overrides):
    payload = {
        "observation_id": "MU-OPENING-1",
        "timeframe": "2M",
        "observed_at": OPENING_TIME,
        "close": 130.0,
        "high": 130.1,
        "low": 129.0,
        "vwap": 129.2,
        "relative_volume": 1.8,
        "relative_strength_pct": 0.30,
        "daily_context_approved": True,
        "context_15m_approved": True,
        "sector_context_approved": True,
        "average_daily_share_volume": 25_000_000.0,
        "opening_range_established": True,
        "opening_range_high": 129.8,
    }
    payload.update(overrides)
    return IntradayMomentumObservation(**payload)


def standard_observation(**overrides):
    payload = {
        "observation_id": "MU-STANDARD-1",
        "timeframe": "5M",
        "observed_at": STANDARD_TIME,
        "close": 131.0,
        "high": 131.2,
        "low": 130.2,
        "vwap": 130.4,
        "relative_volume": 1.4,
        "relative_strength_pct": 0.25,
        "daily_context_approved": True,
        "context_15m_approved": True,
        "sector_context_approved": True,
        "average_daily_share_volume": 25_000_000.0,
        "continuation_high": 130.8,
        "ema9": 130.6,
        "ema20": 130.2,
    }
    payload.update(overrides)
    return IntradayMomentumObservation(**payload)


def test_opening_two_minute_orb_triggers_with_full_context():
    result = evaluate_mu_momentum_signal(opening_observation())

    assert result.triggered is True
    assert result.trigger_type == "OPENING_2M_ORB"
    assert result.reasons == ()
    assert result.entry_price == 130.0
    assert result.stock_stop_price == 129.2


def test_opening_range_must_exist_and_breakout_must_be_confirmed():
    result = evaluate_mu_momentum_signal(
        opening_observation(
            opening_range_established=False,
            opening_range_high=130.0,
        )
    )

    assert result.triggered is False
    assert "OPENING_RANGE_NOT_ESTABLISHED" in result.reasons
    assert "OPENING_RANGE_BREAKOUT_NOT_CONFIRMED" in result.reasons


def test_opening_signal_blocks_low_relative_volume_and_excess_vwap_extension():
    result = evaluate_mu_momentum_signal(
        opening_observation(
            close=131.0,
            high=131.1,
            relative_volume=1.49,
        )
    )

    assert result.triggered is False
    assert "OPENING_RELATIVE_VOLUME_TOO_LOW" in result.reasons
    assert "OPENING_VWAP_EXTENSION_TOO_HIGH" in result.reasons


def test_standard_five_minute_continuation_triggers_with_ema_alignment():
    result = evaluate_mu_momentum_signal(standard_observation())

    assert result.triggered is True
    assert result.trigger_type == "STANDARD_5M_CONTINUATION"
    assert result.reasons == ()
    assert result.stock_stop_price == 130.4


def test_standard_signal_requires_five_minute_timeframe():
    result = evaluate_mu_momentum_signal(
        standard_observation(timeframe="2M"),
    )

    assert result.triggered is False
    assert "SIGNAL_REQUIRES_5M" in result.reasons


def test_standard_signal_requires_continuation_and_ema_trend():
    result = evaluate_mu_momentum_signal(
        standard_observation(
            continuation_high=131.0,
            ema9=130.0,
            ema20=130.2,
        )
    )

    assert result.triggered is False
    assert "CONTINUATION_BREAKOUT_NOT_CONFIRMED" in result.reasons
    assert "STANDARD_EMA_TREND_NOT_ALIGNED" in result.reasons


def test_context_sector_macro_and_earnings_can_each_block_signal():
    result = evaluate_mu_momentum_signal(
        opening_observation(
            daily_context_approved=False,
            context_15m_approved=False,
            sector_context_approved=False,
            scheduled_macro_blackout=True,
            earnings_event_risk=True,
        )
    )

    assert result.triggered is False
    assert "DAILY_CONTEXT_NOT_APPROVED" in result.reasons
    assert "CONTEXT_15M_NOT_APPROVED" in result.reasons
    assert "SECTOR_CONTEXT_NOT_APPROVED" in result.reasons
    assert "SCHEDULED_MACRO_BLACKOUT" in result.reasons
    assert "EARNINGS_EVENT_RISK_BLOCKED" in result.reasons


def test_relative_strength_must_be_positive():
    result = evaluate_mu_momentum_signal(
        opening_observation(relative_strength_pct=0.0),
    )

    assert result.triggered is False
    assert "RELATIVE_STRENGTH_NOT_POSITIVE" in result.reasons


def test_triggered_signal_converts_to_stage_one_stock_entry_contract():
    observation = opening_observation()
    signal = evaluate_mu_momentum_signal(observation)
    event = build_intraday_entry_event(observation, signal)
    risk = evaluate_intraday_entry(
        event,
        IntradayPortfolioState(nav=1_000_000.0),
    )

    assert event.symbol == "MU"
    assert event.instrument == "STOCK"
    assert event.timeframe == "2M"
    assert event.stock_stop_price == 129.2
    assert event.trading_authorized is False
    assert event.live_trading_enabled is False
    assert risk.approved is True
    assert risk.share_quantity > 0


def test_non_triggered_decision_cannot_create_entry_event():
    observation = opening_observation(relative_volume=1.0)
    signal = evaluate_mu_momentum_signal(observation)

    with pytest.raises(ValueError, match="INTRADAY_MOMENTUM_SIGNAL_NOT_TRIGGERED"):
        build_intraday_entry_event(observation, signal)


def test_sndk_cannot_enter_mu_v1_signal_engine():
    with pytest.raises(ValueError, match="INTRADAY_PILOT_SYMBOL_INVALID"):
        evaluate_mu_momentum_signal(opening_observation(symbol="SNDK"))
