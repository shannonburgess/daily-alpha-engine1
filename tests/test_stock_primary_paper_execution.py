from datetime import UTC, datetime

from daily_alpha.ledger import PaperLedger
from daily_alpha.reconciled_receipt_executor import (
    ReceiptReconciledAwsPinePaperExecutor,
    STOCK_PRIMARY_POLICY,
)

NOW = datetime(2026, 8, 20, 19, 55, tzinfo=UTC)
AFTER_CLOSE = datetime(2026, 8, 20, 20, 5, tzinfo=UTC)


class ExplodingSecrets:
    def get_secret_value(self, *, SecretId):  # pragma: no cover - must never run
        raise AssertionError("ORATS secret must not be read for stock-primary entry")


class ExplodingOrats:
    def fetch_chain(self, *args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("ORATS must not be called for stock-primary PAPER entry")


def ingress(action="ENTRY_LONG", **overrides):
    payload = {
        "schema_version": "2026-08-16-v3",
        "source": "TRADINGVIEW_PINE",
        "signal_id": f"AAPL-{action}-STOCK-PRIMARY",
        "symbol": "AAPL",
        "sector": "Technology",
        "lifecycle": "CONFIRMED_LEADER",
        "action": action,
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 110.0,
        "bar_time": NOW.isoformat(),
        "received_at": NOW.isoformat(),
        "position_fraction": None,
        "runner_stage": None,
        "stock_stop_price": 100.0,
        "average_daily_dollar_volume": 75_000_000.0,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def executor(tmp_path):
    return ReceiptReconciledAwsPinePaperExecutor(
        ledger=PaperLedger(tmp_path),
        secrets_client=ExplodingSecrets(),
        paper_nav=1_000_000.0,
        orats_factory=lambda token: ExplodingOrats(),
    )


def test_new_paper_entry_is_stock_and_never_calls_orats(tmp_path):
    service = executor(tmp_path)

    result = service.execute(ingress(), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    assert result["reason"] == "PAPER_STOCK_POSITION_OPENED"
    trade = service.ledger.find_open("AAPL")[0]
    assert trade.instrument.value == "STOCK"
    assert trade.entry_price == 110.0
    assert trade.fallback_reason == STOCK_PRIMARY_POLICY
    assert result["context"]["options_execution_enabled"] is False
    assert result["context"]["orats_required_for_new_entry"] is False
    assert result["context"]["fill_model"] == (
        "CONFIRMED_SIGNAL_PRICE_PROCESS_ORDERS_ON_CLOSE"
    )
    receipt = result["execution_receipt"]
    assert receipt["instrument"] == "STOCK"
    assert receipt["fill_price"] == 110.0
    assert receipt["live_trading_enabled"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_stock_entry_below_broad_ten_dollar_floor_is_blocked(tmp_path):
    service = executor(tmp_path)

    result = service.execute(
        ingress(price=9.99, stock_stop_price=9.0),
        now=NOW,
    )

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "STOCK_PRICE_BELOW_CANONICAL_FLOOR"
    assert service.ledger.find_open("AAPL") == []


def test_stock_entry_requires_valid_long_stop(tmp_path):
    service = executor(tmp_path)

    result = service.execute(
        ingress(stock_stop_price=110.0),
        now=NOW,
    )

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "STOCK_STOP_INVALID_FOR_LONG_ENTRY"
    assert service.ledger.find_open("AAPL") == []


def test_confirmed_close_signal_after_regular_session_uses_model_fill(tmp_path):
    service = executor(tmp_path)

    result = service.execute(ingress(), now=AFTER_CLOSE)

    assert result["disposition"] == "EXECUTED_PAPER"
    trade = service.ledger.find_open("AAPL")[0]
    assert trade.instrument.value == "STOCK"
    assert trade.entry_price == 110.0
    assert result["context"]["signal_fill_price"] == 110.0
    assert result["context"]["fill_model"] == (
        "CONFIRMED_SIGNAL_PRICE_PROCESS_ORDERS_ON_CLOSE"
    )


def test_stock_runner_add_and_exit_do_not_require_orats(tmp_path):
    service = executor(tmp_path)
    service.execute(ingress(), now=NOW)
    before = service.ledger.find_open("AAPL")[0]

    add_result = service.execute(
        ingress(
            "ADD",
            signal_id="AAPL-ADD-1-STOCK",
            price=120.0,
            position_fraction=0.25,
            runner_stage="ADD_1_ATR",
            stock_stop_price=None,
        ),
        now=NOW,
    )
    after = service.ledger.find_open("AAPL")[0]

    assert add_result["disposition"] == "EXECUTED_PAPER"
    assert after.quantity > before.quantity
    assert after.runner_stage == "ADD_1_ATR"
    assert add_result["context"]["orats_required_for_new_entry"] is False

    exit_result = service.execute(
        ingress(
            "EXIT",
            signal_id="AAPL-EXIT-STOCK",
            price=125.0,
            stock_stop_price=None,
        ),
        now=NOW,
    )
    assert exit_result["disposition"] == "EXECUTED_PAPER"
    assert service.ledger.find_open("AAPL") == []
    assert exit_result["execution_receipt"]["instrument"] == "STOCK"
