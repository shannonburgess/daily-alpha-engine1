from __future__ import annotations

import json
from pathlib import Path


WORKFLOW = Path(".github/workflows/prove-fred-initial-release-staging.yml")
POLICY = Path("infra/aws/staging/data-feed-ingestion-github-deploy-policy.json")


def test_fred_staging_proof_is_manual_main_locked_and_staging_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "push:" not in text
    assert 'test "$GITHUB_REF_NAME" = "main"' in text
    assert 'git rev-parse origin/main' in text
    assert "environment: staging" in text
    assert "daily-alpha-staging-data-feed-ingestion" in text
    assert "cloudformation deploy" not in text
    assert "aws cloudformation deploy" not in text


def test_fred_staging_proof_requires_explicit_confirmation_and_bounded_dates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Type PROVE_FRED" in text
    assert "FRED_PROOF_CONFIRMATION_REQUIRED" in text
    assert "FRED_PROOF_DATE_RANGE_TOO_LARGE" in text
    assert "FRED_PROOF_END_DATE_IN_FUTURE" in text
    assert "HISTORICAL_BACKFILL" in text
    assert "31" in text


def test_fred_staging_proof_smokes_deployed_contract_before_provider_call() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    smoke = "Require deployed FRED initial-release capability before provider call"
    capture = "Capture real FRED initial-release staging evidence"
    assert smoke in text
    assert capture in text
    assert text.index(smoke) < text.index(capture)
    assert "fred_historical_output_type" in text
    assert "historical_backfill_supported" in text
    assert "CAPTURED_AT_ONLY" in text


def test_fred_staging_proof_rehydrates_exact_s3_objects_through_pit_parser() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "aws', 's3', 'cp'" in text
    assert "'/fred/raw/'" in text
    assert "'/receipts/'" in text
    assert "parse_fred_initial_release_history" in text
    assert "FRED_OUTPUT_TYPE_4_INITIAL_RELEASE_V1" in text
    assert "DAILY_ALPHA_FRED_INITIAL_RELEASE_STAGING_PROOF_V1" in text
    assert "function_code_sha256" in text
    assert "repo_commit" in text
    assert "actions/upload-artifact@v4" in text


def test_fred_staging_proof_preserves_no_action_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "predictive_alpha_claimed': False" in text
    assert "promotion_authorized': False" in text
    assert "paper_mutation_authorized': False" in text
    assert "trading_authorized': False" in text
    assert "live_trading_enabled': False" in text
    assert "does **not** prove predictive alpha" in text


def test_github_role_can_read_only_exact_staging_fred_evidence_prefix() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    statements = {item["Sid"]: item for item in policy["Statement"]}
    proof_read = statements["ReadOnlyCapturedFredProofEvidence"]

    assert proof_read["Effect"] == "Allow"
    assert proof_read["Action"] == "s3:GetObject"
    assert proof_read["Resource"] == (
        "arn:aws:s3:::daily-alpha-staging-raw-490809405132-us-east-2/"
        "data-feeds/staging/fred/*"
    )
    assert all(
        action != "s3:ListBucket"
        for statement in policy["Statement"]
        for action in (
            statement["Action"]
            if isinstance(statement["Action"], list)
            else [statement["Action"]]
        )
    )
