import json
from datetime import UTC, datetime

from daily_alpha.pine_processor import process_sqs_batch

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.persisted = []
        self.executed = []

    def persist(self, body, result):
        self.persisted.append((body, result))
        return True

    def mark_execution(self, signal_id, execution):
        self.executed.append((signal_id, execution))


class Executor:
    def execute(self, body, *, now=None):
        assert body["signal_id"] == "entry-1"
        assert now == NOW
        return {
            "disposition": "EXECUTED_PAPER",
            "reason": "PAPER_POSITION_OPENED",
            "paper_execution_triggered": True,
            "paper_ledger_updated": True,
            "live_trading_enabled": False,
        }


def test_sqs_processor_hands_validated_event_to_executor():
    body = {
        "schema_version": "2026-08-16-v3",
        "source": "TRADINGVIEW_PINE",
        "signal_id": "entry-1",
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.3",
        "timeframe": "1D",
        "price": 110.0,
        "bar_time": NOW.isoformat(),
        "received_at": NOW.isoformat(),
        "position_fraction": None,
        "runner_stage": None,
        "stock_stop_price": 100.0,
        "average_daily_dollar_volume": 60_000_000.0,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    store = Store()

    response = process_sqs_batch(
        {"Records": [{"messageId": "1", "body": json.dumps(body)}]},
        store,
        executor=Executor(),
        now=NOW,
    )

    assert response == {"batchItemFailures": []}
    assert len(store.persisted) == 1
    assert store.executed[0][0] == "entry-1"
    assert store.executed[0][1]["disposition"] == "EXECUTED_PAPER"
