import pytest

from daily_alpha.pine_forward_deployment_evidence import (
    FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA,
    PROJECTION_MINIMUM_COMMIT,
    parse_forward_parity_deployment_receipt,
)


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
            "PAPER_SHADOW_V24": {
                "event_count_visible": 2,
                "open_count": 0,
                "armed_count_visible": 0,
                "scan_truncated": False,
            },
            "PAPER_SHADOW_V25": {
                "event_count_visible": 2,
                "open_count": 0,
                "armed_count_visible": 0,
                "scan_truncated": False,
            },
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def test_parse_forward_deployment_receipt_binds_exact_staging_evidence() -> None:
    evidence = parse_forward_parity_deployment_receipt(_receipt())

    assert evidence.monitor_deployed is True
    assert evidence.commit_sha == "c" * 40
    assert evidence.processor_version == "43"
    assert evidence.sh24_event_count_visible == 2
    assert evidence.sh25_event_count_visible == 2
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
