"""Fail-closed health check for the canonical PAPER ARMED replay scheduler.

This monitor is GitHub-only. It verifies that the default-branch replay workflow is
actually starting during each verified NYSE core session, without invoking AWS or
mutating TradingView. Manual workflow_dispatch runs are ignored so they cannot mask
a missing scheduled automation tick.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if __package__:
    from scripts.nyse_session_calendar import core_session_for
else:
    from nyse_session_calendar import core_session_for

NEW_YORK = ZoneInfo("America/New_York")
FIRST_REPLAY_HEALTH_CHECK = time(10, 0)
REPLAY_TICK_MINUTE = 40
FRESH_SCHEDULE_SECONDS = 95 * 60
MAX_PENDING_SECONDS = 60 * 60
FINAL_TICK_WINDOW = timedelta(minutes=35)
FINAL_TICK_BEFORE_CLOSE = timedelta(minutes=20)
PENDING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


@dataclass(frozen=True)
class ReplaySchedulerStatus:
    ok: bool
    status: str
    diagnosis: str
    reason: str
    session_phase: str
    session_date_et: str
    latest_run_id: str | None
    latest_run_status: str | None
    latest_run_conclusion: str | None
    latest_run_created_at: str | None
    latest_run_updated_at: str | None
    age_seconds: float | None
    checked_at: str
    workflow_state: str | None = None
    workflow_created_at: str | None = None
    trading_authorized: bool = False
    live_trading_enabled: bool = False
    tradingview_configuration_frozen: bool = True
    tradingview_mutation_attempted: bool = False


def evaluate_replay_scheduler(
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    workflow_created_at: datetime | None = None,
    workflow_state: str | None = None,
) -> ReplaySchedulerStatus:
    """Verify scheduled replay cadence for the current official NYSE session."""
    _require_aware(now, "now")
    if workflow_created_at is not None:
        _require_aware(workflow_created_at, "workflow_created_at")
        workflow_created_at = workflow_created_at.astimezone(UTC)
    normalized_state = _text(workflow_state).lower() or None
    checked = now.astimezone(UTC)
    session = core_session_for(checked)

    if normalized_state is not None and normalized_state != "active":
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_WORKFLOW_NOT_ACTIVE",
            reason=f"Canonical PAPER ARMED replay workflow state is {normalized_state!r}, not active.",
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    if session.calendar_status != "VERIFIED":
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_CALENDAR_UNVERIFIED",
            reason="NYSE session coverage is unavailable; scheduled replay health cannot be inferred.",
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    if session.is_trading_day is not True:
        return _status(
            checked,
            session,
            ok=True,
            status="NOT_DUE",
            diagnosis="REPLAY_NOT_DUE_NON_TRADING_DAY",
            reason="No PAPER ARMED replay is due on a verified NYSE non-trading day.",
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    local_now = checked.astimezone(NEW_YORK)
    if session.session_phase == "PREMARKET":
        return _status(
            checked,
            session,
            ok=True,
            status="NOT_DUE",
            diagnosis="REPLAY_NOT_DUE_PREMARKET",
            reason="The first replay-health checkpoint is not due before the NYSE core session.",
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    scheduled = _scheduled_runs_for_session(
        runs, session_date=date.fromisoformat(session.session_date_et)
    )

    if session.session_phase == "REGULAR_SESSION":
        if local_now.time().replace(tzinfo=None) < FIRST_REPLAY_HEALTH_CHECK:
            return _status(
                checked,
                session,
                ok=True,
                status="NOT_DUE",
                diagnosis="REPLAY_FIRST_TICK_NOT_DUE",
                reason="The first scheduled replay tick has not reached its health-check grace boundary.",
                workflow_created_at=workflow_created_at,
                workflow_state=normalized_state,
            )
        return _evaluate_in_session(
            scheduled,
            checked=checked,
            session=session,
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    if session.session_phase == "POST_SESSION":
        return _evaluate_post_session(
            scheduled,
            checked=checked,
            session=session,
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    return _status(
        checked,
        session,
        ok=False,
        status="FAIL",
        diagnosis="REPLAY_SESSION_PHASE_UNRECOGNIZED",
        reason=f"Unhandled verified NYSE session phase: {session.session_phase}",
        workflow_created_at=workflow_created_at,
        workflow_state=normalized_state,
    )


def render_markdown(status: ReplaySchedulerStatus) -> str:
    age = "unknown" if status.age_seconds is None else f"{status.age_seconds:.1f}s"
    lines = [
        "",
        "### PAPER ARMED replay scheduler health",
        f"Status: **{status.status}**  ",
        f"Diagnosis: `{status.diagnosis}`  ",
        f"Session: `{status.session_date_et}` / `{status.session_phase}`  ",
        f"Workflow state: `{status.workflow_state or 'unknown'}`  ",
        f"Workflow created: `{status.workflow_created_at or 'unknown'}`  ",
        f"Latest scheduled replay run: `{status.latest_run_id or 'none'}`  ",
        (
            "Latest run status/conclusion: "
            f"`{status.latest_run_status or 'none'}` / `{status.latest_run_conclusion or 'none'}`  "
        ),
        f"Latest run created: `{status.latest_run_created_at or 'none'}`  ",
        f"Latest run updated: `{status.latest_run_updated_at or 'none'}`  ",
        f"Scheduler evidence age: `{age}`  ",
        f"Reason: {status.reason}  ",
        "TradingView configuration: **frozen; no mutation attempted**  ",
        "Safety: `trading_authorized=false`, `live_trading_enabled=false`",
        "",
    ]
    return "\n".join(lines)


def _evaluate_in_session(
    runs: list[dict[str, Any]],
    *,
    checked: datetime,
    session: Any,
    workflow_created_at: datetime | None,
    workflow_state: str | None,
) -> ReplaySchedulerStatus:
    due_tick = _latest_due_tick_utc(checked)
    due_runs = [
        run
        for run in runs
        if (created := _parse_aware(run.get("createdAt"))) is not None
        and created >= due_tick
    ]
    latest = _latest_run(due_runs)
    if latest is None:
        if workflow_created_at is not None and workflow_created_at > due_tick:
            return _status(
                checked,
                session,
                ok=True,
                status="PENDING",
                diagnosis="REPLAY_SCHEDULER_ACTIVATION_PENDING",
                reason=(
                    "The replay workflow was created after the latest due scheduler tick; "
                    "the first eligible default-branch tick has not occurred yet."
                ),
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_TICK_MISSING",
            reason=(
                "No scheduled PAPER ARMED replay workflow run is visible for the latest due "
                f"hourly tick ({due_tick.isoformat()})."
            ),
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    reference = _run_reference(latest)
    if reference is None:
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_INVALID_TIMESTAMP",
            reason="Latest scheduled replay run has no valid timezone-aware timestamp.",
            latest=latest,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    age = (checked - reference).total_seconds()
    if age < -60:
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_FUTURE_TIMESTAMP",
            reason="Latest scheduled replay timestamp is implausibly in the future.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )
    age = max(0.0, age)

    run_status = _text(latest.get("status")).lower()
    conclusion = _text(latest.get("conclusion")).lower()
    if run_status in PENDING_STATUSES:
        if age <= MAX_PENDING_SECONDS:
            return _status(
                checked,
                session,
                ok=True,
                status="PENDING",
                diagnosis="REPLAY_SCHEDULER_PENDING",
                reason="The latest due scheduled replay run is queued or in progress.",
                latest=latest,
                age_seconds=age,
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_STUCK",
            reason="Scheduled replay has remained queued/in progress beyond 60 minutes.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    if run_status == "completed" and conclusion == "success":
        if age <= FRESH_SCHEDULE_SECONDS:
            return _status(
                checked,
                session,
                ok=True,
                status="PASS",
                diagnosis="REPLAY_SCHEDULER_HEALTHY",
                reason="Latest due scheduled replay completed successfully.",
                latest=latest,
                age_seconds=age,
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_STALE",
            reason="Latest due successful scheduled replay is older than 95 minutes.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    if run_status == "completed" and conclusion and conclusion != "success":
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_COMPLETED_NON_SUCCESS",
            reason="Latest due scheduled replay completed non-successfully.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    return _status(
        checked,
        session,
        ok=False,
        status="FAIL",
        diagnosis="REPLAY_SCHEDULER_UNKNOWN_RUN_STATE",
        reason="Latest due scheduled replay has an unrecognized status/conclusion pair.",
        latest=latest,
        age_seconds=age,
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )


def _evaluate_post_session(
    runs: list[dict[str, Any]],
    *,
    checked: datetime,
    session: Any,
    workflow_created_at: datetime | None,
    workflow_state: str | None,
) -> ReplaySchedulerStatus:
    close_utc = _scheduled_close_utc(session)
    if close_utc is None:
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULED_CLOSE_UNAVAILABLE",
            reason="Verified trading day has no scheduled close; final replay coverage cannot be proven.",
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    window_start = close_utc - FINAL_TICK_WINDOW
    final_tick = close_utc - FINAL_TICK_BEFORE_CLOSE
    final_candidates = [
        run
        for run in runs
        if (created := _parse_aware(run.get("createdAt"))) is not None
        and window_start <= created <= close_utc
    ]
    latest = _latest_run(final_candidates)
    if latest is None:
        if workflow_created_at is not None and workflow_created_at > final_tick:
            return _status(
                checked,
                session,
                ok=True,
                status="PENDING",
                diagnosis="REPLAY_SCHEDULER_ACTIVATION_PENDING",
                reason=(
                    "The replay workflow was created after the session's final nominal scheduler "
                    "tick; first-session final coverage was not technically available."
                ),
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_FINAL_TICK_MISSING",
            reason=(
                "No scheduled replay run started within the final 35 minutes before the official "
                "NYSE core close."
            ),
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    reference = _run_reference(latest)
    age = None if reference is None else max(0.0, (checked - reference).total_seconds())
    run_status = _text(latest.get("status")).lower()
    conclusion = _text(latest.get("conclusion")).lower()
    if run_status in PENDING_STATUSES:
        if age is not None and age <= MAX_PENDING_SECONDS:
            return _status(
                checked,
                session,
                ok=True,
                status="PENDING",
                diagnosis="REPLAY_FINAL_TICK_PENDING",
                reason="The final scheduled replay run is still pending within the allowed window.",
                latest=latest,
                age_seconds=age,
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_FINAL_TICK_STUCK",
            reason="The final scheduled replay run is stuck beyond the allowed pending window.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    if run_status == "completed" and conclusion == "success":
        return _status(
            checked,
            session,
            ok=True,
            status="PASS",
            diagnosis="REPLAY_FINAL_TICK_HEALTHY",
            reason="A scheduled replay run completed successfully within 35 minutes of the official close.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    if run_status == "completed" and conclusion and conclusion != "success":
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_FINAL_TICK_NON_SUCCESS",
            reason="The final scheduled replay run completed non-successfully.",
            latest=latest,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    return _status(
        checked,
        session,
        ok=False,
        status="FAIL",
        diagnosis="REPLAY_FINAL_TICK_UNKNOWN_STATE",
        reason="The final scheduled replay run has an unrecognized state.",
        latest=latest,
        age_seconds=age,
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )


def _scheduled_runs_for_session(
    runs: list[dict[str, Any]],
    *,
    session_date: date,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict) or _text(run.get("event")).lower() != "schedule":
            continue
        created = _parse_aware(run.get("createdAt"))
        if created is None:
            continue
        if created.astimezone(NEW_YORK).date() == session_date:
            result.append(run)
    return result


def _latest_due_tick_utc(checked: datetime) -> datetime:
    local = checked.astimezone(NEW_YORK)
    due = local.replace(minute=REPLAY_TICK_MINUTE, second=0, microsecond=0)
    if due > local:
        due -= timedelta(hours=1)
    return due.astimezone(UTC)


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


def _run_reference(run: dict[str, Any]) -> datetime | None:
    status = _text(run.get("status")).lower()
    created = _parse_aware(run.get("createdAt"))
    updated = _parse_aware(run.get("updatedAt"))
    return created if status in PENDING_STATUSES else (updated or created)


def _scheduled_close_utc(session: Any) -> datetime | None:
    if not session.scheduled_close_et:
        return None
    hour, minute = (int(part) for part in session.scheduled_close_et.split(":"))
    local = datetime.combine(
        date.fromisoformat(session.session_date_et),
        time(hour, minute),
        tzinfo=NEW_YORK,
    )
    return local.astimezone(UTC)


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


def _load_workflow_metadata(path: Path | None) -> tuple[datetime | None, str | None]:
    if path is None:
        return None, None
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise TypeError("workflow metadata JSON must contain an object")
    created_at = _parse_aware(raw.get("created_at"))
    state = _optional_text(raw.get("state"))
    return created_at, state


def _status(
    checked: datetime,
    session: Any,
    *,
    ok: bool,
    status: str,
    diagnosis: str,
    reason: str,
    latest: dict[str, Any] | None = None,
    age_seconds: float | None = None,
    workflow_created_at: datetime | None = None,
    workflow_state: str | None = None,
) -> ReplaySchedulerStatus:
    latest = latest or {}
    return ReplaySchedulerStatus(
        ok=ok,
        status=status,
        diagnosis=diagnosis,
        reason=reason,
        session_phase=str(session.session_phase),
        session_date_et=str(session.session_date_et),
        latest_run_id=_optional_text(latest.get("databaseId")),
        latest_run_status=_optional_text(latest.get("status")),
        latest_run_conclusion=_optional_text(latest.get("conclusion")),
        latest_run_created_at=_optional_text(latest.get("createdAt")),
        latest_run_updated_at=_optional_text(latest.get("updatedAt")),
        age_seconds=age_seconds,
        checked_at=checked.isoformat(),
        workflow_state=workflow_state,
        workflow_created_at=(
            None if workflow_created_at is None else workflow_created_at.astimezone(UTC).isoformat()
        ),
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-json", type=Path, required=True)
    parser.add_argument("--workflow-metadata", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    raw = json.loads(args.runs_json.read_text())
    if not isinstance(raw, list):
        raise TypeError("runs JSON must contain a list")
    workflow_created_at, workflow_state = _load_workflow_metadata(args.workflow_metadata)
    status = evaluate_replay_scheduler(
        raw,
        now=datetime.now(UTC),
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(asdict(status), indent=2, sort_keys=True) + "\n")
    args.output_md.write_text(render_markdown(status))
    print(json.dumps(asdict(status), sort_keys=True))
    return 0 if status.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
