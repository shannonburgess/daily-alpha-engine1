import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from daily_alpha.armed_replay import replay_armed_events
from daily_alpha.pine_paper_reconciliation import ReconciledAwsPinePaperExecutor
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


class EmptyLedger:
    account_id = "paper-shadow-v24"

    def find_open(self, symbol, instrument=None):
        return []


def _executor():
    return ReceiptReconciledAwsPinePaperExecutor(
        ledger=EmptyLedger(),
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


def test_local_contract_receive_arm_replay_and_persist_exact_receipt(monkeypatch):
    client = InMemoryDynamo()
    store = DynamoPineEventStore(
        table_name="paper-test",
        account_id="paper-shadow-v24",
        client=client,
    )
    executor = _executor()
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
    assert armed_execution["trading_authorized"] is False
    assert armed_execution["live_trading_enabled"] is False

    replay_signal_id = "AMD-E2E-1-REPLAY-20260820T140500"

    def fake_replay(self, ingress, *, now=None):
        return {
            "disposition": "EXECUTED_PAPER",
            "reason": "PAPER_POSITION_OPENED",
            "action": "ENTRY_LONG",
            "symbol": "AMD",
            "paper_execution_triggered": True,
            "paper_ledger_updated": True,
            "trading_authorized": False,
            "live_trading_enabled": False,
            "paper": {
                "trade": {
                    "trade_id": "amd-trade-1",
                    "signal_id": replay_signal_id,
                    "symbol": "AMD",
                    "instrument": "STOCK",
                    "quantity": 5,
                    "entry_price": 102.0,
                    "entry_time": REPLAY_TIME.isoformat(),
                    "state": "OPEN",
                    "exit_price": None,
                    "exit_time": None,
                    "realized_pnl": 0.0,
                    "fallback_reason": "STOCK_FALLBACK",
                    "option_expiration": None,
                    "option_strike": None,
                    "option_type": None,
                    "target_quantity": 5,
                    "runner_stage": "STARTER",
                    "add1_signal_id": None,
                    "add2_signal_id": None,
                    "harvest_signal_id": None,
                    "sector": "Information Technology",
                    "initial_risk_basis": 500.0,
                },
                "paper_ledger_updated": True,
            },
            "context": {
                "replayed_from_armed_signal": True,
                "origin_signal_id": ingress["signal_id"],
                "origin_signal_price": ingress["price"],
                "replay_market_price": 102.0,
            },
        }

    monkeypatch.setattr(ReconciledAwsPinePaperExecutor, "replay_armed", fake_replay)
    replay = replay_armed_events(store, executor, now=REPLAY_TIME, limit=5)

    assert replay["armed_found"] == 1
    assert replay["armed_claimed"] == 1
    assert replay["outcome_counts"] == {"EXECUTED_PAPER": 1}
    persisted = client.items[key]
    assert persisted["disposition"]["S"] == "EXECUTED_PAPER"
    execution = json.loads(persisted["execution_json"]["S"])
    receipt = execution["execution_receipt"]
    assert receipt["paper_account_id"] == "paper-shadow-v24"
    assert receipt["signal_id"] == replay_signal_id
    assert receipt["origin_signal_id"] == "AMD-E2E-1"
    assert receipt["instrument"] == "STOCK"
    assert receipt["fill_price"] == 102.0
    assert receipt["fill_quantity"] == 5
    assert receipt["fill_notional"] == 510.0
    assert receipt["remaining_quantity"] == 5
    assert receipt["remaining_cost_basis"] == 510.0
    assert receipt["average_entry_price"] == 102.0
    assert receipt["initial_risk_basis"] == 500.0
    assert receipt["realized_pnl"] == 0.0
    assert receipt["r_basis_status"] == "NO_REALIZED_PNL_YET"
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False
    assert execution["evaluated_at"] == REPLAY_TIME.isoformat()
