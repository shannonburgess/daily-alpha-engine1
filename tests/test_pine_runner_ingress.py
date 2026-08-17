import json
from datetime import UTC, datetime

from daily_alpha.pine_ingress import build_pine_ingress_record

NOW = datetime(2026, 8, 16, 11, 30, tzinfo=UTC)
SECRET = "runner-secret"


def _payload(action: str, stage: str):
    return {
        "webhook_secret": SECRET,
        "signal_id": f"mu-{action.lower()}-1",
        "symbol": "MU",
        "action": action,
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "1.9",
        "timeframe": "1D",
        "price": 575.5,
        "bar_time": "2026-08-16T11:29:00Z",
        "position_fraction": 0.25,
        "runner_stage": stage,
    }


def test_add_ingress_record_is_sanitized_and_never_authorizes_trading():
    record = build_pine_ingress_record(
        {"body": json.dumps(_payload("ADD", "ADD_1_ATR"))},
        expected_secret=SECRET,
        received_at=NOW,
    ).to_dict()

    assert record["schema_version"] == "2026-08-16-v4"
    assert record["action"] == "ADD"
    assert record["position_fraction"] == 0.25
    assert record["runner_stage"] == "ADD_1_ATR"
    assert record["entry_type"] is None
    assert record["trading_authorized"] is False
    assert record["paper_execution_triggered"] is False
    assert record["live_trading_enabled"] is False
    assert "webhook_secret" not in record
    assert SECRET not in json.dumps(record)


def test_partial_ingress_record_preserves_harvest_metadata_only():
    record = build_pine_ingress_record(
        {"body": json.dumps(_payload("PARTIAL", "HARVEST_3_ATR"))},
        expected_secret=SECRET,
        received_at=NOW,
    ).to_dict()

    assert record["schema_version"] == "2026-08-16-v4"
    assert record["action"] == "PARTIAL"
    assert record["position_fraction"] == 0.25
    assert record["runner_stage"] == "HARVEST_3_ATR"
    assert record["entry_type"] is None
    assert record["trading_authorized"] is False
    assert record["paper_execution_triggered"] is False
