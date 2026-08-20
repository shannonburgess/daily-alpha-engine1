from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.shadow_replay_scheduler_monitor import (
    evaluate_replay_scheduler,
    render_markdown,
)


def _run(
    created: datetime,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    event: str = "schedule",
    run_id: int = 123,
) -> dict:
    updated = created + timedelta(minutes=5)
    return {
        "databaseId": run_id,
        "status": status,
        "conclusion": conclusion,
        "createdAt": created.isoformat(),
        "updatedAt": updated.isoformat(),
        "event": event,
    }


def test_premarket_without_runs_is_not_due() -> None:
    now = datetime(2026, 8, 20, 13, 17, tzinfo=UTC)  # 09:17 ET
    result = evaluate_replay_scheduler([], now=now)

    assert result.ok is True
    assert result.status == "NOT_DUE"
    assert result.diagnosis == "REPLAY_NOT_DUE_PREMARKET"
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_regular_session_recent_scheduled_success_passes() -> None:
    now = datetime(2026, 8, 20, 14, 17, tzinfo=UTC)  # 10:17 ET
    result = evaluate_replay_scheduler(
        [_run(datetime(2026, 8, 20, 13, 40, tzinfo=UTC))],
        now=now,
    )

    assert result.ok is True
    assert result.status == "PASS"
    assert result.diagnosis == "REPLAY_SCHEDULER_HEALTHY"
    assert result.latest_run_id == "123"
    assert "frozen" in render_markdown(result)


def test_manual_dispatch_cannot_mask_missing_schedule() -> None:
    now = datetime(2026, 8, 20, 14, 17, tzinfo=UTC)
    result = evaluate_replay_scheduler(
        [_run(datetime(2026, 8, 20, 14, 0, tzinfo=UTC), event="workflow_dispatch")],
        now=now,
    )

    assert result.ok is False
    assert result.diagnosis == "REPLAY_SCHEDULER_MISSING"


def test_malformed_created_timestamp_cannot_mask_missing_schedule() -> None:
    now = datetime(2026, 8, 20, 14, 17, tzinfo=UTC)
    malformed = {
        "databaseId": 999,
        "status": "completed",
        "conclusion": "success",
        "createdAt": "not-a-timestamp",
        "updatedAt": datetime(2026, 8, 20, 14, 10, tzinfo=UTC).isoformat(),
        "event": "schedule",
    }

    result = evaluate_replay_scheduler([malformed], now=now)

    assert result.ok is False
    assert result.diagnosis == "REPLAY_SCHEDULER_MISSING"


def test_regular_session_stale_success_fails_closed() -> None:
    now = datetime(2026, 8, 20, 15, 17, tzinfo=UTC)  # 11:17 ET
    result = evaluate_replay_scheduler(
        [_run(datetime(2026, 8, 20, 13, 40, tzinfo=UTC))],
        now=now,
    )

    assert result.ok is False
    assert result.status == "FAIL"
    assert result.diagnosis == "REPLAY_SCHEDULER_STALE"


def test_recent_pending_schedule_is_allowed() -> None:
    now = datetime(2026, 8, 20, 14, 17, tzinfo=UTC)
    result = evaluate_replay_scheduler(
        [
            _run(
                datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
                status="in_progress",
                conclusion=None,
            )
        ],
        now=now,
    )

    assert result.ok is True
    assert result.status == "PENDING"
    assert result.diagnosis == "REPLAY_SCHEDULER_PENDING"


def test_completed_failure_fails_closed() -> None:
    now = datetime(2026, 8, 20, 14, 17, tzinfo=UTC)
    result = evaluate_replay_scheduler(
        [
            _run(
                datetime(2026, 8, 20, 13, 40, tzinfo=UTC),
                conclusion="failure",
            )
        ],
        now=now,
    )

    assert result.ok is False
    assert result.diagnosis == "REPLAY_SCHEDULER_COMPLETED_NON_SUCCESS"


def test_post_session_requires_final_tick_near_close() -> None:
    now = datetime(2026, 8, 20, 20, 17, tzinfo=UTC)  # 16:17 ET
    healthy = evaluate_replay_scheduler(
        [_run(datetime(2026, 8, 20, 19, 40, tzinfo=UTC))],
        now=now,
    )
    missed = evaluate_replay_scheduler(
        [_run(datetime(2026, 8, 20, 18, 40, tzinfo=UTC))],
        now=now,
    )

    assert healthy.ok is True
    assert healthy.diagnosis == "REPLAY_FINAL_TICK_HEALTHY"
    assert missed.ok is False
    assert missed.diagnosis == "REPLAY_FINAL_TICK_MISSING"


def test_early_close_uses_official_close_window() -> None:
    now = datetime(2026, 11, 27, 18, 17, tzinfo=UTC)  # 13:17 ET, 13:00 close
    result = evaluate_replay_scheduler(
        [_run(datetime(2026, 11, 27, 17, 40, tzinfo=UTC))],  # 12:40 ET
        now=now,
    )

    assert result.ok is True
    assert result.diagnosis == "REPLAY_FINAL_TICK_HEALTHY"


def test_non_trading_day_is_not_due() -> None:
    now = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)
    result = evaluate_replay_scheduler([], now=now)

    assert result.ok is True
    assert result.diagnosis == "REPLAY_NOT_DUE_NON_TRADING_DAY"


def test_calendar_outside_coverage_fails_closed() -> None:
    now = datetime(2029, 8, 20, 15, 0, tzinfo=UTC)
    result = evaluate_replay_scheduler([], now=now)

    assert result.ok is False
    assert result.diagnosis == "REPLAY_CALENDAR_UNVERIFIED"


def test_naive_now_is_rejected() -> None:
    naive = datetime(2026, 8, 20, 14, 17, tzinfo=UTC).replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_replay_scheduler([], now=naive)


def test_exact_direct_cli_invocation_works(tmp_path: Path) -> None:
    runs = tmp_path / "runs.json"
    output_json = tmp_path / "status.json"
    output_md = tmp_path / "status.md"
    runs.write_text("[]\n")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/shadow_replay_scheduler_monitor.py",
            "--runs-json",
            str(runs),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # Runtime date determines PASS/NOT_DUE/FAIL, but direct execution/import must work
    # and always emit a structured safety-bounded result.
    assert completed.returncode in {0, 2}, completed.stderr
    payload = json.loads(output_json.read_text())
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False
    assert "PAPER ARMED replay scheduler health" in output_md.read_text()
