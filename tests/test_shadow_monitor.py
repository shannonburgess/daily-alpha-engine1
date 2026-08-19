from __future__ import annotations

import json
from datetime import UTC, datetime

from scripts.shadow_monitor import render_markdown, summarize

NOW = datetime(2026, 8, 19, 20, 30, tzinfo=UTC)


def positions(*, v24=None, v25=None):
    return {
        "ok": True,
        "books": {
            "PAPER_SHADOW_V24": {
                "open_count": len(v24 or []),
                "open_positions": v24 or [],
            },
            "PAPER_SHADOW_V25": {
                "open_count": len(v25 or []),
                "open_positions": v25 or [],
            },
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def scan_event(
    account: str,
    *,
    signal_id="sig-1",
    disposition="NO_TRADE",
    reason="PORTFOLIO_RISK_REJECTED",
    execution=None,
):
    ingress = {
        "signal_id": signal_id,
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "model_id": account,
        "forward_test_start": "2026-08-19",
        "replay_max_price": 230.0,
        "received_at": "2026-08-19T19:55:00+00:00",
    }
    result = {
        "signal_id": signal_id,
        "disposition": "HELD_FOR_CONTEXT",
        "reason": "ENTRY_REQUIRES_PORTFOLIO_RISK_ORATS_CONTEXT",
        "received_at": ingress["received_at"],
    }
    item = {
        "signal_id": {"S": signal_id},
        "symbol": {"S": "AAPL"},
        "action": {"S": "ENTRY_LONG"},
        "disposition": {"S": disposition},
        "reason": {"S": reason},
        "ingress_json": {"S": json.dumps(ingress)},
        "result_json": {"S": json.dumps(result)},
    }
    if execution is not None:
        item["execution_json"] = {"S": json.dumps(execution)}
    return {"Items": [item]}


def test_no_event_day_is_explicit_not_assumed_trade_rejection():
    summary = summarize(
        positions(),
        {"PAPER_SHADOW_V24": {"Items": []}, "PAPER_SHADOW_V25": {"Items": []}},
        now=NOW,
    )

    assert summary["diagnosis"] == "NO_STRATEGY_EVENT_RECEIVED"
    assert summary["total_session_events"] == 0
    assert summary["total_session_fills"] == 0
    assert summary["safety"]["violations"] == []
    assert "No SH24/SH25 strategy-origin event" in render_markdown(summary)


def test_strategy_event_without_fill_surfaces_exact_reason():
    summary = summarize(
        positions(),
        {
            "PAPER_SHADOW_V24": scan_event("PAPER_SHADOW_V24"),
            "PAPER_SHADOW_V25": {"Items": []},
        },
        now=NOW,
    )

    assert summary["diagnosis"] == "STRATEGY_EVENTS_RECEIVED_NO_PAPER_FILL"
    assert summary["accounts"]["PAPER_SHADOW_V24"]["reason_counts"] == {
        "PORTFOLIO_RISK_REJECTED": 1
    }
    assert summary["blocker_counts"] == {"PORTFOLIO_RISK_REJECTED": 1}


def test_executed_paper_receipt_is_counted_and_rendered():
    execution = {
        "disposition": "EXECUTED_PAPER",
        "reason": "PAPER_ENTRY_EXECUTED",
        "paper_account_id": "PAPER_SHADOW_V25",
        "trading_authorized": False,
        "live_trading_enabled": False,
        "execution_receipt": {
            "account_id": "PAPER_SHADOW_V25",
            "symbol": "AAPL",
            "action": "ENTRY_LONG",
            "quantity": 10,
            "fill_price": 100.25,
        },
    }
    summary = summarize(
        positions(v25=[{"symbol": "AAPL", "instrument": "STOCK"}]),
        {
            "PAPER_SHADOW_V24": {"Items": []},
            "PAPER_SHADOW_V25": scan_event(
                "PAPER_SHADOW_V25",
                disposition="EXECUTED_PAPER",
                reason="PAPER_ENTRY_EXECUTED",
                execution=execution,
            ),
        },
        now=NOW,
    )

    assert summary["diagnosis"] == "TRADES_RECORDED"
    assert summary["total_session_fills"] == 1
    assert summary["accounts"]["PAPER_SHADOW_V25"]["open_count"] == 1
    rendered = render_markdown(summary)
    assert "`AAPL` ENTRY_LONG: qty=10, fill=100.25" in rendered


def test_cross_account_receipt_fails_safety_and_isolation_check():
    execution = {
        "disposition": "EXECUTED_PAPER",
        "reason": "PAPER_ENTRY_EXECUTED",
        "paper_account_id": "PAPER_SHADOW_V25",
        "trading_authorized": False,
        "live_trading_enabled": False,
        "execution_receipt": {
            "account_id": "PAPER_SHADOW_V25",
            "symbol": "AAPL",
            "action": "ENTRY_LONG",
            "quantity": 1,
            "fill_price": 100.0,
        },
    }
    summary = summarize(
        positions(),
        {
            "PAPER_SHADOW_V24": scan_event(
                "PAPER_SHADOW_V24",
                disposition="EXECUTED_PAPER",
                reason="PAPER_ENTRY_EXECUTED",
                execution=execution,
            ),
            "PAPER_SHADOW_V25": {"Items": []},
        },
        now=NOW,
    )

    assert summary["ok"] is False
    assert summary["diagnosis"] == "SAFETY_OR_ISOLATION_VIOLATION"
    assert any("ACCOUNT_MISMATCH" in item for item in summary["safety"]["violations"])
