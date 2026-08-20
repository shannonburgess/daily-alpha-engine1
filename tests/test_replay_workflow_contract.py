from pathlib import Path


WORKFLOW = Path(".github/workflows/replay-paper-armed-signals.yml")


def test_replay_workflow_is_staging_paper_only_and_session_gated():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "40 13-20 * * 1-5"' in text
    assert "core_session_for" in text
    assert 'session.session_phase == "REGULAR_SESSION"' in text
    assert "environment: staging" in text
    assert "daily-alpha-pine-processor" in text
    assert '\"operation\":\"REPLAY_ARMED_SIGNALS\"' in text
    assert '\"operation\":\"GET_SHADOW_MONITOR_STATE\"' in text
    assert "daily-alpha-paper-armed-replay-staging" in text
    assert "Trading authorized: false" in text
    assert "Live trading enabled: false" in text
    assert "aws lambda update-function" not in text
    assert "aws events put-" not in text
    assert "aws scheduler create-" not in text


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
