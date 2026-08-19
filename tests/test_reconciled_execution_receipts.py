from datetime import UTC, datetime

from daily_alpha.execution_receipts import build_paper_execution_receipt
from daily_alpha.pine_paper_reconciliation import ReconciledAwsPinePaperExecutor
from daily_alpha.reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor

NOW = datetime(2026, 8, 19, 14, 5, tzinfo=UTC)


def _stock_trade(**overrides):
    trade = {
        "trade_id": "trade-1",
        "signal_id": "entry-1",
        "symbol": "CAT",
        "instrument": "STOCK",
        "quantity": 10,
        "entry_price": 100.0,
        "entry_time": "2026-08-19T14:00:00+00:00",
        "state": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "realized_pnl": None,
        "fallback_reason": "STOCK_FALLBACK",
        "option_expiration": None,
        "option_strike": None,
        "option_type": None,
        "target_quantity": 12,
        "runner_stage": "STARTER",
        "add1_signal_id": None,
        "add2_signal_id": None,
        "harvest_signal_id": None,
        "sector": "Industrials",
    }
    trade.update(overrides)
    return trade


class FakeTrade:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class FakeLedger:
    account_id = "paper-shadow-v24"

    def __init__(self, trade=None):
        self.trade = trade

    def find_open(self, symbol, instrument=None):
        if self.trade is None:
            return []
        return [FakeTrade(self.trade)]


def _executor(ledger):
    return ReceiptReconciledAwsPinePaperExecutor(
        ledger=ledger,
        secrets_client=object(),
        paper_nav=1_000_000,
        orats_factory=lambda token: None,
    )


def test_receipt_contract_preserves_stock_notional_and_realized_r():
    before = _stock_trade(quantity=10, realized_pnl=0.0)
    closed = _stock_trade(
        quantity=10,
        state="CLOSED",
        exit_price=110.0,
        exit_time=NOW.isoformat(),
        realized_pnl=100.0,
    )
    receipt = build_paper_execution_receipt(
        action="EXIT",
        paper={"closed_trades": [closed], "signal_id": "exit-1"},
        fill_price=110.0,
        before_trade=before,
        initial_risk_basis=500.0,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["fill_quantity"] == 10
    assert receipt["fill_notional"] == 1_100.0
    assert receipt["remaining_quantity"] == 0
    assert receipt["realized_pnl_this_event"] == 100.0
    assert receipt["realized_r_this_event"] == 0.2
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False


def test_reconciled_entry_attaches_receipt_without_changing_execution(monkeypatch):
    ledger = FakeLedger()
    executor = _executor(ledger)
    ingress = {
        "signal_id": "entry-1",
        "symbol": "CAT",
        "action": "ENTRY_LONG",
        "price": 100.0,
    }

    def fake_execute(self, ingress, *, now=None):
        return {
            "disposition": "EXECUTED_PAPER",
            "reason": "PAPER_POSITION_OPENED",
            "action": "ENTRY_LONG",
            "symbol": "CAT",
            "paper_execution_triggered": True,
            "paper_ledger_updated": True,
            "trading_authorized": False,
            "live_trading_enabled": False,
            "paper": {"trade": _stock_trade(), "paper_ledger_updated": True},
            "context": {"risk": {"planned_loss": 500.0}},
        }

    monkeypatch.setattr(ReconciledAwsPinePaperExecutor, "execute", fake_execute)
    result = executor.execute(ingress, now=NOW)

    receipt = result["execution_receipt"]
    assert result["disposition"] == "EXECUTED_PAPER"
    assert receipt["action"] == "ENTRY_LONG"
    assert receipt["fill_price"] == 100.0
    assert receipt["fill_quantity"] == 10
    assert receipt["fill_notional"] == 1_000.0
    assert receipt["account_id"] == "paper-shadow-v24"
    assert result["paper"]["execution_receipt"] == receipt


def test_armed_replay_receipt_uses_refreshed_market_price_and_replay_signal_id(
    monkeypatch,
):
    before = _stock_trade(quantity=10, entry_price=100.0)
    ledger = FakeLedger(before)
    executor = _executor(ledger)
    ingress = {
        "signal_id": "CAT-ADD-ORIGIN",
        "symbol": "CAT",
        "action": "ADD",
        "price": 99.0,
        "runner_stage": "ADD_1_ATR",
        "position_fraction": 0.2,
    }
    replay_signal_id = "CAT-ADD-ORIGIN-REPLAY-20260819T140500"
    after = _stock_trade(
        quantity=12,
        entry_price=100.83333333,
        runner_stage="ADD_1_ATR",
        add1_signal_id=replay_signal_id,
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
    result = executor.replay_armed(ingress, now=NOW)

    receipt = result["execution_receipt"]
    assert receipt["signal_id"] == replay_signal_id
    assert receipt["fill_price"] == 105.0
    assert receipt["fill_quantity"] == 2
    assert receipt["fill_notional"] == 210.0
    assert receipt["remaining_quantity"] == 12
    assert result["paper"]["signal_id"] == replay_signal_id


def test_armed_or_state_mismatch_never_fabricates_receipt(monkeypatch):
    executor = _executor(FakeLedger())

    def fake_execute(self, ingress, *, now=None):
        return {
            "disposition": "STATE_MISMATCH",
            "reason": "TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER",
            "action": "EXIT",
            "symbol": "VLO",
            "paper_execution_triggered": False,
            "paper_ledger_updated": False,
            "trading_authorized": False,
            "live_trading_enabled": False,
            "paper": {},
            "context": {},
        }

    monkeypatch.setattr(ReconciledAwsPinePaperExecutor, "execute", fake_execute)
    result = executor.execute(
        {"signal_id": "vlo-exit", "symbol": "VLO", "action": "EXIT", "price": 1.0},
        now=NOW,
    )

    assert result["disposition"] == "STATE_MISMATCH"
    assert "execution_receipt" not in result
