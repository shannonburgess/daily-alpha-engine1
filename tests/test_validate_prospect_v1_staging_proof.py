from __future__ import annotations

import json

import pytest

from scripts.validate_prospect_v1_staging_proof import (
    ProspectV1StagingProofError,
    render_receipt,
    validate_result,
)


def _result(*, total=5, top=None, additional=2, ready=True, delivery=True):
    top = ["AAA", "BBB", "CCC"] if top is None else top
    return {
        "prospect_v1_runtime_enabled": True,
        "live_trading_enabled": False,
        "email_delivery": {"status": "SENT"},
        "prospect_initial_rollout": {
            "ready": ready,
            "delivery_contract_validated": delivery,
            "reasons": [],
            "board_id": "board-123",
            "total_qualifying": total,
            "top_pick_symbols": top,
            "additional_qualifying_count": additional,
            "filtered_count": 7,
            "verified_channels": ["NEWSLETTER", "DASHBOARD", "API"],
            "trading_authorized": False,
            "live_trading_enabled": False,
        },
    }


def test_validate_result_accepts_top3_plus_complete_board_delivery_proof():
    proof = validate_result(_result())

    assert proof["total_qualifying"] == 5
    assert proof["top_pick_symbols"] == ["AAA", "BBB", "CCC"]
    assert proof["additional_qualifying_count"] == 2
    assert proof["verified_channels"] == ["API", "DASHBOARD", "NEWSLETTER"]
    assert proof["newsletter_delivery_status"] == "SENT"
    assert proof["trading_authorized"] is False
    assert proof["live_trading_enabled"] is False


def test_validate_result_accepts_fewer_than_three_without_weakening_standard():
    proof = validate_result(_result(total=2, top=["AAA", "BBB"], additional=0))

    assert proof["top_pick_symbols"] == ["AAA", "BBB"]
    assert proof["additional_qualifying_count"] == 0


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value: value.update(prospect_v1_runtime_enabled=False), "PROSPECT_V1_RUNTIME_NOT_ENABLED"),
        (
            lambda value: value["prospect_initial_rollout"].update(ready=False),
            "PROSPECT_INITIAL_ROLLOUT_NOT_READY",
        ),
        (
            lambda value: value["prospect_initial_rollout"].update(delivery_contract_validated=False),
            "NEWSLETTER_DELIVERY_NOT_VALIDATED",
        ),
        (
            lambda value: value["prospect_initial_rollout"].update(additional_qualifying_count=1),
            "ADDITIONAL_QUALIFYING_COUNT_MISMATCH",
        ),
        (
            lambda value: value["prospect_initial_rollout"].update(
                verified_channels=["NEWSLETTER", "API"]
            ),
            "REQUIRED_PROSPECT_CHANNELS_NOT_VERIFIED",
        ),
        (lambda value: value["email_delivery"].update(status="DISABLED"), "NEWSLETTER_EMAIL_NOT_SENT"),
        (
            lambda value: value["prospect_initial_rollout"].update(trading_authorized=True),
            "PROSPECT_TRADING_AUTHORITY_INVALID",
        ),
    ],
)
def test_validate_result_fails_closed_when_launch_proof_is_incomplete(mutate, code):
    result = _result()
    mutate(result)

    with pytest.raises(ProspectV1StagingProofError, match=code):
        validate_result(result)


def test_render_receipt_requires_exact_environment_restoration(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(_result()), encoding="utf-8")

    with pytest.raises(
        ProspectV1StagingProofError,
        match="REPORT_LAMBDA_ENVIRONMENT_NOT_RESTORED",
    ):
        render_receipt(
            result_path=result_path,
            output_json=tmp_path / "receipt.json",
            output_markdown=tmp_path / "receipt.md",
            commit="abc123",
            run_id="456",
            environment_restored=False,
        )


def test_render_receipt_is_sanitized_and_records_restoration(tmp_path):
    result = _result()
    result["email_delivery"]["recipient"] = "private@example.com"
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    json_path = tmp_path / "receipt.json"
    markdown_path = tmp_path / "receipt.md"

    receipt = render_receipt(
        result_path=result_path,
        output_json=json_path,
        output_markdown=markdown_path,
        commit="abc123",
        run_id="456",
        environment_restored=True,
    )

    assert receipt["report_lambda_environment_restored"] is True
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False
    assert "private@example.com" not in json_path.read_text(encoding="utf-8")
    assert "private@example.com" not in markdown_path.read_text(encoding="utf-8")
