import json
from datetime import UTC, datetime

from daily_alpha.armed_replay import (
    list_armed_ingress,
    list_recent_pine_event_state,
    replay_armed_events,
)
from daily_alpha.pine_paper_reconciliation import (
    ReconciledAwsPinePaperExecutor,
    prepare_armed_replay,
)
from daily_alpha.reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor

NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


def _entry(**overrides):
    payload = {
        "signal_id": "AMD-ENTRY-1",
        "symbol": "AMD",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 250.0,
        "bar_time": "2026-08-18T20:00:00+00:00",
        "received_at": "2026-08-18T20:05:00+00:00",
        "sector": "Information Technology",
        "stock_stop_price": 235.0,
        "average_daily_dollar_volume": 1_000_000_000,
    }
    payload.update(overrides)
    return payload


def test_legacy_armed_entry_without_no_chase_ceiling_stays_armed():
    decision = prepare_armed_replay(_entry(), market_price=252.0, now=NOW)

    assert decision.status == "WAIT_REVALIDATION"
    assert decision.reason == "REPLAY_NO_CHASE_CEILING_REQUIRED"
    assert decision.ingress is None


def test_armed_entry_above_explicit_no_chase_ceiling_is_cancelled():
    decision = prepare_armed_replay(
        _entry(replay_max_price=255.0),
        market_price=256.0,
        now=NOW,
    )

    assert decision.status == "CANCELLED_REPLAY"
    assert decision.reason == "REPLAY_ENTRY_CHASE_LIMIT_EXCEEDED"
    assert decision.ingress is None


def test_armed_entry_revalidation_creates_fresh_execution_time_signal():
    decision = prepare_armed_replay(
        _entry(replay_max_price=255.0),
        market_price=252.0,
        now=NOW,
    )

    assert decision.should_execute is True
    assert decision.ingress is not None
    assert decision.ingress["price"] == 252.0
    assert decision.ingress["bar_time"] == NOW.isoformat()
    assert decision.ingress["received_at"] == NOW.isoformat()
    assert decision.ingress["origin_signal_id"] == "AMD-ENTRY-1"
    assert decision.ingress["origin_signal_price"] == 250.0
    assert decision.ingress["execution_timing"] == "ARMED_REPLAY_REGULAR_SESSION"
    assert decision.ingress["signal_id"].startswith("AMD-ENTRY-1-REPLAY-")


class _ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeClient:
    def __init__(self, ingress, *, claim_conflict=False):
        self.ingress = ingress
        self.claim_conflict = claim_conflict
        self.scans = []
        self.updates = []

    def scan(self, **kwargs):
        self.scans.append(kwargs)
        return {
            "Items": [
                {
                    "signal_id": {"S": self.ingress["signal_id"]},
                    "ingress_json": {
                        "S": json.dumps(self.ingress, sort_keys=True)
                    },
                }
            ]
        }

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        if self.claim_conflict:
            raise _ConditionalFailure()
        return {}


class FakeStore:
    table_name = "paper-test"
    account_id = "paper-shadow"

    def __init__(self, ingress, *, claim_conflict=False):
        self.client = FakeClient(ingress, claim_conflict=claim_conflict)
        self.marked = []

    def mark_execution(self, signal_id, execution):
        self.marked.append((signal_id, execution))


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def replay_armed(self, ingress, *, now):
        self.calls.append((dict(ingress), now))
        return {
            "disposition": "CANCELLED_REPLAY",
            "reason": "REPLAY_ENTRY_CHASE_LIMIT_EXCEEDED",
            "action": ingress["action"],
            "symbol": ingress["symbol"],
            "paper_execution_triggered": False,
            "paper_ledger_updated": False,
            "trading_authorized": False,
            "live_trading_enabled": False,
        }


def test_durable_worker_scans_only_armed_event_contract_and_persists_outcome():
    ingress = _entry(replay_max_price=255.0)
    store = FakeStore(ingress)
    executor = FakeExecutor()

    armed = list_armed_ingress(store, limit=5, now=NOW)
    assert len(armed) == 1
    assert armed[0]["_persisted_signal_id"] == "AMD-ENTRY-1"
    scan = store.client.scans[0]
    assert scan["ExpressionAttributeValues"][":armed"]["S"] == (
        "ARMED_FOR_NEXT_TRADABLE_WINDOW"
    )
    assert scan["ExpressionAttributeValues"][":now_epoch"]["N"] == str(
        int(NOW.timestamp())
    )

    result = replay_armed_events(store, executor, now=NOW, limit=5)

    assert result["armed_found"] == 1
    assert result["armed_claimed"] == 1
    assert result["lease_conflicts"] == 0
    assert result["outcome_counts"] == {"CANCELLED_REPLAY": 1}
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    claim = store.client.updates[0]
    assert "replay_lease_until_epoch" in claim["UpdateExpression"]
    assert "disposition = :armed" in claim["ConditionExpression"]
    assert store.marked[0][0] == "AMD-ENTRY-1"
    assert store.marked[0][1]["paper_execution_triggered"] is False


