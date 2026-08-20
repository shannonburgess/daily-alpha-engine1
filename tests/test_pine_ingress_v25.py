import json
from datetime import UTC, datetime

import pytest

from daily_alpha.pine_ingress import PineIngressError, build_pine_ingress_record


def _event(**overrides):
    payload = {
        "webhook_secret": "test-secret",
        "signal_id": "AMD-TEST-V25",
        "symbol": "AMD",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.5",
        "model_id": "PAPER_SHADOW_V25",
        "forward_test_start": "2026-08-18",
        "replay_max_price": 255.0,
        "timeframe": "1D",
        "price": 250.0,
        "bar_time": "2026-08-18T20:00:00+00:00",
        "entry_type": "ARMED_BREAKOUT_CONFIRM",
        "stock_stop_price": 235.0,
        "average_daily_dollar_volume": 1_000_000_000,
    }
    payload.update(overrides)
    return {"body": json.dumps(payload)}


def test_v25_shadow_entry_is_preserved_in_ingress_record():
    record = build_pine_ingress_record(
        _event(),
        expected_secret="test-secret",
        received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
    )

    assert record.schema_version == "2026-08-18-v5"
    assert record.strategy_version == "2.5"
    assert record.model_id == "PAPER_SHADOW_V25"
    assert record.forward_test_start == "2026-08-18"
    assert record.replay_max_price == 255.0
    assert record.entry_type == "ARMED_BREAKOUT_CONFIRM"
    assert record.trading_authorized is False
    assert record.paper_execution_triggered is False
    assert record.live_trading_enabled is False


def test_v25_requires_explicit_shadow_model_id():
    with pytest.raises(PineIngressError, match="PAPER_SHADOW_V25"):
        build_pine_ingress_record(
            _event(model_id=""),
            expected_secret="test-secret",
            received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        )


def test_v25_rejects_v24_shadow_model_id():
    with pytest.raises(PineIngressError, match="does not match strategy version 2.5"):
        build_pine_ingress_record(
            _event(model_id="PAPER_SHADOW_V24"),
            expected_secret="test-secret",
            received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        )


def test_shadow_model_requires_forward_test_start():
    with pytest.raises(PineIngressError, match="forward_test_start is required"):
        build_pine_ingress_record(
            _event(forward_test_start=""),
            expected_secret="test-secret",
            received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        )


def test_shadow_signal_cannot_predate_forward_test_start():
    with pytest.raises(PineIngressError, match="predates forward_test_start"):
        build_pine_ingress_record(
            _event(forward_test_start="2026-08-19"),
            expected_secret="test-secret",
            received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        )


def test_shadow_entry_requires_explicit_replay_max_price():
    with pytest.raises(PineIngressError, match="replay_max_price is required"):
        build_pine_ingress_record(
            _event(replay_max_price=""),
            expected_secret="test-secret",
            received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        )


def test_shadow_entry_rejects_replay_ceiling_below_signal_price():
    with pytest.raises(PineIngressError, match="cannot be below signal price"):
        build_pine_ingress_record(
            _event(replay_max_price=249.99),
            expected_secret="test-secret",
            received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
        )


def test_untagged_legacy_entry_can_omit_replay_ceiling():
    event = _event(
        strategy_version="2.4",
        model_id="",
        forward_test_start="",
        replay_max_price="",
        entry_type="NORMAL_BREAKOUT",
    )
    record = build_pine_ingress_record(
        event,
        expected_secret="test-secret",
        received_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
    )

    assert record.schema_version == "2026-08-16-v4"
    assert record.model_id is None
    assert record.forward_test_start is None
    assert record.replay_max_price is None
