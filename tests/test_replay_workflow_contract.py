import pathlib

WORKFLOW = pathlib.Path(".github/workflows/replay-paper-armed-signals.yml")


def test_replay_workflow_is_staging_paper_only_and_session_gated():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "40 13-20 * * 1-5"' in text
    assert "core_session_for" in text
    assert 'session.session_phase == "REGULAR_SESSION"' in text
    assert "environment: staging" in text
    assert "daily-alpha-pine-processor" in text
    assert '\"operation\":\"REPLAY_ARMED_SIGNALS\"' in text
    assert '\"operation\":\"GET_SHADOW_MONITOR_STATE\"' in text
    assert '\"armed_limit\":100' in text
    assert "daily-alpha-paper-armed-replay-staging" in text
    assert "NO_ARMED_SIGNALS" in text
    assert "RETRY_PENDING_NEXT_SCHEDULE" in text
    assert "armed_claimed" in text
    assert "lease_conflicts" in text
    assert "outcome_counts" in text
    assert "account_results" in text
    assert "Trading authorized: false" in text
    assert "Live trading enabled: false" in text
    assert "aws lambda update-function" not in text
    assert "aws events put-" not in text
    assert "aws scheduler create-" not in text


def test_replay_workflow_reconciles_every_claim_with_an_outcome_or_lease_conflict():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert ".armed_found == (.armed_claimed + .lease_conflicts)" in text
    assert "([.outcome_counts[]] | add // 0) == .armed_claimed" in text
    assert "((.outcomes | length) == .armed_claimed)" in text
    assert "Retryable ARMED outcomes" in text
    assert "Outcome counts" in text


def test_replay_workflow_never_reads_or_prints_secret_values():
    text = WORKFLOW.read_text(encoding="utf-8")

    forbidden = (
        "secretsmanager get-secret-value",
        "ORATS_TOKEN",
        "webhook_secret",
        "live_trading_enabled: true",
        "trading_authorized: true",
    )
    for value in forbidden:
        assert value not in text
