from __future__ import annotations

from datetime import UTC, datetime

from scripts.shadow_monitor import render_markdown, summarize

NOW = datetime(2026, 8, 19, 20, 30, tzinfo=UTC)
REGULAR_NOW = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)
PREMARKET_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def monitor_state(*, v24=None, v25=None, v24_armed=0, v25_armed=0):
    return {
        "ok": True,
        "books": {
            "PAPER_SHADOW_V24": {
                "open_count": 0,
                "open_positions": [],
                "armed_count_visible": v24_armed,
                "events": v24 or [],
                "scan_truncated": False,
            },
            "PAPER_SHADOW_V25": {
                "open_count": 0,
                "open_positions": [],
                "armed_count_visible": v25_armed,
                "events": v25 or [],
                "scan_truncated": False,
            },
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def event(
    account: str,
    *,
    signal_id=None,
    symbol="AAPL",
    disposition="NO_TRADE",
    reason="PORTFOLIO_RISK_REJECTED",
    receipt=None,
    paper_account_id=None,
):
    return {
        "signal_id": signal_id or f"sig-{account}",
        "symbol": symbol,
        "action": "ENTRY_LONG",
        "model_id": account,
        "forward_test_start": "2026-08-19",
        "replay_max_price": 230.0,
        "received_at": "2026-08-19T19:55:00+00:00",
        "disposition": disposition,
        "reason": reason,
        "evaluated_at": "2026-08-19T19:55:01+00:00",
        "paper_execution_triggered": disposition == "EXECUTED_PAPER",
        "paper_ledger_updated": disposition == "EXECUTED_PAPER",
        "paper_account_id": paper_account_id or account,
        "execution_receipt": receipt,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def test_no_event_day_is_explicit_not_assumed_trade_rejection():
    summary = summarize(monitor_state(), now=NOW)

    assert summary["diagnosis"] == "NO_GENUINE_STRATEGY_EVENT_RECEIVED"
    assert summary["session_phase"] == "POST_SESSION"
    assert summary["session_complete"] is True
    assert summary["zero_trade_status"] == "FINAL_AT_AWS_BOUNDARY"
    assert summary["total_strategy_events"] == 0
    assert summary["total_test_events"] == 0
    assert summary["total_session_fills"] == 0
    assert summary["safety"]["violations"] == []
    rendered = render_markdown(summary)
    assert "final zero-trade result at the AWS evidence boundary" in rendered
    assert "TradingView configuration remains frozen" in rendered


def test_in_session_no_event_state_is_provisional_not_final_zero_trade():
    summary = summarize(monitor_state(), now=REGULAR_NOW)

    assert summary["diagnosis"] == "NO_GENUINE_STRATEGY_EVENT_RECEIVED"
    assert summary["session_phase"] == "REGULAR_SESSION"
    assert summary["session_complete"] is False
    assert summary["zero_trade_status"] == "PROVISIONAL_SESSION_IN_PROGRESS"
    rendered = render_markdown(summary)
    assert "state is provisional until the regular session is complete" in rendered
    assert "final zero-trade result" not in rendered


def test_premarket_no_event_state_is_provisional_before_open():
    summary = summarize(monitor_state(), now=PREMARKET_NOW)

    assert summary["session_phase"] == "PREMARKET"
    assert summary["session_complete"] is False
    assert summary["zero_trade_status"] == "PROVISIONAL_SESSION_NOT_OPEN"


def test_e2e_proof_is_excluded_from_genuine_trade_diagnosis():
    proof = event(
        "PAPER_SHADOW_V25",
        signal_id="TV-SHADOW-E2E-20260819-01",
        symbol="MU",
        disposition="STATE_MISMATCH",
        reason="TRADINGVIEW_POSITION_NOT_IN_PAPER_LEDGER",
    )

    summary = summarize(monitor_state(v25=[proof]), now=NOW)

    assert summary["diagnosis"] == "NO_GENUINE_STRATEGY_EVENT_RECEIVED"
    assert summary["total_strategy_events"] == 0
    assert summary["total_test_events"] == 1
    assert summary["blocker_counts"] == {}
    assert summary["accounts"]["PAPER_SHADOW_V25"]["session_test_event_count"] == 1
    assert "excluded from the trade diagnosis" in render_markdown(summary)


def test_strategy_event_without_fill_surfaces_exact_reason():
    summary = summarize(
        monitor_state(v24=[event("PAPER_SHADOW_V24")]),
        now=NOW,
    )

    assert summary["diagnosis"] == "STRATEGY_EVENTS_RECEIVED_NO_PAPER_FILL"
    assert summary["zero_trade_status"] == "FINAL_EXACT_BLOCKERS_RECORDED"
    assert summary["total_strategy_events"] == 1
    assert summary["accounts"]["PAPER_SHADOW_V24"]["reason_counts"] == {
        "PORTFOLIO_RISK_REJECTED": 1
    }
    assert summary["blocker_counts"] == {"PORTFOLIO_RISK_REJECTED": 1}


def test_armed_state_is_visible_without_manufacturing_fill():
    summary = summarize(monitor_state(v25_armed=1), now=NOW)

    assert summary["diagnosis"] == "ARMED_WAITING_FOR_REVALIDATION"
    assert summary["zero_trade_status"] is None
    assert summary["total_armed"] == 1
    assert summary["total_session_fills"] == 0


def test_executed_paper_receipt_is_counted_and_rendered():
    receipt = {
        "account_id": "PAPER_SHADOW_V25",
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "quantity": 10,
        "fill_price": 100.25,
    }
    state = monitor_state(
        v25=[
            event(
                "PAPER_SHADOW_V25",
                disposition="EXECUTED_PAPER",
                reason="PAPER_ENTRY_EXECUTED",
                receipt=receipt,
            )
        ]
    )
    state["books"]["PAPER_SHADOW_V25"]["open_count"] = 1
    state["books"]["PAPER_SHADOW_V25"]["open_positions"] = [
        {"symbol": "AAPL", "instrument": "STOCK"}
    ]

    summary = summarize(state, now=NOW)

    assert summary["diagnosis"] == "TRADES_RECORDED"
    assert summary["zero_trade_status"] is None
    assert summary["total_session_fills"] == 1
    assert summary["accounts"]["PAPER_SHADOW_V25"]["open_count"] == 1
    assert "`AAPL` ENTRY_LONG: qty=10, fill=100.25" in render_markdown(summary)


def test_cross_account_receipt_fails_safety_and_isolation_check():
    receipt = {
        "account_id": "PAPER_SHADOW_V25",
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "quantity": 1,
        "fill_price": 100.0,
    }
    bad = event(
        "PAPER_SHADOW_V24",
        disposition="EXECUTED_PAPER",
        reason="PAPER_ENTRY_EXECUTED",
        receipt=receipt,
        paper_account_id="PAPER_SHADOW_V25",
    )

    summary = summarize(monitor_state(v24=[bad]), now=NOW)

    assert summary["ok"] is False
    assert summary["diagnosis"] == "SAFETY_OR_EVIDENCE_VIOLATION"
    assert any("ACCOUNT_MISMATCH" in item for item in summary["safety"]["violations"])


def test_truncated_event_scan_fails_closed_instead_of_calling_day_complete():
    state = monitor_state()
    state["books"]["PAPER_SHADOW_V24"]["scan_truncated"] = True

    summary = summarize(state, now=NOW)

    assert summary["ok"] is False
    assert summary["diagnosis"] == "SAFETY_OR_EVIDENCE_VIOLATION"
    assert "PAPER_SHADOW_V24:EVENT_EVIDENCE_TRUNCATED" in summary["safety"]["violations"]
