import json
from datetime import UTC, datetime

from daily_alpha.armed_replay import list_armed_ingress, replay_armed_events
from daily_alpha.pine_paper_reconciliation import prepare_armed_replay


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


class FakeClient:
    def __init__(self, ingress):
        self.ingress = ingress
        self.scans = []

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


class FakeStore:
    table_name = "paper-test"
    account_id = "paper-shadow"

    def __init__(self, ingress):
        self.client = FakeClient(ingress)
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

    armed = list_armed_ingress(store, limit=5)
    assert len(armed) == 1
    assert armed[0]["_persisted_signal_id"] == "AMD-ENTRY-1"
    scan = store.client.scans[0]
    assert scan["ExpressionAttributeValues"][":armed"]["S"] == (
        "ARMED_FOR_NEXT_TRADABLE_WINDOW"
    )

    result = replay_armed_events(store, executor, now=NOW, limit=5)

    assert result["armed_found"] == 1
    assert result["outcome_counts"] == {"CANCELLED_REPLAY": 1}
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert store.marked[0][0] == "AMD-ENTRY-1"
    assert store.marked[0][1]["paper_execution_triggered"] is False
