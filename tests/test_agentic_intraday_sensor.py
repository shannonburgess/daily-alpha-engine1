from datetime import UTC, datetime

import pytest

from daily_alpha.agentic_intraday import (
    IntradayPhase,
    intraday_bar_phase,
    intraday_phase,
)
from daily_alpha.agentic_intraday_momentum import evaluate_mu_momentum_signal
from daily_alpha.agentic_intraday_sensor import (
    IntradayObservationBridgePolicy,
    IntradaySensorError,
    IntradaySensorEventType,
    IntradayServerContext,
    build_momentum_observation,
    evaluate_15m_technical_context,
    parse_intraday_sensor_payload,
)


def sensor_payload(**overrides):
    payload = {
        "schema_version": "2026-08-21-agentic-intraday-sensor-v1",
        "source": "TRADINGVIEW_AGENTIC_INTRADAY",
        "event_id": "MU-AGENTIC-EXECUTION_2M_BAR-OPEN-1",
        "event_type": "EXECUTION_2M_BAR",
        "account_id": "PAPER_AGENTIC_INTRADAY_V1",
        "symbol": "MU",
        "instrument": "STOCK",
        "timeframe": "2",
        "phase": "OPENING_2M",
        "bar_time": "2026-08-21T13:38:00Z",
        "open": 129.5,
        "high": 130.1,
        "low": 129.4,
        "close": 130.0,
        "volume": 2_000_000.0,
        "vwap": 129.2,
        "ema9": 129.8,
        "ema20": 129.4,
        "relative_volume": 1.8,
        "average_daily_share_volume_30": 100_000.0,
        "relative_strength_qqq_pct": 0.30,
        "relative_strength_smh_pct": 0.15,
        "session_bar_count": 3,
        "session_high_prior": 129.8,
        "session_low_prior": 128.9,
        "high_3_prior": 129.8,
        "high_5_prior": 129.9,
        "high_10_prior": 130.2,
        "low_3_prior": 128.9,
        "low_5_prior": 128.7,
        "sensor_only": True,
        "paper_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def approved_context(**overrides):
    payload = {
        "daily_context_approved": True,
        "sector_context_approved": True,
        "context_15m_approved": True,
        "canonical_average_daily_share_volume": 25_000_000.0,
        "scheduled_macro_blackout": False,
        "earnings_event_risk": False,
    }
    payload.update(overrides)
    return IntradayServerContext(**payload)


def test_wall_clock_switches_at_ten_but_last_two_minute_bar_remains_opening():
    ten_et = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)

    assert intraday_phase(ten_et) == IntradayPhase.STANDARD_5M
    assert intraday_bar_phase(ten_et, "2M") == IntradayPhase.OPENING_2M
    assert intraday_bar_phase(ten_et, "5M") == IntradayPhase.STANDARD_5M


def test_parser_accepts_final_opening_two_minute_bar_closing_at_ten_et():
    bar = parse_intraday_sensor_payload(
        sensor_payload(
            event_id="MU-AGENTIC-EXECUTION_2M_BAR-1000",
            bar_time="2026-08-21T14:00:00Z",
            phase="OPENING_2M",
        )
    )

    assert bar.event_type == IntradaySensorEventType.EXECUTION_2M_BAR
    assert bar.timeframe == "2M"
    assert bar.phase == IntradayPhase.OPENING_2M


def test_context_bar_can_close_at_ten_while_declaring_opening_phase_from_bar_open():
    bar = parse_intraday_sensor_payload(
        sensor_payload(
            event_id="MU-AGENTIC-CONTEXT-15M-1000",
            event_type="CONTEXT_15M_BAR",
            timeframe="15",
            phase="OPENING_2M",
            bar_time="2026-08-21T14:00:00Z",
            open=129.0,
            high=130.2,
            low=128.9,
            close=130.0,
            vwap=129.4,
            ema9=129.8,
            ema20=129.5,
            relative_strength_qqq_pct=0.25,
        )
    )
    decision = evaluate_15m_technical_context(bar)

    assert bar.event_type == IntradaySensorEventType.CONTEXT_15M_BAR
    assert decision.approved is True
    assert decision.reasons == ()


def test_parser_accepts_null_optional_sensor_values_but_not_missing_required_values():
    bar = parse_intraday_sensor_payload(
        sensor_payload(
            ema9=None,
            ema20=None,
            relative_volume=None,
            average_daily_share_volume_30=None,
            relative_strength_qqq_pct=None,
            relative_strength_smh_pct=None,
            session_high_prior=None,
            session_low_prior=None,
            high_3_prior=None,
            high_5_prior=None,
            high_10_prior=None,
            low_3_prior=None,
            low_5_prior=None,
        )
    )

    assert bar.ema9 is None
    assert bar.relative_volume is None
    assert bar.high_3_prior is None

    with pytest.raises(IntradaySensorError, match="INTRADAY_SENSOR_VWAP_REQUIRED"):
        parse_intraday_sensor_payload(sensor_payload(vwap=None))


