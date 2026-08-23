import pytest

from daily_alpha.pine_forward_deployment_evidence import (
    FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA,
    PROJECTION_MINIMUM_COMMIT,
    parse_forward_parity_deployment_receipt,
)


def _event(account_id: str, version: str, signal_id: str) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": version,
        "model_id": account_id,
        "timeframe": "D",
        "price": 17.25,
        "bar_time": "2026-08-21T20:00:00+00:00",
        "entry_type": "NORMAL_BREAKOUT",
        "runner_stage": None,
        "disposition": "NO_TRADE",
        "reason": "PORTFOLIO_CONTEXT_REQUIRED",
        "paper_execution_triggered": False,
        "paper_ledger_updated": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _book(account_id: str, version: str) -> dict[str, object]:
    event = _event(account_id, version, f"{account_id}-EVENT-1")
    return {
        "event_count_visible": 1,
        "event_count_scanned": 1,
        "event_history_omitted": 0,
        "event_limit": 100,
        "scan_pages": 1,
        "scan_items_evaluated": 4,
        "events": [event],
        "open_count": 0,
        "armed_count_visible": 0,
        "scan_truncated": False,
    }


def _receipt() -> dict[str, object]:
    return {
        "schema": FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA,
        "repository": "shannonburgess/daily-alpha-engine1",
        "commit_sha": "c" * 40,
        "workflow_run_id": "32650000000",
        "workflow_run_attempt": "1",
        "projection_minimum_commit": PROJECTION_MINIMUM_COMMIT,
        "projection_ancestor_verified": True,
        "processor": {
            "function_name": "daily-alpha-pine-processor",
            "handler": "lambda_handlers.pine_processor.lambda_handler",
            "runtime": "python3.11",
            "version": "43",
            "code_sha256": "code-hash",
            "last_update_status": "Successful",
        },
        "books": {
            "PAPER_SHADOW_V24": _book("PAPER_SHADOW_V24", "2.4"),
            "PAPER_SHADOW_V25": _book("PAPER_SHADOW_V25", "2.5"),
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def test_parse_forward_deployment_receipt_binds_exact_staging_event_evidence() -> None:
    evidence = parse_forward_parity_deployment_receipt(_receipt())

    assert evidence.monitor_deployed is True
    assert evidence.commit_sha == "c" * 40
    assert evidence.processor_version == "43"
    assert evidence.sh24_event_count_visible == 1
    assert evidence.sh25_event_count_visible == 1
    assert evidence.sh24.event_count_scanned == 1
    assert evidence.sh24.event_history_omitted == 0
    assert evidence.sh24.events[0].signal_id == "PAPER_SHADOW_V24-EVENT-1"
    assert evidence.sh25.events[0].to_dict()["strategy_version"] == "2.5"
    assert evidence.trading_authorized is False
    assert evidence.live_trading_enabled is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema", "wrong", "schema is unsupported"),
        ("repository", "someone/else", "repository is not canonical"),
        ("projection_minimum_commit", "d" * 40, "projection lineage is not canonical"),
        ("projection_ancestor_verified", False, "projection ancestry is unverified"),
        ("trading_authorized", True, "trading_authorized must remain false"),
        ("live_trading_enabled", True, "live_trading_enabled must remain false"),
    ),
)
def test_parse_forward_deployment_receipt_fails_closed_on_top_level_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = _receipt()
    receipt[field] = value

    with pytest.raises(ValueError, match=message):
        parse_forward_parity_deployment_receipt(receipt)


def test_parse_forward_deployment_receipt_rejects_wrong_processor() -> None:
    receipt = _receipt()
    receipt["processor"]["handler"] = "wrong.handler"

    with pytest.raises(ValueError, match="processor handler is not canonical"):
        parse_forward_parity_deployment_receipt(receipt)


def test_parse_forward_deployment_receipt_rejects_cross_book_or_truncated_evidence() -> None:
    receipt = _receipt()
    receipt["books"]["PAPER_SHADOW_V25"]["scan_truncated"] = True

    with pytest.raises(ValueError, match="PAPER_SHADOW_V25 deployment evidence must be complete"):
        parse_forward_parity_deployment_receipt(receipt)

    receipt = _receipt()
    receipt["books"]["PAPER_DEFAULT"] = receipt["books"]["PAPER_SHADOW_V25"]
    with pytest.raises(ValueError, match="books are not exactly SH24 and SH25"):
        parse_forward_parity_deployment_receipt(receipt)


def test_parse_forward_deployment_receipt_rejects_omitted_history_or_count_drift() -> None:
    receipt = _receipt()
    book = receipt["books"]["PAPER_SHADOW_V24"]
    book["event_count_scanned"] = 2
    book["event_history_omitted"] = 1
    with pytest.raises(ValueError, match="omitted persisted event history"):
        parse_forward_parity_deployment_receipt(receipt)

    receipt = _receipt()
    receipt["books"]["PAPER_SHADOW_V24"]["event_count_scanned"] = 2
    with pytest.raises(ValueError, match="event scan counts do not reconcile"):
        parse_forward_parity_deployment_receipt(receipt)


def test_parse_forward_deployment_receipt_rejects_event_book_or_version_drift() -> None:
    receipt = _receipt()
    event = receipt["books"]["PAPER_SHADOW_V24"]["events"][0]
    event["model_id"] = "PAPER_SHADOW_V25"
    with pytest.raises(ValueError, match="crossed the requested model book"):
        parse_forward_parity_deployment_receipt(receipt)

    receipt = _receipt()
    receipt["books"]["PAPER_SHADOW_V24"]["events"][0]["strategy_version"] = "2.5"
    with pytest.raises(ValueError, match="strategy version crossed its book"):
        parse_forward_parity_deployment_receipt(receipt)


def test_parse_forward_deployment_receipt_rejects_event_authority_or_nondaily_timeframe() -> None:
    receipt = _receipt()
    receipt["books"]["PAPER_SHADOW_V25"]["events"][0]["live_trading_enabled"] = True
    with pytest.raises(ValueError, match="live_trading_enabled must remain false"):
        parse_forward_parity_deployment_receipt(receipt)

    receipt = _receipt()
    receipt["books"]["PAPER_SHADOW_V25"]["events"][0]["timeframe"] = "5"
    with pytest.raises(ValueError, match="timeframe is not canonical daily"):
        parse_forward_parity_deployment_receipt(receipt)
