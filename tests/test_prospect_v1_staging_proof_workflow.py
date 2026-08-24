# ruff: noqa: I001

from pathlib import Path


WORKFLOW = Path(".github/workflows/prove-prospect-v1-staging.yml")


def test_prospect_staging_proof_is_manual_only_and_staging_scoped():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "push:" not in text
    assert "schedule:" not in text
    assert "environment: staging" in text
    assert "daily-alpha-report" in text
    assert "DailyAlphaGitHubStagingDeployRole" in text
    assert "production" not in text.lower()


def test_proof_temporarily_enables_runtime_and_always_restores_exact_environment():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "DAILY_ALPHA_PROSPECT_V1_RUNTIME_ENABLED" in text
    assert "PROSPECT_RUNTIME_ALREADY_ENABLED_BEFORE_PROOF" in text
    assert text.count("if: always()") >= 2
    assert "/tmp/original-environment.json" in text
    assert "REPORT_LAMBDA_ENVIRONMENT_RESTORE_MISMATCH" in text
    assert "--environment-restored" in text


def test_proof_requires_real_report_delivery_and_publishes_only_sanitized_receipt():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "PUBLISH_STAGING_REPORT" in text
    assert "'session': 'MANUAL'" in text
    assert "'session': 'PROSPECT_V1_PROOF'" not in text
    assert "prospect-v1-proof-${{ github.run_id }}-${{ github.run_attempt }}" in text
    assert "'error_code': result.get('error_code')" in text
    assert "validate_prospect_v1_staging_proof.py" in text
    assert "prospect-v1-staging-proof.md" in text
    assert "gh issue comment 337" in text
    assert "cat /tmp/prospect-v1-result.json" not in text
    assert "cat /tmp/original-vars.json" not in text
    assert "cat /tmp/restored-vars.json" not in text
