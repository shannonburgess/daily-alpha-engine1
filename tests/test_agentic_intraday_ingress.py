import json
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic_intraday_ingress import (
    AgenticIntradayIngressAuthError,
    AgenticIntradayIngressError,
    AgenticIntradayServerContext,
    build_agentic_momentum_observation,
    build_agentic_sensor_record,
    derive_agentic_15m_context,
)
from daily_alpha.agentic_intraday_momentum import evaluate_mu_momentum_signal

SECRET = "test-intraday-secret"


def sensor_payload(
    *,
    event_type: str = "EXECUTION_2M_BAR",
    timeframe: str = "2",
    phase: str = "OPENING_2M",
    bar_time: datetime = datetime(2026, 8, 21, 13, 46, tzinfo=UTC),
    **overrides,
):
    payload = {
        "webhook_secret": SECRET,
        "schema_version": "2026-08-21-agentic-intraday-sensor-v1",
        "source": "TRADINGVIEW_AGENTIC_INTRADAY",
        "event_id": f"MU-{event_type}-{int(bar_time.timestamp())}",
        "event_type": event_type,
        "account_id": "PAPER_AGENTIC_INTRADAY_V1",
        "symbol": "MU",
        "instrument": "STOCK",
        "timeframe": timeframe,
        "phase": phase,
        "bar_time": bar_time.isoformat().replace("+00:00", "Z"),
        "open": 129.8,
        "high": 130.6,
        "low": 129.2,
        "close": 130.5,
        "volume": 2_000_000,
        "vwap": 129.5,
        "ema9": 130.2,
        "ema20": 129.8,
        "relative_volume": 1.8,
        "average_daily_share_volume_30": 25_000_000,
        "relative_strength_qqq_pct": 0.15,
        "relative_strength_smh_pct": 0.25,
        "session_bar_count": 4,
        "session_high_prior": 130.0,
        "session_low_prior": 128.9,
        "high_3_prior": 130.1,
        "high_5_prior": 130.2,
        "high_10_prior": 130.3,
        "low_3_prior": 129.0,
        "low_5_prior": 128.8,
        "sensor_only": True,
        "paper_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def event(payload):
    return {"body": json.dumps(payload), "isBase64Encoded": False}


def record(payload, *, received_at=None):
    bar_time = datetime.fromisoformat(payload["bar_time"].replace("Z", "+00:00"))
    return build_agentic_sensor_record(
        event(payload),
        expected_secret=SECRET,
        received_at=received_at or bar_time + timedelta(seconds=30),
    )


def approved_15m_context(*, bar_time=datetime(2026, 8, 21, 13, 45, tzinfo=UTC)):
    payload = sensor_payload(
        event_type="CONTEXT_15M_BAR",
        timeframe="15",
        phase="OPENING_2M",
        bar_time=bar_time,
        close=130.0,
        high=130.2,
        low=129.0,
        open=129.4,
        vwap=129.5,
        ema9=129.9,
        ema20=129.6,
        relative_strength_smh_pct=0.20,
    )
    return derive_agentic_15m_context(record(payload))


def server_context(**overrides):
    values = {
        "daily_context_approved": True,
        "sector_context_approved": True,
        "scheduled_macro_blackout": False,
        "earnings_event_risk": False,
    }
    values.update(overrides)
    return AgenticIntradayServerContext(**values)


def test_sensor_ingress_authenticates_and_normalizes_two_minute_record():
    payload = sensor_payload()
    result = record(payload)

    assert result.symbol == "MU"
    assert result.account_id == "PAPER_AGENTIC_INTRADAY_V1"
    assert result.instrument == "STOCK"
    assert result.timeframe == "2M"
    assert result.event_type == "EXECUTION_2M_BAR"
    assert result.sensor_only is True
    assert result.paper_only is True
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False
    assert not hasattr(result, "webhook_secret")


def test_sensor_ingress_rejects_bad_secret_and_live_flags():
    payload = sensor_payload(webhook_secret="wrong")
    with pytest.raises(AgenticIntradayIngressAuthError, match="INTRADAY_WEBHOOK_AUTH_FAILED"):
        build_agentic_sensor_record(
            event(payload),
            expected_secret=SECRET,
            received_at=datetime(2026, 8, 21, 13, 47, tzinfo=UTC),
        )

    payload = sensor_payload(live_trading_enabled=True)
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_SENSOR_LIVE_TRADING_FORBIDDEN"):
        record(payload)


def test_sensor_ingress_rejects_wrong_symbol_or_phase_contract():
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_SENSOR_SYMBOL_INVALID"):
        record(sensor_payload(symbol="NVDA"))

    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_SENSOR_PHASE_MISMATCH"):
        record(sensor_payload(phase="STANDARD_5M"))


def test_sensor_ingress_rejects_stale_or_future_bar_time():
    payload = sensor_payload()
    bar_time = datetime.fromisoformat(payload["bar_time"].replace("Z", "+00:00"))
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_SENSOR_EVENT_STALE"):
        record(payload, received_at=bar_time + timedelta(minutes=16))
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_SENSOR_BAR_TIME_IN_FUTURE"):
        record(payload, received_at=bar_time - timedelta(minutes=2))


def test_15m_context_is_derived_from_raw_mu_price_trend_evidence():
    context = approved_15m_context()
    assert context.approved is True
    assert context.reasons == ()

    payload = sensor_payload(
        event_type="CONTEXT_15M_BAR",
        timeframe="15",
        phase="OPENING_2M",
        bar_time=datetime(2026, 8, 21, 13, 45, tzinfo=UTC),
        close=129.0,
        high=130.0,
        low=128.5,
        open=129.5,
        vwap=129.5,
        ema9=129.0,
        ema20=129.3,
        relative_strength_smh_pct=-0.1,
    )
    rejected = derive_agentic_15m_context(record(payload))
    assert rejected.approved is False
    assert "CONTEXT_15M_PRICE_NOT_ABOVE_VWAP" in rejected.reasons
    assert "CONTEXT_15M_EMA_NOT_ALIGNED" in rejected.reasons
    assert "CONTEXT_15M_RELATIVE_STRENGTH_NOT_POSITIVE" in rejected.reasons


def test_two_minute_sensor_enrichment_feeds_existing_signal_evaluator():
    raw = record(sensor_payload())
    observation = build_agentic_momentum_observation(
        raw,
        context_15m=approved_15m_context(),
        server_context=server_context(),
    )
    signal = evaluate_mu_momentum_signal(observation)

    assert observation.timeframe == "2M"
    assert observation.opening_range_established is True
    assert observation.opening_range_high == 130.0
    assert observation.average_daily_share_volume == 25_000_000
    assert signal.triggered is True
    assert signal.trigger_type == "OPENING_2M_ORB"
    assert signal.stock_stop_price == 129.5


def test_five_minute_sensor_enrichment_feeds_existing_signal_evaluator():
    bar_time = datetime(2026, 8, 21, 14, 15, tzinfo=UTC)
    payload = sensor_payload(
        event_type="EXECUTION_5M_BAR",
        timeframe="5",
        phase="STANDARD_5M",
        bar_time=bar_time,
        open=130.6,
        high=131.2,
        low=130.1,
        close=131.0,
        vwap=130.2,
        relative_volume=1.4,
        relative_strength_smh_pct=0.18,
        ema9=130.8,
        ema20=130.4,
        high_3_prior=130.7,
    )
    raw = record(payload)
    observation = build_agentic_momentum_observation(
        raw,
        context_15m=approved_15m_context(
            bar_time=datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
        ),
        server_context=server_context(),
    )
    signal = evaluate_mu_momentum_signal(observation)

    assert observation.timeframe == "5M"
    assert observation.continuation_high == 130.7
    assert observation.ema9 == 130.8
    assert observation.ema20 == 130.4
    assert signal.triggered is True
    assert signal.trigger_type == "STANDARD_5M_CONTINUATION"


def test_stale_or_future_15m_context_fails_closed_before_signal_evaluation():
    raw = record(sensor_payload())
    stale = approved_15m_context(bar_time=datetime(2026, 8, 21, 12, 45, tzinfo=UTC))
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_15M_CONTEXT_STALE"):
        build_agentic_momentum_observation(
            raw,
            context_15m=stale,
            server_context=server_context(),
        )

    future = approved_15m_context(bar_time=datetime(2026, 8, 21, 13, 47, tzinfo=UTC))
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_15M_CONTEXT_FROM_FUTURE"):
        build_agentic_momentum_observation(
            raw,
            context_15m=future,
            server_context=server_context(),
        )


def test_server_owned_macro_and_earnings_context_are_not_inferred_from_pine():
    raw = record(sensor_payload())
    observation = build_agentic_momentum_observation(
        raw,
        context_15m=approved_15m_context(),
        server_context=server_context(
            daily_context_approved=False,
            sector_context_approved=False,
            scheduled_macro_blackout=True,
            earnings_event_risk=True,
        ),
    )
    signal = evaluate_mu_momentum_signal(observation)

    assert signal.triggered is False
    assert "DAILY_CONTEXT_NOT_APPROVED" in signal.reasons
    assert "SECTOR_CONTEXT_NOT_APPROVED" in signal.reasons
    assert "SCHEDULED_MACRO_BLACKOUT" in signal.reasons
    assert "EARNINGS_EVENT_RISK_BLOCKED" in signal.reasons


def test_management_and_flatten_sensor_bars_cannot_become_entry_observations():
    management_time = datetime(2026, 8, 21, 19, 35, tzinfo=UTC)
    payload = sensor_payload(
        event_type="MANAGEMENT_5M_BAR",
        timeframe="5",
        phase="MANAGEMENT_ONLY",
        bar_time=management_time,
    )
    raw = record(payload)
    with pytest.raises(AgenticIntradayIngressError, match="INTRADAY_EXECUTION_SENSOR_RECORD_REQUIRED"):
        build_agentic_momentum_observation(
            raw,
            context_15m=approved_15m_context(
                bar_time=datetime(2026, 8, 21, 19, 30, tzinfo=UTC)
            ),
            server_context=server_context(),
        )
