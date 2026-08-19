from datetime import UTC, datetime

from daily_alpha.ledger import PaperLedger
from daily_alpha.models import Decision, DecisionStatus, InstrumentSelected, OptionCandidate
from daily_alpha.pipeline import EntryPricing, PaperTradingPipeline
from daily_alpha.pine_paper_reconciliation import ReconciledAwsPinePaperExecutor
from daily_alpha.reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor
from daily_alpha.signals import SignalAction, parse_pine_signal
from daily_alpha.sizing import PortfolioLimits

NOW = datetime(2026, 8, 19, 14, 5, tzinfo=UTC)


def _signal(action: SignalAction):
    payload = {
        "signal_id": f"risk-{action.value}",
        "symbol": "RDW",
        "action": action.value,
        "strategy": "QARS Turtle",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 15.0,
        "bar_time": NOW.isoformat(),
    }
    if action == SignalAction.ADD:
        payload.update(position_fraction=0.25, runner_stage="ADD_1_ATR")
    if action == SignalAction.PARTIAL:
        payload.update(position_fraction=0.25, runner_stage="HARVEST_3_ATR")
    return parse_pine_signal(payload, received_at=NOW)


def test_pipeline_persists_actual_runner_target_risk_for_stock_and_option(tmp_path):
    limits = PortfolioLimits(nav=1_000_000)

    stock_ledger = PaperLedger(tmp_path / "stock")
    stock_pipeline = PaperTradingPipeline(stock_ledger, limits)
    stock = stock_pipeline.process_entry(
        signal=_signal(SignalAction.ENTRY_LONG),
        decision=Decision.create(
            symbol="RDW",
            status=DecisionStatus.SELECTED,
            instrument_selected=InstrumentSelected.STOCK,
            fallback_reason="STOCK_FALLBACK",
        ),
        pricing=EntryPricing(stock_price=15.0, stock_stop_price=14.0),
    )
    assert stock.target_quantity == 1332
    assert stock.initial_risk_basis == 1332.0

    option_ledger = PaperLedger(tmp_path / "option")
    option_pipeline = PaperTradingPipeline(option_ledger, limits)
    option = option_pipeline.process_entry(
        signal=_signal(SignalAction.ENTRY_LONG),
        decision=Decision.create(
            symbol="RDW",
            status=DecisionStatus.SELECTED,
            instrument_selected=InstrumentSelected.OPTION,
            fallback_reason="QUALIFIED_OPTION_SELECTED",
            selected_contract=OptionCandidate(
                symbol="RDW",
                expiration="2026-10-16",
                strike=15.0,
                option_type="CALL",
                dte=58,
                bid=1.9,
                ask=2.1,
                open_interest=500,
                volume=50,
            ),
        ),
        pricing=EntryPricing(option_premium=2.0),
    )
    assert option.target_quantity == 24
    assert option.initial_risk_basis == 4800.0


def test_legacy_trade_without_risk_basis_still_deserializes(tmp_path):
    ledger = PaperLedger(tmp_path)
    path = tmp_path / "stock_trades.jsonl"
    path.write_text(
        '{"event":"OPEN","signal_id":"legacy","trade":{"trade_id":"t1",'
        '"signal_id":"legacy","symbol":"RDW","instrument":"STOCK",'
        '"quantity":4,"entry_price":10.0,"entry_time":"2026-08-19T14:00:00+00:00",'
        '"state":"OPEN","sector":"Industrials"}}\n',
        encoding="utf-8",
    )
    trade = ledger.find_open("RDW")[0]
    assert trade.initial_risk_basis is None


class _Trade:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class _Ledger:
    account_id = "paper-shadow-v24"

    def __init__(self, payload):
        self.payload = payload

    def find_open(self, symbol, instrument=None):
        return [_Trade(self.payload)]


def test_exit_receipt_uses_persisted_trade_risk_when_result_has_no_risk_context(monkeypatch):
    before = {
        "trade_id": "trade-1",
        "signal_id": "entry-1",
        "symbol": "RDW",
        "instrument": "STOCK",
        "quantity": 10,
        "entry_price": 100.0,
        "entry_time": NOW.isoformat(),
        "state": "OPEN",
        "realized_pnl": 0.0,
        "target_quantity": 10,
        "runner_stage": "STARTER",
        "sector": "Industrials",
        "initial_risk_basis": 500.0,
    }
    closed = {
        **before,
        "state": "CLOSED",
        "exit_price": 110.0,
        "exit_time": NOW.isoformat(),
        "realized_pnl": 100.0,
    }
    executor = ReceiptReconciledAwsPinePaperExecutor(
        ledger=_Ledger(before),
        secrets_client=object(),
        paper_nav=1_000_000,
        orats_factory=lambda token: None,
    )

    def fake_execute(self, ingress, *, now=None):
        return {
            "disposition": "EXECUTED_PAPER",
            "action": "EXIT",
            "symbol": "RDW",
            "paper": {"closed_trades": [closed], "paper_ledger_updated": True},
            "context": {},
            "trading_authorized": False,
            "live_trading_enabled": False,
        }

    monkeypatch.setattr(ReconciledAwsPinePaperExecutor, "execute", fake_execute)
    result = executor.execute(
        {"signal_id": "exit-1", "symbol": "RDW", "action": "EXIT", "price": 110.0},
        now=NOW,
    )

    receipt = result["execution_receipt"]
    assert receipt["initial_risk_basis"] == 500.0
    assert receipt["realized_pnl_this_event"] == 100.0
    assert receipt["realized_r_this_event"] == 0.2
    assert receipt["r_basis_status"] == "AVAILABLE"
    assert receipt["live_trading_enabled"] is False
