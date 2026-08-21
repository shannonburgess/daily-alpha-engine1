from datetime import UTC, datetime

import pytest

from daily_alpha.ledger import PaperLedger
from daily_alpha.pine_processor import PineProcessorError, PineProcessorResult
from daily_alpha.shadow_routing import (
    PAPER_SHADOW_V24,
    PAPER_SHADOW_V25,
    ShadowRoutedPineEventStore,
    ShadowRoutedPinePaperExecutor,
    account_id_for_ingress,
)

SHADOW_START = "2026-08-19"


class AccountPaperLedger(PaperLedger):
    def __init__(self, root, account_id):
        super().__init__(root)
        self.account_id = account_id


class RecordingStore:
    def __init__(self, account_id):
        self.account_id = account_id
        self.persisted = []
        self.executions = []

    def persist(self, ingress, result):
        self.persisted.append((dict(ingress), result.signal_id))
        return True

    def mark_execution(self, signal_id, execution):
        self.executions.append((signal_id, dict(execution)))


def _ingress(version, model_id=None, forward_test_start=SHADOW_START):
    payload = {
        "schema_version": "2026-08-18-v5",
        "source": "TRADINGVIEW_PINE",
        "signal_id": f"AMD-{version}",
        "symbol": "AMD",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": version,
        "timeframe": "1D",
        "price": 250.0,
        "bar_time": "2026-08-19T20:00:00+00:00",
        "received_at": "2026-08-19T20:00:00+00:00",
        "entry_type": "ARMED_BREAKOUT_CONFIRM" if version == "2.5" else "NORMAL_BREAKOUT",
        "sector": "Information Technology",
        "stock_stop_price": 235.0,
        "average_daily_dollar_volume": 1_000_000_000,
        "replay_max_price": 260.0,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    if model_id is not None:
        payload["model_id"] = model_id
        payload["forward_test_start"] = forward_test_start
    return payload


def test_untagged_existing_v24_is_not_silently_migrated(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_PAPER_ACCOUNT_ID", "paper-staging")
    assert account_id_for_ingress(_ingress("2.4")) == "paper-staging"


def test_explicit_shadow_models_route_to_separate_accounts(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)
    assert account_id_for_ingress(_ingress("2.4", PAPER_SHADOW_V24)) == PAPER_SHADOW_V24
    assert account_id_for_ingress(_ingress("2.5", PAPER_SHADOW_V25)) == PAPER_SHADOW_V25


def test_shadow_model_version_mismatch_fails_closed(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)
    with pytest.raises(PineProcessorError, match="VERSION_MISMATCH"):
        account_id_for_ingress(_ingress("2.4", PAPER_SHADOW_V25))


def test_shadow_start_configuration_is_required(monkeypatch):
    monkeypatch.delenv("DAILY_ALPHA_SHADOW_FORWARD_START", raising=False)
    with pytest.raises(PineProcessorError, match="FORWARD_START_NOT_CONFIGURED"):
        account_id_for_ingress(_ingress("2.5", PAPER_SHADOW_V25))


def test_shadow_models_must_match_same_configured_forward_start(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)
    with pytest.raises(PineProcessorError, match="FORWARD_START_MISMATCH"):
        account_id_for_ingress(
            _ingress("2.5", PAPER_SHADOW_V25, forward_test_start="2026-08-20")
        )


def test_shadow_event_store_uses_model_specific_account(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)
    stores = {}

    def factory(account_id):
        store = RecordingStore(account_id)
        stores[account_id] = store
        return store

    router = ShadowRoutedPineEventStore(store_factory=factory)
    ingress = _ingress("2.5", PAPER_SHADOW_V25)
    result = PineProcessorResult(
        schema_version="test",
        signal_id=ingress["signal_id"],
        symbol="AMD",
        action="ENTRY_LONG",
        disposition="HELD_FOR_CONTEXT",
        reason="TEST",
        received_at=ingress["received_at"],
        processed_at=ingress["received_at"],
    )

    assert router.persist(ingress, result) is True
    router.mark_execution(
        result.signal_id,
        {"disposition": "ARMED_FOR_NEXT_TRADABLE_WINDOW", "reason": "TEST"},
    )

    assert PAPER_SHADOW_V25 in stores
    assert stores[PAPER_SHADOW_V25].persisted[0][1] == result.signal_id
    assert stores[PAPER_SHADOW_V25].executions[0][0] == result.signal_id


def test_v25_executor_preserves_shadow_account_and_arms_after_hours(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)
    ledgers = {}

    def ledger_factory(account_id):
        ledger = AccountPaperLedger(tmp_path / account_id, account_id)
        ledgers[account_id] = ledger
        return ledger

    executor = ShadowRoutedPinePaperExecutor(
        paper_nav=1_000_000,
        secrets_client=object(),
        ledger_factory=ledger_factory,
    )

    result = executor.execute(
        _ingress("2.5", PAPER_SHADOW_V25),
        now=datetime(2026, 8, 19, 20, 5, tzinfo=UTC),
    )

    assert result["disposition"] == "ARMED_FOR_NEXT_TRADABLE_WINDOW"
    assert result["reason"] == "MARKET_CLOSED_REVALIDATION_REQUIRED"
    assert result["paper_account_id"] == PAPER_SHADOW_V25
    assert result["model_id"] == PAPER_SHADOW_V25
    assert result["forward_test_start"] == SHADOW_START
    assert result["paper_execution_triggered"] is False
    assert result["context"]["execution_policy"] == (
        "STOCK_PRIMARY_MODEL_VALIDATION_V1"
    )
    assert result["context"]["options_execution_enabled"] is False
    assert result["context"]["orats_required_for_new_entry"] is False
    assert ledgers[PAPER_SHADOW_V25].find_open("AMD") == []
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
