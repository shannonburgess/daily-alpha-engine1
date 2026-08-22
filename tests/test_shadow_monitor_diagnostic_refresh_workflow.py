from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT / ".github/workflows/refresh-paper-shadow-monitor-after-source-diagnostic.yml"
)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text()


def test_source_diagnostic_completion_refreshes_canonical_monitor() -> None:
    workflow = _workflow_text()

    assert "workflow_run:" in workflow
    assert "- Diagnose SH24 source-side signal coverage" in workflow
    assert "- completed" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "gh workflow run monitor-paper-shadows.yml" in workflow
    assert '--repo "${REPO}"' in workflow
    assert "--ref main" in workflow


def test_diagnostic_refresh_has_no_aws_or_execution_authority() -> None:
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
