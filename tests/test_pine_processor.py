import json
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.pine_processor import (
    DynamoPineEventStore,
    PineProcessorError,
    process_ingress_record,
    process_sqs_batch,
)

NOW = datetime(2026, 8, 16, 23, 20, tzinfo=UTC)
RECEIVED = NOW - timedelta(minutes=2)


def ingress(action="ENTRY_LONG", **overrides):
    payload = {
        "schema_version": "2026-08-16-v3",
        "source": "TRADINGVIEW_PINE",
        "signal_id": f"mu-{action.lower()}-1",
        "symbol": "MU",
        "action": action,
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.3",
        "timeframe": "D",
        "price": 575.5,
        "bar_time": (RECEIVED - timedelta(minutes=1)).isoformat(),
        "received_at": RECEIVED.isoformat(),
        "position_fraction": None,
        "runner_stage": None,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def test_entry_is_held_until_portfolio_risk_and_orats_context_exists():
    result = process_ingress_record(ingress(), now=NOW)

    assert result.disposition == "HELD_FOR_CONTEXT"
    assert result.reason == "ENTRY_REQUIRES_PORTFOLIO_RISK_ORATS_CONTEXT"
    assert result.paper_ledger_updated is False
    assert result.paper_execution_triggered is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_canonical_add_is_held_with_runner_metadata_preserved():
    result = process_ingress_record(
        ingress(
            "ADD",
            position_fraction=0.25,
            runner_stage="ADD_1_ATR",
        ),
        now=NOW,
    )

    assert result.action == "ADD"
    assert result.position_fraction == 0.25
    assert result.runner_stage == "ADD_1_ATR"
    assert result.reason == "ADD_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_FILL_CONTEXT"


def test_canonical_partial_is_held_with_harvest_metadata_preserved():
    result = process_ingress_record(
        ingress(
            "PARTIAL",
            position_fraction=0.25,
            runner_stage="HARVEST_3_ATR",
        ),
        now=NOW,
    )

    assert result.action == "PARTIAL"
    assert result.runner_stage == "HARVEST_3_ATR"
    assert result.reason == "PARTIAL_REQUIRES_OPEN_POSITION_AND_INSTRUMENT_FILL_CONTEXT"


def test_processor_rejects_noncanonical_strategy_version():
    with pytest.raises(PineProcessorError, match="STRATEGY_VERSION_NOT_CANONICAL"):
        process_ingress_record(ingress(strategy_version="1.9"), now=NOW)


def test_processor_rejects_noncanonical_runner_stage():
    with pytest.raises(PineProcessorError, match="ADD_STAGE_INVALID"):
        process_ingress_record(
            ingress(
                "ADD",
                position_fraction=0.25,
                runner_stage="ADD_7_ATR",
            ),
            now=NOW,
        )


def test_processor_rejects_wrong_runner_fraction():
    with pytest.raises(PineProcessorError, match="RUNNER_FRACTION_INVALID"):
        process_ingress_record(
            ingress(
                "PARTIAL",
                position_fraction=0.50,
                runner_stage="HARVEST_3_ATR",
            ),
            now=NOW,
        )


def test_processor_rejects_any_unsafe_execution_flag():
    with pytest.raises(PineProcessorError, match="UNSAFE_FLAG_LIVE_TRADING_ENABLED"):
        process_ingress_record(ingress(live_trading_enabled=True), now=NOW)


def test_processor_rejects_secret_leakage():
    with pytest.raises(PineProcessorError, match="SECRET_MUST_NOT_BE_PRESENT"):
        process_ingress_record(ingress(webhook_secret="must-not-cross-sqs"), now=NOW)


def test_processor_rejects_stale_queue_event():
    stale_received = NOW - timedelta(minutes=31)
    with pytest.raises(PineProcessorError, match="QUEUE_EVENT_STALE"):
        process_ingress_record(
            ingress(
                received_at=stale_received.isoformat(),
                bar_time=(stale_received - timedelta(minutes=1)).isoformat(),
            ),
            now=NOW,
        )


class FakeStore:
    def __init__(self):
        self.items = []

    def persist(self, body, result):
        self.items.append((body, result))
        return True


def test_sqs_batch_uses_partial_failure_semantics():
    store = FakeStore()
    event = {
        "Records": [
            {"messageId": "good", "body": json.dumps(ingress())},
            {
                "messageId": "bad",
                "body": json.dumps(ingress(live_trading_enabled=True)),
            },
        ]
    }

    response = process_sqs_batch(event, store, now=NOW)

    assert response == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    assert len(store.items) == 1
    assert store.items[0][1].signal_id == "mu-entry_long-1"


class ConditionalFailure(Exception):
    def __init__(self):
        super().__init__("duplicate")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeDynamoClient:
    def __init__(self):
        self.calls = []
        self.fail_duplicate = False

    def put_item(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_duplicate:
            raise ConditionalFailure()
        return {}


def test_dynamo_event_store_is_idempotent_by_signal_id():
    client = FakeDynamoClient()
    store = DynamoPineEventStore(client=client)
    body = ingress()
    result = process_ingress_record(body, now=NOW)

    assert store.persist(body, result) is True
    client.fail_duplicate = True
    assert store.persist(body, result) is False

    item = client.calls[0]["Item"]
    assert "webhook_secret" not in item["ingress_json"]["S"]
    assert item["disposition"]["S"] == "HELD_FOR_CONTEXT"
