from datetime import UTC, datetime

from lambda_handlers import pine_processor as handler


class FakeStore:
    def __init__(self, account_id=None):
        self.account_id = account_id or "paper-staging"


class FakeExecutor:
    pass


def test_replay_all_paper_accounts_scans_default_and_both_shadows(monkeypatch):
    monkeypatch.setattr(handler, "DynamoPineEventStore", FakeStore)
    monkeypatch.setattr(handler, "ShadowRoutedPinePaperExecutor", FakeExecutor)
    monkeypatch.setattr(handler, "default_paper_account_id", lambda: "paper-staging")

    seen = []

    def fake_replay(store, executor, *, now, limit):
        assert isinstance(executor, FakeExecutor)
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

    seen = []

    def fake_replay(store, executor, *, now, limit):
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
