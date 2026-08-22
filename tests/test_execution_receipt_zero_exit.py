from datetime import UTC, datetime

import pytest

from daily_alpha.execution_receipts import build_paper_execution_receipt
from daily_alpha.reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor

NOW = datetime(2026, 8, 22, 5, 40, tzinfo=UTC)


def _trade(**overrides):
    payload = {
        "trade_id": "zero-exit-trade",
        "signal_id": "entry-zero-exit",
        "symbol": "LOSS",
        "instrument": "STOCK",
        "quantity": 10,
        "entry_price": 100.0,
        "entry_time": "2026-08-21T14:00:00+00:00",
        "state": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "realized_pnl": 0.0,
        "fallback_reason": "STOCK_PRIMARY_MODEL_VALIDATION_V1",
        "option_expiration": None,
        "option_strike": None,
        "option_type": None,
        "target_quantity": 10,
        "runner_stage": "STARTER",
        "add1_signal_id": None,
        "add2_signal_id": None,
        "harvest_signal_id": None,
        "sector": "Industrials",
        "initial_risk_basis": 100.0,
    }
    payload.update(overrides)
    return payload


class _FakeTrade:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class _FakeLedger:
    account_id = "PAPER_SHADOW_V24"

    def __init__(self, trade):
        self.trade = trade

    def find_open(self, symbol, instrument=None):
        return [_FakeTrade(self.trade)]


def test_zero_price_exit_receipt_preserves_catastrophic_loss_evidence():
    before = _trade()
    closed = _trade(
        state="CLOSED",
        exit_price=0.0,
        exit_time=NOW.isoformat(),
        realized_pnl=-1_000.0,
    )

    receipt = build_paper_execution_receipt(
        action="EXIT",
        paper={"closed_trades": [closed], "signal_id": "exit-zero"},
        fill_price=0.0,
        before_trade=before,
        account_id="PAPER_SHADOW_V24",
        initial_risk_basis=100.0,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["fill_price"] == 0.0
    assert receipt["fill_notional"] == 0.0
    assert receipt["fill_quantity"] == 10
    assert receipt["remaining_quantity"] == 0
    assert receipt["realized_pnl_this_event"] == -1_000.0
    assert receipt["cumulative_realized_pnl"] == -1_000.0
    assert receipt["realized_r_this_event"] == -10.0
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False


def test_zero_price_non_exit_and_nonfinite_prices_still_fail_closed():
    open_trade = _trade()
    with pytest.raises(ValueError, match="EXECUTION_RECEIPT_FILL_PRICE_INVALID"):
        build_paper_execution_receipt(
            action="ENTRY_LONG",
            paper={"trade": open_trade},
            fill_price=0.0,
            occurred_at=NOW,
        )

    closed = _trade(
        state="CLOSED",
        exit_price=0.0,
        exit_time=NOW.isoformat(),
        realized_pnl=-1_000.0,
    )
    for bad_price in (float("nan"), float("inf"), float("-inf"), -0.01):
        with pytest.raises(ValueError, match="EXECUTION_RECEIPT_FILL_PRICE_INVALID"):
            build_paper_execution_receipt(
                action="EXIT",
                paper={"closed_trades": [closed], "signal_id": "exit-bad"},
                fill_price=bad_price,
                before_trade=open_trade,
                occurred_at=NOW,
            )


def test_reconciled_stock_exit_can_attach_zero_price_receipt(monkeypatch):
    before = _trade()
    closed = _trade(
        state="CLOSED",
        exit_price=0.0,
        exit_time=NOW.isoformat(),
        realized_pnl=-1_000.0,
    )
    executor = ReceiptReconciledAwsPinePaperExecutor(
        ledger=_FakeLedger(before),
        secrets_client=object(),
        paper_nav=1_000_000,
        orats_factory=lambda token: None,
    )

    def fake_execute(self, ingress, *, now=None):
        return {
            "disposition": "EXECUTED_PAPER",
            "reason": "PAPER_POSITION_CLOSED",
            "action": "EXIT",
            "symbol": "LOSS",
            "paper_execution_triggered": True,
            "paper_ledger_updated": True,
            "trading_authorized": False,
            "live_trading_enabled": False,
            "paper": {
                "closed_trades": [closed],
                "paper_ledger_updated": True,
            },
            "context": {},
        }

    monkeypatch.setattr(
        ReceiptReconciledAwsPinePaperExecutor,
        "_execute_stock_primary",
        fake_execute,
    )
    result = executor.execute(
        {
            "signal_id": "exit-zero",
            "symbol": "LOSS",
            "action": "EXIT",
            "price": 0.0,
        },
        now=NOW,
    )

    receipt = result["execution_receipt"]
    assert result["disposition"] == "EXECUTED_PAPER"
    assert receipt["fill_price"] == 0.0
    assert receipt["cumulative_realized_pnl"] == -1_000.0
    assert receipt["realized_r_this_event"] == -10.0
    assert result["paper"]["execution_receipt"] == receipt
