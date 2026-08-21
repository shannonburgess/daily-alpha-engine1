import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from daily_alpha.armed_replay import replay_armed_events
from daily_alpha.ledger import PaperLedger
from daily_alpha.pine_processor import DynamoPineEventStore, process_sqs_batch
from daily_alpha.reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor

AFTER_CLOSE = datetime(2026, 8, 19, 21, 5, tzinfo=UTC)
REPLAY_TIME = datetime(2026, 8, 20, 14, 5, tzinfo=UTC)


class InMemoryDynamo:
    """Minimal Dynamo contract used to exercise the real Pine audit-store boundary."""

    def __init__(self):
        self.items = {}

    def put_item(self, **kwargs):
        item = deepcopy(kwargs["Item"])
        key = (item["pk"]["S"], item["sk"]["S"])
        if key in self.items:
            error = RuntimeError("duplicate")
            error.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
            raise error
        self.items[key] = item
        return {}

    def update_item(self, **kwargs):
        key = (kwargs["Key"]["pk"]["S"], kwargs["Key"]["sk"]["S"])
        if key not in self.items:
            raise RuntimeError("missing audit event")
        values = kwargs["ExpressionAttributeValues"]
        item = self.items[key]
        if ":lease_until" in values:
            armed = values[":armed"]["S"]
            now_epoch = int(values[":now_epoch"]["N"])
            current_lease = int(item.get("replay_lease_until_epoch", {}).get("N", "0"))
            if item.get("disposition", {}).get("S") != armed or current_lease >= now_epoch:
                error = RuntimeError("lease conflict")
                error.response = {
                    "Error": {"Code": "ConditionalCheckFailedException"}
                }
                raise error
            item["replay_lease_until_epoch"] = deepcopy(values[":lease_until"])
            item["replay_lease_token"] = deepcopy(values[":lease_token"])
            return {}
        item["disposition"] = deepcopy(values[":disposition"])
        item["reason"] = deepcopy(values[":reason"])
        item["execution_json"] = deepcopy(values[":execution"])
        return {}

    def scan(self, **kwargs):
        armed = kwargs["ExpressionAttributeValues"][":armed"]["S"]
        now_raw = kwargs["ExpressionAttributeValues"].get(":now_epoch")
        now_epoch = int(now_raw["N"]) if now_raw else None
        limit = kwargs.get("Limit", 25)
        matches = []
        for item in self.items.values():
            if item.get("disposition", {}).get("S") != armed:
                continue
            if now_epoch is not None:
                lease_until = int(
                    item.get("replay_lease_until_epoch", {}).get("N", "0")
                )
                if lease_until >= now_epoch:
                    continue
            matches.append(deepcopy(item))
        return {"Items": matches[:limit]}


def _executor(tmp_path):
    return ReceiptReconciledAwsPinePaperExecutor(
        ledger=PaperLedger(tmp_path / "paper-ledger"),
        secrets_client=object(),
        paper_nav=1_000_000,
        orats_factory=lambda token: None,
    )


def _ingress():
    received = AFTER_CLOSE - timedelta(minutes=1)
    return {
        "schema_version": "2026-08-16-v4",
        "source": "TRADINGVIEW_PINE",
        "signal_id": "AMD-E2E-1",
        "symbol": "AMD",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 100.0,
        "bar_time": (received - timedelta(minutes=1)).isoformat(),
        "received_at": received.isoformat(),
        "position_fraction": None,
        "runner_stage": None,
        "sector": "Information Technology",
        "stock_stop_price": 95.0,
        "replay_max_price": 105.0,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }


def test_local_contract_receive_arm_replay_and_persist_exact_stock_receipt(tmp_path):
    client = InMemoryDynamo()
    store = DynamoPineEventStore(
        table_name="paper-test",
        account_id="paper-shadow-v24",
        client=client,
    )
    executor = _executor(tmp_path)
    ingress = _ingress()
    event = {
        "Records": [
            {
                "messageId": "amd-e2e",
                "body": json.dumps(ingress),
            }
        ]
    }

    first = process_sqs_batch(event, store, executor=executor, now=AFTER_CLOSE)

    assert first == {"batchItemFailures": []}
    key = ("ACCOUNT#paper-shadow-v24#PINE_EVENT#AMD-E2E-1", "RECEIVED")
    persisted = client.items[key]
    assert persisted["disposition"]["S"] == "ARMED_FOR_NEXT_TRADABLE_WINDOW"
    armed_execution = json.loads(persisted["execution_json"]["S"])
    assert armed_execution["paper_execution_triggered"] is False
    assert armed_execution["context"]["options_execution_enabled"] is False
    assert armed_execution["context"]["orats_required_for_new_entry"] is False
    assert armed_execution["trading_authorized"] is False
    assert armed_execution["live_trading_enabled"] is False

    replay = replay_armed_events(store, executor, now=REPLAY_TIME, limit=5)

    assert replay["armed_found"] == 1
    assert replay["armed_claimed"] == 1
    assert replay["outcome_counts"] == {"EXECUTED_PAPER": 1}
    persisted_after = client.items[key]
    assert persisted_after["disposition"]["S"] == "EXECUTED_PAPER"
    execution = json.loads(persisted_after["execution_json"]["S"])
    receipt = execution["execution_receipt"]
    trade = executor.ledger.find_open("AMD")[0]

    assert execution["reason"] == "PAPER_STOCK_POSITION_OPENED"
    assert execution["context"]["execution_policy"] == (
        "STOCK_PRIMARY_MODEL_VALIDATION_V1"
    )
    assert execution["context"]["options_execution_enabled"] is False
    assert execution["context"]["orats_required_for_new_entry"] is False
    assert execution["context"]["model_validation_fill_price"] == 100.0
    assert trade.instrument.value == "STOCK"
    assert trade.entry_price == 100.0
    assert receipt["signal_id"] == "AMD-E2E-1-REPLAY-20260820T140500"
    assert receipt["instrument"] == "STOCK"
    assert receipt["fill_price"] == 100.0
    assert receipt["fill_quantity"] == trade.quantity
    assert receipt["fill_notional"] == trade.quantity * 100.0
    assert receipt["remaining_quantity"] == trade.quantity
    assert receipt["initial_risk_basis"] == trade.initial_risk_basis
    assert receipt["r_basis_status"] == "NO_REALIZED_PNL_YET"
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False
    assert execution["trading_authorized"] is False
    assert execution["live_trading_enabled"] is False
