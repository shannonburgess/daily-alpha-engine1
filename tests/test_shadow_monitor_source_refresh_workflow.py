from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/refresh-paper-shadow-monitor-on-source-change.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text()


def test_source_refresh_targets_trusted_main_and_canonical_monitor() -> None:
    workflow = _workflow_text()

    assert "push:" in workflow
    assert "- main" in workflow
    assert "gh workflow run monitor-paper-shadows.yml" in workflow
    assert '--repo "${REPO}"' in workflow
    assert "--ref main" in workflow


def test_source_refresh_covers_monitor_critical_paths() -> None:
    workflow = _workflow_text()
    expected_paths = (
        ".github/workflows/monitor-paper-shadows.yml",
        ".github/workflows/refresh-paper-shadow-monitor-on-source-change.yml",
        ".github/workflows/replay-paper-armed-signals.yml",
        "scripts/shadow_monitor.py",
        "scripts/shadow_contract_monitor.py",
        "scripts/shadow_replay_scheduler_monitor.py",
        "scripts/shadow_transport_monitor.py",
        "scripts/shadow_universe_monitor.py",
        "scripts/shadow_liquidity_monitor.py",
        "scripts/shadow_source_diagnostic_monitor.py",
        "scripts/nyse_session_calendar.py",
    )

    for path in expected_paths:
        assert f'"{path}"' in workflow


def test_source_refresh_has_no_aws_secret_or_execution_authority() -> None:
    workflow = _workflow_text().lower()

    assert "actions: write" in workflow
    assert "contents: read" in workflow
    assert "id-token: write" not in workflow
    assert "secrets." not in workflow
    assert "aws-actions/" not in workflow
    assert "aws lambda" not in workflow
    assert "trading_authorized=true" not in workflow
    assert "live_trading_enabled=true" not in workflow
    assert "production" not in workflow
