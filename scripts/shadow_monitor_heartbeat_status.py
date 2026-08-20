"""Evaluate whether the canonical PAPER-shadow monitor is actually running on schedule.

The primary monitor can only diagnose AWS state after GitHub starts it. This watchdog
closes the remaining gap where a missed scheduler invocation could leave an older
green issue comment looking current. It never talks to AWS or TradingView.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FRESH_SUCCESS_SECONDS = 95 * 60
MAX_PENDING_SECONDS = 60 * 60
PENDING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


@dataclass(frozen=True)
class HeartbeatStatus:
    ok: bool
    diagnosis: str
    needs_issue_update: bool
    current_shadow_state_verified: bool
    prior_state_reused: bool
    latest_run_id: str | None
    latest_run_status: str | None
    latest_run_conclusion: str | None
    latest_run_created_at: str | None
    latest_run_updated_at: str | None
    latest_run_head_sha: str | None
    age_seconds: float | None
    checked_at: str
    reason: str
    tradingview_configuration_frozen: bool = True
    tradingview_mutation_attempted: bool = False
    runtime_safety_state: str = "UNVERIFIED_BY_HEARTBEAT"


def evaluate_heartbeat(
    runs: list[dict[str, Any]],
    *,
    now: datetime,
) -> HeartbeatStatus:
    """Classify scheduler health without reusing an old AWS state snapshot."""
    _require_aware(now, "now")
    checked = now.astimezone(UTC)
    latest = _latest_run(runs)
    if latest is None:
        return _status(
            checked,
            diagnosis="MONITOR_HEARTBEAT_MISSING",
            needs_issue_update=True,
            reason="No canonical monitor workflow run is visible on main.",
        )

    created = _parse_aware(latest.get("createdAt"))
    updated = _parse_aware(latest.get("updatedAt"))
    run_status = str(latest.get("status") or "").strip().lower()
    conclusion = str(latest.get("conclusion") or "").strip().lower()

    reference = created if run_status in PENDING_STATUSES else (updated or created)
    if reference is None:
        return _status(
            checked,
            diagnosis="MONITOR_HEARTBEAT_INVALID_TIMESTAMP",
            needs_issue_update=True,
            latest=latest,
            reason="Latest canonical monitor run has no valid timezone-aware timestamp.",
        )

    age = (checked - reference).total_seconds()
    if age < -60:
        return _status(
            checked,
            diagnosis="MONITOR_HEARTBEAT_FUTURE_TIMESTAMP",
            needs_issue_update=True,
            latest=latest,
            age_seconds=age,
            reason="Latest canonical monitor timestamp is implausibly in the future.",
        )
    age = max(0.0, age)

    if run_status in PENDING_STATUSES:
        if age <= MAX_PENDING_SECONDS:
            return _status(
                checked,
                diagnosis="MONITOR_HEARTBEAT_PENDING",
                needs_issue_update=False,
                latest=latest,
                age_seconds=age,
                reason="Canonical monitor run is currently pending or in progress.",
            )
        return _status(
            checked,
            diagnosis="MONITOR_RUN_STUCK",
            needs_issue_update=True,
            latest=latest,
            age_seconds=age,
            reason="Canonical monitor run has remained pending/in progress beyond 60 minutes.",
        )

    if run_status == "completed" and conclusion == "success":
        if age <= FRESH_SUCCESS_SECONDS:
            return _status(
                checked,
                diagnosis="MONITOR_HEARTBEAT_HEALTHY",
                needs_issue_update=False,
                latest=latest,
                age_seconds=age,
                reason="Latest canonical monitor completed successfully within the freshness window.",
                ok=True,
            )
        return _status(
            checked,
            diagnosis="MONITOR_HEARTBEAT_STALE",
            needs_issue_update=True,
            latest=latest,
            age_seconds=age,
            reason="Latest successful canonical monitor run is older than 95 minutes.",
        )

    if run_status == "completed" and conclusion and conclusion != "success":
        return _status(
            checked,
            diagnosis="MONITOR_COMPLETED_NON_SUCCESS",
            needs_issue_update=False,
            latest=latest,
            age_seconds=age,
            reason=(
                "Latest monitor completed non-successfully; the workflow_run failure receipt "
                "owns the exact rolling issue status and heartbeat will not overwrite it."
            ),
        )

    return _status(
        checked,
        diagnosis="MONITOR_HEARTBEAT_UNKNOWN_RUN_STATE",
        needs_issue_update=True,
        latest=latest,
        age_seconds=age,
        reason="Latest canonical monitor run has an unrecognized status/conclusion pair.",
    )


def render_markdown(status: HeartbeatStatus) -> str:
    """Render the fail-closed rolling issue status for heartbeat-only failures."""
    age = "unknown" if status.age_seconds is None else f"{status.age_seconds:.1f}s"
    limitation = (
        "The scheduler heartbeat cannot prove current positions, ARMED state, receipts, "
        "zero-trade state, or AWS safety. Do **not** interpret an older green monitor result "
        "as current until the canonical monitor resumes and publishes fresh evidence."
    )
    run_state = (
        f"Latest run status/conclusion: `{status.latest_run_status or 'none'}` / "
        f"`{status.latest_run_conclusion or 'none'}`  "
    )
    lines = [
        "<!-- daily-alpha-shadow-monitor -->",
        "## Daily Alpha PAPER Shadow Monitor",
        "",
        f"**Diagnosis:** `{status.diagnosis}`  ",
        "**Current PAPER-shadow state verified:** False  ",
        "**Prior green state reused:** False  ",
        "**Current runtime safety state:** `UNVERIFIED_BY_HEARTBEAT`  ",
        "**TradingView configuration:** frozen; no mutation attempted",
        "",
        status.reason,
        "",
        limitation,
        "",
        "### Scheduler heartbeat evidence",
        f"Latest run ID: `{status.latest_run_id or 'none'}`  ",
        run_state,
        f"Latest run created: `{status.latest_run_created_at or 'none'}`  ",
        f"Latest run updated: `{status.latest_run_updated_at or 'none'}`  ",
        f"Latest run head SHA: `{status.latest_run_head_sha or 'none'}`  ",
        f"Heartbeat age: `{age}`  ",
        f"Checked at: `{status.checked_at}`",
        "",
    ]
    return "\n".join(lines)


def _latest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [run for run in runs if isinstance(run, dict)]
    if not candidates:
        return None

    def sort_key(run: dict[str, Any]) -> datetime:
        return (
            _parse_aware(run.get("createdAt"))
            or _parse_aware(run.get("updatedAt"))
            or datetime.min.replace(tzinfo=UTC)
        )

    return max(candidates, key=sort_key)


def _parse_aware(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _status(
    checked: datetime,
    *,
    diagnosis: str,
    needs_issue_update: bool,
    reason: str,
    latest: dict[str, Any] | None = None,
    age_seconds: float | None = None,
    ok: bool = False,
) -> HeartbeatStatus:
    latest = latest or {}
    return HeartbeatStatus(
        ok=ok,
        diagnosis=diagnosis,
        needs_issue_update=needs_issue_update,
        current_shadow_state_verified=False,
        prior_state_reused=False,
        latest_run_id=_optional_text(latest.get("databaseId")),
        latest_run_status=_optional_text(latest.get("status")),
        latest_run_conclusion=_optional_text(latest.get("conclusion")),
        latest_run_created_at=_optional_text(latest.get("createdAt")),
        latest_run_updated_at=_optional_text(latest.get("updatedAt")),
        latest_run_head_sha=_optional_text(latest.get("headSha")),
        age_seconds=age_seconds,
        checked_at=checked.isoformat(),
        reason=reason,
    )


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    raw = json.loads(args.runs_json.read_text())
    if not isinstance(raw, list):
        raise TypeError("runs JSON must contain a list")
    status = evaluate_heartbeat(raw, now=datetime.now(UTC))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(status.__dict__, indent=2, sort_keys=True) + "\n")
    args.output_md.write_text(render_markdown(status))
    print(f"needs_issue_update={'true' if status.needs_issue_update else 'false'}")
    print(f"diagnosis={status.diagnosis}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
