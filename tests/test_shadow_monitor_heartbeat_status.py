from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.shadow_monitor_heartbeat_status import evaluate_heartbeat, render_markdown

NOW = datetime(2026, 8, 20, 12, 57, tzinfo=UTC)


def _run(
    *,
    age_minutes: int,
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict:
    timestamp = NOW - timedelta(minutes=age_minutes)
    return {
        "databaseId": 12345,
        "status": status,
        "conclusion": conclusion,
        "createdAt": timestamp.isoformat(),
        "updatedAt": timestamp.isoformat(),
        "headSha": "abc123",
    }


def test_fresh_success_does_not_replace_current_monitor_status() -> None:
    status = evaluate_heartbeat([_run(age_minutes=40)], now=NOW)

    assert status.ok is True
    assert status.diagnosis == "MONITOR_HEARTBEAT_HEALTHY"
    assert status.needs_issue_update is False
    assert status.current_shadow_state_verified is False


def test_previous_hour_success_becomes_stale_when_current_run_never_started() -> None:
    status = evaluate_heartbeat([_run(age_minutes=100)], now=NOW)

    assert status.ok is False
    assert status.diagnosis == "MONITOR_HEARTBEAT_STALE"
    assert status.needs_issue_update is True
    markdown = render_markdown(status)
    assert "Prior green state reused:** False" in markdown
    assert "Do **not** interpret an older green monitor result" in markdown


def test_recent_pending_run_is_not_declared_failed() -> None:
    status = evaluate_heartbeat(
        [_run(age_minutes=40, status="in_progress", conclusion=None)],
        now=NOW,
    )

    assert status.diagnosis == "MONITOR_HEARTBEAT_PENDING"
    assert status.needs_issue_update is False


def test_stuck_pending_run_replaces_stale_green_status() -> None:
    status = evaluate_heartbeat(
        [_run(age_minutes=70, status="queued", conclusion=None)],
        now=NOW,
    )

    assert status.diagnosis == "MONITOR_RUN_STUCK"
    assert status.needs_issue_update is True


def test_no_run_is_fail_closed() -> None:
    status = evaluate_heartbeat([], now=NOW)

    assert status.diagnosis == "MONITOR_HEARTBEAT_MISSING"
    assert status.needs_issue_update is True
    assert status.latest_run_id is None


def test_completed_failure_is_owned_by_primary_failure_receipt() -> None:
    status = evaluate_heartbeat(
        [_run(age_minutes=10, status="completed", conclusion="failure")],
        now=NOW,
    )

    assert status.diagnosis == "MONITOR_COMPLETED_NON_SUCCESS"
    assert status.needs_issue_update is False
    assert "failure receipt" in status.reason


def test_unknown_run_state_fails_closed() -> None:
    status = evaluate_heartbeat(
        [_run(age_minutes=10, status="mystery", conclusion=None)],
        now=NOW,
    )

    assert status.diagnosis == "MONITOR_HEARTBEAT_UNKNOWN_RUN_STATE"
    assert status.needs_issue_update is True


def test_naive_now_is_rejected() -> None:
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_heartbeat([], now=naive)
