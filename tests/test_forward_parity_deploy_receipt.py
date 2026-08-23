import pytest

from scripts.render_forward_parity_deploy_receipt import (
    PROJECTION_MINIMUM_COMMIT,
    RECEIPT_SCHEMA,
    ReceiptError,
    build_receipt,
    render_markdown,
)


def _event() -> dict[str, object]:
    return {
        "signal_id": "DINO-ENTRY-20260821",
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.5",
        "model_id": "PAPER_SHADOW_V25",
        "timeframe": "D",
        "price": 17.25,
        "bar_time": "2026-08-21T20:00:00+00:00",
        "entry_type": "NORMAL_BREAKOUT",
        "breakout_level": 17.10,
        "armed_age": None,
        "received_at": "2026-08-21T20:00:02+00:00",
        "disposition": "NO_TRADE",
        "reason": "SECTOR_DATA_UNVERIFIED",
        "paper_execution_triggered": False,
        "paper_ledger_updated": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
        "webhook_secret": "must-never-leave-monitor",
        "ingress_json": "raw-ingress-must-never-leave-monitor",
    }


def _monitor() -> dict[str, object]:
    return {
        "ok": True,
        "service": "daily-alpha-pine-processor",
        "operation": "GET_SHADOW_MONITOR_STATE",
        "books": {
            "PAPER_SHADOW_V24": {
                "events": [],
                "event_count_visible": 0,
                "scan_truncated": False,
                "open_count": 0,
                "open_positions": [],
                "armed_count_visible": 0,
                "armed_signals": [],
            },
            "PAPER_SHADOW_V25": {
                "events": [],
                "event_count_visible": 0,
                "scan_truncated": False,
                "open_count": 0,
                "open_positions": [],
                "armed_count_visible": 0,
                "armed_signals": [],
            },
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _config() -> dict[str, object]:
    return {
        "FunctionName": "daily-alpha-pine-processor",
        "Handler": "lambda_handlers.pine_processor.lambda_handler",
        "Runtime": "python3.11",
        "Version": "42",
        "CodeSha256": "base64-code-hash",
        "LastUpdateStatus": "Successful",
    }


def _receipt(monitor: dict[str, object] | None = None) -> dict[str, object]:
    return build_receipt(
        monitor or _monitor(),
        _config(),
        commit_sha="a" * 40,
        run_id="32650000000",
        run_attempt="1",
        repository="shannonburgess/daily-alpha-engine1",
        projection_ancestor_verified=True,
    )


def test_receipt_binds_deployed_commit_processor_and_book_safety() -> None:
    receipt = _receipt()

    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["projection_minimum_commit"] == PROJECTION_MINIMUM_COMMIT
    assert receipt["projection_ancestor_verified"] is True
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False
    assert receipt["processor"]["code_sha256"] == "base64-code-hash"
    assert set(receipt["books"]) == {"PAPER_SHADOW_V24", "PAPER_SHADOW_V25"}


def test_receipt_includes_only_sanitized_persisted_event_projection() -> None:
    monitor = _monitor()
    monitor["books"]["PAPER_SHADOW_V25"]["events"] = [_event()]
    monitor["books"]["PAPER_SHADOW_V25"]["event_count_visible"] = 1

    receipt = _receipt(monitor)
    event = receipt["books"]["PAPER_SHADOW_V25"]["events"][0]

    assert event["signal_id"] == "DINO-ENTRY-20260821"
    assert event["model_id"] == "PAPER_SHADOW_V25"
    assert event["strategy_version"] == "2.5"
    assert event["bar_time"] == "2026-08-21T20:00:00+00:00"
    assert event["disposition"] == "NO_TRADE"
    assert event["reason"] == "SECTOR_DATA_UNVERIFIED"
    assert event["paper_execution_triggered"] is False
    assert event["trading_authorized"] is False
    assert event["live_trading_enabled"] is False
    assert "webhook_secret" not in event
    assert "ingress_json" not in event


def test_receipt_refuses_unverified_projection_ancestry() -> None:
    with pytest.raises(ReceiptError, match="ancestry was not verified"):
        build_receipt(
            _monitor(),
            _config(),
            commit_sha="a" * 40,
            run_id="1",
            run_attempt="1",
            repository="shannonburgess/daily-alpha-engine1",
            projection_ancestor_verified=False,
        )


def test_receipt_fails_closed_on_truncated_book_evidence() -> None:
    monitor = _monitor()
    monitor["books"]["PAPER_SHADOW_V24"]["scan_truncated"] = True

    with pytest.raises(ReceiptError, match="event scan is truncated"):
        build_receipt(
            monitor,
            _config(),
            commit_sha="a" * 40,
            run_id="1",
            run_attempt="1",
            repository="shannonburgess/daily-alpha-engine1",
            projection_ancestor_verified=True,
        )


def test_receipt_fails_closed_if_live_authority_is_present() -> None:
    monitor = _monitor()
    monitor["live_trading_enabled"] = True

    with pytest.raises(ReceiptError, match="live_trading_enabled must remain false"):
        build_receipt(
            monitor,
            _config(),
            commit_sha="a" * 40,
            run_id="1",
            run_attempt="1",
            repository="shannonburgess/daily-alpha-engine1",
            projection_ancestor_verified=True,
        )


def test_receipt_fails_closed_if_event_claims_live_authority() -> None:
    monitor = _monitor()
    unsafe = _event()
    unsafe["live_trading_enabled"] = True
    monitor["books"]["PAPER_SHADOW_V25"]["events"] = [unsafe]
    monitor["books"]["PAPER_SHADOW_V25"]["event_count_visible"] = 1

    with pytest.raises(ReceiptError, match="event live_trading_enabled must remain false"):
        _receipt(monitor)


def test_markdown_contains_machine_readable_sanitized_receipt() -> None:
    monitor = _monitor()
    monitor["books"]["PAPER_SHADOW_V25"]["events"] = [_event()]
    monitor["books"]["PAPER_SHADOW_V25"]["event_count_visible"] = 1
    markdown = render_markdown(_receipt(monitor))

    assert f"<!-- {RECEIPT_SCHEMA} -->" in markdown
    assert "base64-code-hash" in markdown
    assert "DINO-ENTRY-20260821" in markdown
    assert "webhook_secret" not in markdown
    assert "raw-ingress-must-never-leave-monitor" not in markdown
    assert "does not prove signal parity or authorize trading" in markdown
