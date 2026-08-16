from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.ledger import PaperLedger, TradeState
from daily_alpha.paper_runtime import PaperRuntimeError, process_paper_event

NOW = datetime(2026, 8, 16, 6, 30, tzinfo=UTC)


def engine_result(*, instrument="OPTION"):
    contract = None
    if instrument == "OPTION":
        contract = {
            "symbol": "AAPL",
            "expiration": "2026-10-16",
            "strike": 220.0,
            "option_type": "CALL",
            "dte": 60,
            "bid": 5.0,
            "ask": 5.2,
            "open_interest": 1000,
            "volume": 200,
            "delta": 0.50,
        }
    return {
        "ok": True,
        "mode": "PAPER",
        "live_trading_enabled": False,
        "signal": {
            "signal_id": "signal-aapl-entry",
            "symbol": "AAPL",
            "action": "ENTRY_LONG",
            "strategy": "DAILY_ALPHA_PINE",
            "strategy_version": "staging-v1",
            "timeframe": "1D",
            "price": 220.0,
            "bar_time": (NOW - timedelta(minutes=1)).isoformat(),
            "received_at": NOW.isoformat(),
        },
        "risk": {
            "status": "APPROVED",
            "policy_version": "2026-08-15-v2",
            "nav": 1_000_000.0,
        },
        "decision": {
            "symbol": "AAPL",
            "status": "SELECTED",
            "instrument_selected": instrument,
            "fallback_reason": (
                "QUALIFIED_OPTION_SELECTED"
                if instrument == "OPTION"
                else "NO_OPTION_PASSED_QUALITY_FILTERS_STOCK_ELIGIBLE"
            ),
            "selected_contract": contract,
            "created_at": NOW.isoformat(),
        },
    }


def exit_signal():
    return {
        "signal_id": "signal-aapl-exit",
        "symbol": "AAPL",
        "action": "EXIT",
        "strategy": "DAILY_ALPHA_PINE",
        "strategy_version": "staging-v1",
        "timeframe": "1D",
        "price": 225.0,
        "bar_time": (NOW + timedelta(minutes=9)).isoformat(),
    }


def test_option_decision_opens_idempotently_at_conservative_ask(tmp_path):
    ledger = PaperLedger(tmp_path)
    event = {"operation": "OPEN_FROM_DECISION", "engine_result": engine_result()}
    opened = process_paper_event(event, ledger)
    repeated = process_paper_event(event, ledger)

    assert opened["status"] == "OPENED"
    assert opened["trade"]["instrument"] == "OPTION"
    assert opened["trade"]["entry_price"] == 5.2
    assert opened["trade"]["quantity"] == 9
    assert opened["pricing_source"] == "SELECTED_OPTION_ASK"
    assert opened["paper_trade_written"] is True
    assert opened["live_trading_enabled"] is False

    assert repeated["status"] == "ALREADY_OPEN"
    assert repeated["idempotent"] is True
    assert repeated["paper_trade_written"] is False
    assert repeated["trade"]["trade_id"] == opened["trade"]["trade_id"]


def test_stock_fallback_requires_explicit_fill_and_stop(tmp_path):
    ledger = PaperLedger(tmp_path)
    base = {
        "operation": "OPEN_FROM_DECISION",
        "engine_result": engine_result(instrument="STOCK"),
    }
    with pytest.raises(PaperRuntimeError, match="stock_price"):
        process_paper_event(base, ledger)

    opened = process_paper_event(
        {
            **base,
            "pricing": {"stock_price": 220.0, "stock_stop_price": 210.0},
        },
        ledger,
    )
    assert opened["trade"]["instrument"] == "STOCK"
    assert opened["pricing_source"] == "EXPLICIT_STOCK_PAPER_FILL_AND_STOP"


def test_exit_signal_closes_selected_instrument_and_get_open_is_empty(tmp_path):
    ledger = PaperLedger(tmp_path)
    process_paper_event(
        {"operation": "OPEN_FROM_DECISION", "engine_result": engine_result()}, ledger
    )
    before = process_paper_event(
        {"operation": "GET_OPEN", "symbol": "AAPL"}, ledger
    )
    assert before["count"] == 1

    closed = process_paper_event(
        {
            "operation": "CLOSE_FROM_SIGNAL",
            "signal": exit_signal(),
            "pricing": {"option_exit_price": 5.7},
        },
        ledger,
        now=NOW + timedelta(minutes=10),
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_trades"][0]["state"] == TradeState.CLOSED.value
    assert closed["closed_trades"][0]["realized_pnl"] == 450.0

    after = process_paper_event(
        {"operation": "GET_OPEN", "symbol": "AAPL"}, ledger
    )
    assert after["count"] == 0
    assert after["status"] == "NO_OPEN_POSITION"


def test_paper_runtime_rechecks_engine_safety_boundaries(tmp_path):
    ledger = PaperLedger(tmp_path)
    unsafe = engine_result()
    unsafe["live_trading_enabled"] = True
    with pytest.raises(PaperRuntimeError, match="LIVE_TRADING_FLAG_NOT_DISABLED"):
        process_paper_event(
            {"operation": "OPEN_FROM_DECISION", "engine_result": unsafe}, ledger
        )

    rejected = engine_result()
    rejected["risk"]["status"] = "REJECTED"
    with pytest.raises(PaperRuntimeError, match="RISK_DECISION_NOT_APPROVED"):
        process_paper_event(
            {"operation": "OPEN_FROM_DECISION", "engine_result": rejected}, ledger
        )
