from datetime import UTC, datetime

from daily_alpha.ledger import PaperLedger
from daily_alpha.models import InstrumentSelected
from daily_alpha.pine_paper_orchestrator import AwsPinePaperExecutor

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def ingress(action="ENTRY_LONG", **overrides):
    payload = {
        "schema_version": "2026-08-16-v3",
        "source": "TRADINGVIEW_PINE",
        "signal_id": f"AAPL-{action}",
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
        "average_daily_dollar_volume": 100_000_000.0,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def executor(tmp_path):
    return AwsPinePaperExecutor(
        ledger=PaperLedger(tmp_path),
        paper_nav=1_000_000.0,
    )


def test_entry_opens_stock_only(tmp_path):
    service = executor(tmp_path)

    result = service.execute(ingress(), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    assert result["paper_execution_triggered"] is True
    assert result["live_trading_enabled"] is False
    assert result["context"]["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"
    open_trade = service.ledger.find_open("AAPL")[0]
    assert open_trade.instrument == InstrumentSelected.STOCK
    assert open_trade.runner_stage == "STARTER"


def test_stock_runner_add_uses_signal_price(tmp_path):
    service = executor(tmp_path)
    service.execute(ingress(), now=NOW)
    before = service.ledger.find_open("AAPL")[0]

    result = service.execute(
        ingress(
            "ADD",
            signal_id="AAPL-ADD-1",
            price=120.0,
            position_fraction=0.25,
            runner_stage="ADD_1_ATR",
        ),
        now=NOW,
    )

    after = service.ledger.find_open("AAPL")[0]
    assert result["reason"] == "PAPER_ADD_APPLIED"
    assert after.quantity > before.quantity
    assert after.runner_stage == "ADD_1_ATR"


def test_stock_entry_requires_valid_stop(tmp_path):
    service = executor(tmp_path)
    result = service.execute(ingress(stock_stop_price=110.0), now=NOW)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "STOCK_STOP_INVALID_FOR_LONG_ENTRY"
    assert service.ledger.find_open("AAPL") == []


def test_stock_entry_respects_ten_dollar_floor(tmp_path):
    service = executor(tmp_path)
    result = service.execute(
        ingress(price=9.99, stock_stop_price=9.0),
        now=NOW,
    )

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "STOCK_PRICE_BELOW_CANONICAL_FLOOR"


def test_after_close_signal_cannot_mutate_paper_ledger(tmp_path):
    service = executor(tmp_path)
    after_close = datetime(2026, 8, 17, 20, 5, tzinfo=UTC)

    result = service.execute(ingress(), now=after_close)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "OUTSIDE_REGULAR_EXECUTION_WINDOW"
    assert result["paper_execution_triggered"] is False
    assert result["live_trading_enabled"] is False
    assert service.ledger.find_open("AAPL") == []


def test_entry_with_unverified_sector_is_blocked(tmp_path):
    service = executor(tmp_path)

    result = service.execute(ingress(sector="Unknown"), now=NOW)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "SECTOR_DATA_UNVERIFIED"
    assert service.ledger.find_open("AAPL") == []


def test_paper_entry_is_automatic_without_option_data_or_human_approval(tmp_path):
    service = executor(tmp_path)

    result = service.execute(ingress(), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    assert result["context"]["automated_options_execution"] is False
    assert service.ledger.find_open("AAPL")


def test_early_emerging_sizes_below_confirmed_leader(tmp_path):
    early = executor(tmp_path / "early")
    leader = executor(tmp_path / "leader")

    early.execute(ingress(lifecycle="EARLY_EMERGING"), now=NOW)
    leader.execute(ingress(lifecycle="CONFIRMED_LEADER"), now=NOW)

    early_trade = early.ledger.find_open("AAPL")[0]
    leader_trade = leader.ledger.find_open("AAPL")[0]
    assert early_trade.target_quantity < leader_trade.target_quantity


def test_legacy_option_position_is_not_automatically_managed(tmp_path):
    service = executor(tmp_path)
    service.ledger.open_trade(
        signal_id="legacy-option",
        symbol="AAPL",
        instrument=InstrumentSelected.OPTION,
        quantity=1,
        entry_price=2.0,
        entry_time=NOW,
        fallback_reason="LEGACY_USER_DIRECTED_OPTION",
        option_expiration="2026-10-16",
        option_strike=110.0,
        option_type="CALL",
    )

    result = service.execute(
        ingress(
            "ADD",
            signal_id="AAPL-ADD-OPTION",
            price=120.0,
            position_fraction=0.25,
            runner_stage="ADD_1_ATR",
        ),
        now=NOW,
    )

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "USER_DIRECTED_OPTION_MANAGEMENT_REQUIRED"
    assert result["context"]["automated_option_management"] is False
