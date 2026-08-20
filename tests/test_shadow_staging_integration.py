from datetime import UTC, datetime

from lambda_handlers import pine_processor as handler


class FakeStore:
    def __init__(self, account_id=None):
        self.account_id = account_id or "paper-staging"


class FakeLedger:
    def __init__(self, account_id=None):
        self.account_id = account_id or "paper-staging"


class FakeExecutor:
    def __init__(self, *, liquidity_store=None):
        self.liquidity_store = liquidity_store


class FakeTrade:
    def __init__(self, symbol):
        self.symbol = symbol

    def to_dict(self):
        return {"symbol": self.symbol}


def test_replay_all_paper_accounts_scans_default_and_both_shadows(monkeypatch):
    monkeypatch.setattr(handler, "DynamoPineEventStore", FakeStore)
    monkeypatch.setattr(handler, "ShadowRoutedPinePaperExecutor", FakeExecutor)
    monkeypatch.setattr(handler, "default_paper_account_id", lambda: "paper-staging")
    monkeypatch.setattr(handler, "_liquidity_store", lambda: object())

    seen = []

    def fake_replay(store, executor, *, now, limit):
        assert isinstance(executor, FakeExecutor)
        assert executor.liquidity_store is not None
        seen.append((store.account_id, limit))
        return {
            "ok": True,
            "armed_found": 1,
            "outcome_counts": {"EXECUTED_PAPER": 1},
            "outcomes": [
                {
                    "persisted_signal_id": f"SIG-{store.account_id}",
                    "symbol": "AMD",
                    "action": "ENTRY_LONG",
                    "disposition": "EXECUTED_PAPER",
                    "reason": "TEST",
                    "paper_execution_triggered": True,
                    "paper_ledger_updated": True,
                }
            ],
            "trading_authorized": False,
            "live_trading_enabled": False,
        }

    monkeypatch.setattr(handler, "replay_armed_events", fake_replay)
    now = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)

    result = handler._replay_all_paper_accounts(now=now, limit=10)

    assert [account for account, _ in seen] == [
        "paper-staging",
        handler.PAPER_SHADOW_V24,
        handler.PAPER_SHADOW_V25,
    ]
    assert result["accounts_scanned"] == [
        "paper-staging",
        handler.PAPER_SHADOW_V24,
        handler.PAPER_SHADOW_V25,
    ]
    assert result["armed_found"] == 3
    assert result["outcome_counts"] == {"EXECUTED_PAPER": 3}
    assert [item["paper_account_id"] for item in result["outcomes"]] == [
        "paper-staging",
        handler.PAPER_SHADOW_V24,
        handler.PAPER_SHADOW_V25,
    ]
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_replay_all_paper_accounts_honors_global_limit(monkeypatch):
    monkeypatch.setattr(handler, "DynamoPineEventStore", FakeStore)
    monkeypatch.setattr(handler, "ShadowRoutedPinePaperExecutor", FakeExecutor)
    monkeypatch.setattr(handler, "default_paper_account_id", lambda: "paper-staging")
    monkeypatch.setattr(handler, "_liquidity_store", lambda: object())

    seen = []

    def fake_replay(store, executor, *, now, limit):
        assert executor.liquidity_store is not None
        seen.append((store.account_id, limit))
        found = limit
        return {
            "ok": True,
            "armed_found": found,
            "outcome_counts": {"ARMED_FOR_NEXT_TRADABLE_WINDOW": found},
            "outcomes": [],
            "trading_authorized": False,
            "live_trading_enabled": False,
        }

    monkeypatch.setattr(handler, "replay_armed_events", fake_replay)
    now = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)

    result = handler._replay_all_paper_accounts(now=now, limit=2)

    assert seen == [("paper-staging", 2)]
    assert result["armed_found"] == 2
    assert result["accounts_scanned"] == ["paper-staging"]
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_shadow_monitor_state_is_read_only_and_keeps_books_isolated(monkeypatch):
    monkeypatch.setattr(handler, "DynamoPaperLedger", FakeLedger)
    monkeypatch.setattr(handler, "DynamoPineEventStore", FakeStore)

    def fake_open_trades(ledger):
        if ledger.account_id == handler.PAPER_SHADOW_V24:
            return [FakeTrade("MU")]
        return []

    def fake_list_armed(store, *, limit):
        if store.account_id == handler.PAPER_SHADOW_V25:
            return [
                {
                    "_persisted_signal_id": "PERSISTED-V25-1",
                    "signal_id": "SIG-V25-1",
                    "symbol": "NVDA",
                    "action": "ENTRY_LONG",
                    "model_id": handler.PAPER_SHADOW_V25,
                    "forward_test_start": "2026-08-19",
                    "received_at": "2026-08-19T19:00:00+00:00",
                    "replay_max_price": 200.0,
                }
            ]
        return []

    def fake_recent_events(store, *, limit):
        assert limit == 100
        if store.account_id == handler.PAPER_SHADOW_V24:
            return {
                "events": [
                    {
                        "signal_id": "SIG-V24-ENTRY",
                        "symbol": "MU",
                        "action": "ENTRY_LONG",
                        "model_id": handler.PAPER_SHADOW_V24,
                        "forward_test_start": "2026-08-19",
                        "replay_max_price": 130.0,
                        "received_at": "2026-08-19T18:55:00+00:00",
                        "disposition": "EXECUTED_PAPER",
                        "reason": "PAPER_ENTRY_EXECUTED",
                        "evaluated_at": "2026-08-19T18:55:01+00:00",
                        "paper_execution_triggered": True,
                        "paper_ledger_updated": True,
                        "paper_account_id": handler.PAPER_SHADOW_V24,
                        "execution_receipt": {
                            "account_id": handler.PAPER_SHADOW_V24,
                            "symbol": "MU",
                            "action": "ENTRY_LONG",
                            "quantity": 2,
                            "fill_price": 125.0,
                        },
                        "trading_authorized": False,
                        "live_trading_enabled": False,
                    }
                ],
                "event_count_visible": 1,
                "event_limit": 100,
                "scan_pages": 1,
                "scan_items_evaluated": 5,
                "scan_truncated": False,
            }
        return {
            "events": [],
            "event_count_visible": 0,
            "event_limit": 100,
            "scan_pages": 1,
            "scan_items_evaluated": 5,
            "scan_truncated": False,
        }

    monkeypatch.setattr(handler, "_all_open_trades", fake_open_trades)
    monkeypatch.setattr(handler, "list_armed_ingress", fake_list_armed)
    monkeypatch.setattr(handler, "list_recent_pine_event_state", fake_recent_events)
    now = datetime(2026, 8, 19, 19, 30, tzinfo=UTC)

    result = handler._shadow_monitor_state(now=now, armed_limit=25, event_limit=100)

    assert result["operation"] == "GET_SHADOW_MONITOR_STATE"
    assert result["snapshot_at"] == now.isoformat()
    v24 = result["books"][handler.PAPER_SHADOW_V24]
    assert v24["open_count"] == 1
    assert v24["open_positions"] == [{"symbol": "MU"}]
    assert v24["armed_count_visible"] == 0
    assert v24["event_count_visible"] == 1
    assert v24["events"][0]["disposition"] == "EXECUTED_PAPER"
    assert v24["events"][0]["execution_receipt"]["account_id"] == handler.PAPER_SHADOW_V24

    v25 = result["books"][handler.PAPER_SHADOW_V25]
    assert v25["open_count"] == 0
    assert v25["armed_count_visible"] == 1
    assert v25["armed_limit_reached"] is False
    assert v25["event_count_visible"] == 0
    assert v25["armed_signals"] == [
        {
            "persisted_signal_id": "PERSISTED-V25-1",
            "signal_id": "SIG-V25-1",
            "symbol": "NVDA",
            "action": "ENTRY_LONG",
            "model_id": handler.PAPER_SHADOW_V25,
            "forward_test_start": "2026-08-19",
            "received_at": "2026-08-19T19:00:00+00:00",
            "replay_max_price": 200.0,
        }
    ]
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_shadow_monitor_operation_fails_closed_for_invalid_armed_limit(monkeypatch):
    class Context:
        aws_request_id = "REQ-1"

    monkeypatch.setattr(handler, "DynamoPaperLedger", FakeLedger)
    monkeypatch.setattr(handler, "DynamoPineEventStore", FakeStore)
    monkeypatch.setattr(handler, "_all_open_trades", lambda ledger: [])

    def fake_list_armed(store, *, limit):
        raise ValueError("ARMED_REPLAY_LIMIT_INVALID")

    monkeypatch.setattr(handler, "list_armed_ingress", fake_list_armed)

    result = handler.lambda_handler(
        {"operation": "GET_SHADOW_MONITOR_STATE", "armed_limit": 0},
        Context(),
    )

    assert result["ok"] is False
    assert result["status"] == "REJECTED"
    assert result["error_code"] == "ARMED_REPLAY_LIMIT_INVALID"
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert result["request_id"] == "REQ-1"


def test_shadow_monitor_operation_fails_closed_for_invalid_event_limit(monkeypatch):
    class Context:
        aws_request_id = "REQ-2"

    monkeypatch.setattr(handler, "DynamoPaperLedger", FakeLedger)
    monkeypatch.setattr(handler, "DynamoPineEventStore", FakeStore)
    monkeypatch.setattr(handler, "_all_open_trades", lambda ledger: [])
    monkeypatch.setattr(handler, "list_armed_ingress", lambda store, *, limit: [])

    def fake_recent_events(store, *, limit):
        raise ValueError("SHADOW_MONITOR_EVENT_LIMIT_INVALID")

    monkeypatch.setattr(handler, "list_recent_pine_event_state", fake_recent_events)

    result = handler.lambda_handler(
        {"operation": "GET_SHADOW_MONITOR_STATE", "event_limit": 0},
        Context(),
    )

    assert result["ok"] is False
    assert result["status"] == "REJECTED"
    assert result["error_code"] == "SHADOW_MONITOR_EVENT_LIMIT_INVALID"
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert result["request_id"] == "REQ-2"