def test_parser_fails_closed_on_identity_live_and_phase_mismatches():
    with pytest.raises(IntradaySensorError, match="INTRADAY_SENSOR_ACCOUNT_INVALID"):
        parse_intraday_sensor_payload(sensor_payload(account_id="PAPER_SHADOW_V24"))
    with pytest.raises(IntradaySensorError, match="INTRADAY_SENSOR_SHARES_ONLY"):
        parse_intraday_sensor_payload(sensor_payload(instrument="OPTION"))
    with pytest.raises(IntradaySensorError, match="INTRADAY_SENSOR_LIVE_TRADING_FORBIDDEN"):
        parse_intraday_sensor_payload(sensor_payload(live_trading_enabled=True))
    with pytest.raises(IntradaySensorError, match="INTRADAY_SENSOR_EVENT_PHASE_MISMATCH"):
        parse_intraday_sensor_payload(sensor_payload(phase="STANDARD_5M"))


def test_opening_bridge_uses_server_canonical_liquidity_not_pine_telemetry():
    bar = parse_intraday_sensor_payload(sensor_payload())
    observation = build_momentum_observation(bar, approved_context())
    decision = evaluate_mu_momentum_signal(observation)

    assert bar.sensor_average_daily_share_volume_30 == 100_000.0
    assert observation.average_daily_share_volume == 25_000_000.0
    assert observation.opening_range_established is True
    assert observation.opening_range_high == 129.8
    assert decision.triggered is True
    assert decision.trigger_type == "OPENING_2M_ORB"


def test_opening_bridge_fails_closed_without_server_canonical_liquidity():
    bar = parse_intraday_sensor_payload(sensor_payload())

    with pytest.raises(IntradaySensorError, match="INTRADAY_CANONICAL_LIQUIDITY_REQUIRED"):
        build_momentum_observation(
            bar,
            approved_context(canonical_average_daily_share_volume=None),
        )


def test_standard_five_minute_bridge_maps_continuation_high_and_can_trigger():
    bar = parse_intraday_sensor_payload(
        sensor_payload(
            event_id="MU-AGENTIC-EXECUTION_5M_BAR-1005",
            event_type="EXECUTION_5M_BAR",
            timeframe="5",
            phase="STANDARD_5M",
            bar_time="2026-08-21T14:05:00Z",
            open=130.4,
            high=131.2,
            low=130.6,
            close=131.0,
            vwap=130.4,
            ema9=130.8,
            ema20=130.2,
            relative_volume=1.4,
            relative_strength_qqq_pct=0.20,
            high_3_prior=130.5,
        )
    )
    observation = build_momentum_observation(bar, approved_context())
    decision = evaluate_mu_momentum_signal(observation)

    assert observation.continuation_high == 130.5
    assert decision.triggered is True
    assert decision.trigger_type == "STANDARD_5M_CONTINUATION"


def test_bridge_can_switch_relative_strength_source_to_smh_explicitly():
    bar = parse_intraday_sensor_payload(
        sensor_payload(
            relative_strength_qqq_pct=-0.10,
            relative_strength_smh_pct=0.25,
        )
    )
    observation = build_momentum_observation(
        bar,
        approved_context(),
        IntradayObservationBridgePolicy(relative_strength_source="SMH"),
    )

    assert observation.relative_strength_pct == 0.25


def test_management_and_flatten_sensor_bars_cannot_become_entry_observations():
    management = parse_intraday_sensor_payload(
        sensor_payload(
            event_id="MU-AGENTIC-MANAGEMENT-1535",
            event_type="MANAGEMENT_5M_BAR",
            timeframe="5",
            phase="MANAGEMENT_ONLY",
            bar_time="2026-08-21T19:35:00Z",
        )
    )
    flatten = parse_intraday_sensor_payload(
        sensor_payload(
            event_id="MU-AGENTIC-FLATTEN-1555",
            event_type="FLATTEN_5M_BAR",
            timeframe="5",
            phase="FLATTEN_ONLY",
            bar_time="2026-08-21T19:55:00Z",
        )
    )

    with pytest.raises(IntradaySensorError, match="INTRADAY_EXECUTION_SENSOR_BAR_REQUIRED"):
        build_momentum_observation(management, approved_context())
    with pytest.raises(IntradaySensorError, match="INTRADAY_EXECUTION_SENSOR_BAR_REQUIRED"):
        build_momentum_observation(flatten, approved_context())