def test_concurrent_replay_claim_conflict_skips_execution_and_persistence():
    ingress = _entry(replay_max_price=255.0)
    store = FakeStore(ingress, claim_conflict=True)
    executor = FakeExecutor()

    result = replay_armed_events(store, executor, now=NOW, limit=5)

    assert result["armed_found"] == 1
    assert result["armed_claimed"] == 0
    assert result["lease_conflicts"] == 1
    assert result["outcome_counts"] == {}
    assert result["outcomes"] == []
    assert executor.calls == []
    assert store.marked == []


class _HistoryClient:
    def scan(self, **kwargs):
        older = _entry(
            signal_id="OLD",
            received_at="2026-08-18T20:05:00+00:00",
        )
        newer = _entry(
            signal_id="NEW",
            received_at="2026-08-19T13:55:00+00:00",
        )
        return {
            "ScannedCount": 2,
            "Items": [
                {
                    "signal_id": {"S": "OLD"},
                    "symbol": {"S": "AMD"},
                    "action": {"S": "ENTRY_LONG"},
                    "disposition": {"S": "NO_TRADE"},
                    "reason": {"S": "OLD"},
                    "ingress_json": {"S": json.dumps(older)},
                },
                {
                    "signal_id": {"S": "NEW"},
                    "symbol": {"S": "AMD"},
                    "action": {"S": "ENTRY_LONG"},
                    "disposition": {"S": "NO_TRADE"},
                    "reason": {"S": "NEW"},
                    "ingress_json": {"S": json.dumps(newer)},
                },
            ],
        }


class _HistoryStore:
    table_name = "paper-test"
    account_id = "paper-shadow"
    client = _HistoryClient()


def test_monitor_response_limit_omits_old_history_without_claiming_scan_truncation():
    state = list_recent_pine_event_state(_HistoryStore(), limit=1)

    assert state["scan_truncated"] is False
    assert state["event_count_scanned"] == 2
    assert state["event_count_visible"] == 1
    assert state["event_history_omitted"] == 1
    assert state["events"][0]["signal_id"] == "NEW"


class _Trade:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class _Ledger:
    account_id = "paper-shadow-v24"

    def __init__(self, trade):
        self.trade = trade

    def find_open(self, symbol, instrument=None):
        return [_Trade(self.trade)]


def test_durable_worker_persists_replay_receipt_with_risk_basis(monkeypatch):
    ingress = _entry(
        signal_id="CAT-ADD-ORIGIN",
        symbol="CAT",
        action="ADD",
        price=99.0,
        runner_stage="ADD_1_ATR",
        position_fraction=0.2,
    )
    store = FakeStore(ingress)
    before = {
        "trade_id": "trade-1",
        "signal_id": "entry-1",
        "symbol": "CAT",
        "instrument": "STOCK",
        "quantity": 10,
        "entry_price": 100.0,
        "entry_time": NOW.isoformat(),
        "state": "OPEN",
        "realized_pnl": 0.0,
        "target_quantity": 12,
        "runner_stage": "STARTER",
        "sector": "Industrials",
        "initial_risk_basis": 500.0,
    }
    replay_signal_id = "CAT-ADD-ORIGIN-REPLAY-20260819T140000"
    after = {
        **before,
        "quantity": 12,
        "entry_price": 100.83333333,
        "runner_stage": "ADD_1_ATR",
        "add1_signal_id": replay_signal_id,
    }
    executor = ReceiptReconciledAwsPinePaperExecutor(
        ledger=_Ledger(before),
        secrets_client=object(),
        paper_nav=1_000_000,
        orats_factory=lambda token: None,
    )

    def fake_replay(self, ingress, *, now=None):
        return {
            "disposition": "EXECUTED_PAPER",
            "reason": "PAPER_ADD_APPLIED",
            "action": "ADD",
            "symbol": "CAT",
            "paper_execution_triggered": True,
            "paper_ledger_updated": True,
            "trading_authorized": False,
            "live_trading_enabled": False,
            "paper": {
                "updated_trades": [after],
                "runner_stage": "ADD_1_ATR",
                "paper_ledger_updated": True,
            },
            "context": {
                "replayed_from_armed_signal": True,
                "origin_signal_id": "CAT-ADD-ORIGIN",
                "replay_market_price": 105.0,
            },
        }

    monkeypatch.setattr(ReconciledAwsPinePaperExecutor, "replay_armed", fake_replay)
    result = replay_armed_events(store, executor, now=NOW, limit=5)

    assert result["outcome_counts"] == {"EXECUTED_PAPER": 1}
    assert result["armed_claimed"] == 1
    persisted_signal_id, persisted_execution = store.marked[0]
    assert persisted_signal_id == "CAT-ADD-ORIGIN"
    receipt = persisted_execution["execution_receipt"]
    assert receipt["signal_id"] == replay_signal_id
    assert receipt["fill_price"] == 105.0
    assert receipt["fill_quantity"] == 2
    assert receipt["fill_notional"] == 210.0
    assert receipt["initial_risk_basis"] == 500.0
    assert receipt["r_basis_status"] == "NO_REALIZED_PNL_YET"
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False
