"""Fail-closed health check for the canonical PAPER ARMED replay automation.

The primary GitHub schedule remains observable, but a trusted workflow_run from the
canonical PAPER-shadow monitor is also accepted as an automated fail-safe. Manual
workflow_dispatch runs are ignored so operator activity cannot mask missing automation.
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
FALLBACK_FIRST_GRACE_END = time(10, 30)
REPLAY_TICK_MINUTE = 40
FRESH_SCHEDULE_SECONDS = 95 * 60
FRESH_FALLBACK_SECONDS = 80 * 60
MAX_PENDING_SECONDS = 60 * 60
FINAL_TICK_WINDOW = timedelta(minutes=35)
FALLBACK_FINAL_TICK_WINDOW = timedelta(minutes=50)
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
    """Verify automated replay cadence for the current official NYSE session."""
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
            reason="NYSE session coverage is unavailable; replay automation health cannot be inferred.",
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

    session_date = date.fromisoformat(session.session_date_et)
    scheduled = _runs_for_session(runs, session_date=session_date, event="schedule")
    fallback = _runs_for_session(runs, session_date=session_date, event="workflow_run")

    if session.session_phase == "REGULAR_SESSION":
        if local_now.time().replace(tzinfo=None) < FIRST_REPLAY_HEALTH_CHECK:
            return _status(
                checked,
                session,
                ok=True,
                status="NOT_DUE",
                diagnosis="REPLAY_FIRST_TICK_NOT_DUE",
                reason="The first replay-health checkpoint has not reached its grace boundary.",
                workflow_created_at=workflow_created_at,
                workflow_state=normalized_state,
            )
        return _evaluate_in_session(
            scheduled,
            fallback,
            checked=checked,
            session=session,
            workflow_created_at=workflow_created_at,
            workflow_state=normalized_state,
        )

    if session.session_phase == "POST_SESSION":
        return _evaluate_post_session(
            scheduled,
            fallback,
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
        f"Latest automated replay run: `{status.latest_run_id or 'none'}`  ",
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
    scheduled_runs: list[dict[str, Any]],
    fallback_runs: list[dict[str, Any]],
    *,
    checked: datetime,
    session: Any,
    workflow_created_at: datetime | None,
    workflow_state: str | None,
) -> ReplaySchedulerStatus:
    due_tick = _latest_due_tick_utc(checked)
    due_scheduled = [
        run
        for run in scheduled_runs
        if (created := _parse_aware(run.get("createdAt"))) is not None and created >= due_tick
    ]
    latest_scheduled = _latest_run(due_scheduled)
    if latest_scheduled is not None:
        return _evaluate_run(
            latest_scheduled,
            checked=checked,
            session=session,
            max_success_age=FRESH_SCHEDULE_SECONDS,
            pending_diagnosis="REPLAY_SCHEDULER_PENDING",
            pending_reason="The latest due scheduled replay run is queued or in progress.",
            stuck_diagnosis="REPLAY_SCHEDULER_STUCK",
            stuck_reason="Scheduled replay has remained queued/in progress beyond 60 minutes.",
            success_diagnosis="REPLAY_SCHEDULER_HEALTHY",
            success_reason="Latest due scheduled replay completed successfully.",
            stale_diagnosis="REPLAY_SCHEDULER_STALE",
            stale_reason="Latest due successful scheduled replay is older than 95 minutes.",
            failure_diagnosis="REPLAY_SCHEDULER_COMPLETED_NON_SUCCESS",
            failure_reason="Latest due scheduled replay completed non-successfully.",
            unknown_diagnosis="REPLAY_SCHEDULER_UNKNOWN_RUN_STATE",
            unknown_reason="Latest due scheduled replay has an unrecognized status/conclusion pair.",
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    market_open_utc = _session_open_utc(session)
    eligible_fallback = [
        run
        for run in fallback_runs
        if (created := _parse_aware(run.get("createdAt"))) is not None
        and (market_open_utc is None or created >= market_open_utc)
        and created <= checked + timedelta(minutes=1)
    ]
    latest_fallback = _latest_run(eligible_fallback)
    if latest_fallback is not None:
        return _evaluate_run(
            latest_fallback,
            checked=checked,
            session=session,
            max_success_age=FRESH_FALLBACK_SECONDS,
            pending_diagnosis="REPLAY_MONITOR_FALLBACK_PENDING",
            pending_reason="The latest monitor-triggered replay fail-safe is queued or in progress.",
            stuck_diagnosis="REPLAY_MONITOR_FALLBACK_STUCK",
            stuck_reason="Monitor-triggered replay has remained queued/in progress beyond 60 minutes.",
            success_diagnosis="REPLAY_MONITOR_FALLBACK_HEALTHY",
            success_reason=(
                "The standalone cron tick is absent, but the trusted monitor-triggered replay "
                "fail-safe completed successfully within the allowed cadence."
            ),
            stale_diagnosis="REPLAY_MONITOR_FALLBACK_STALE",
            stale_reason="The latest successful monitor-triggered replay is older than 80 minutes.",
            failure_diagnosis="REPLAY_MONITOR_FALLBACK_NON_SUCCESS",
            failure_reason="The latest monitor-triggered replay completed non-successfully.",
            unknown_diagnosis="REPLAY_MONITOR_FALLBACK_UNKNOWN_STATE",
            unknown_reason="The latest monitor-triggered replay has an unrecognized state.",
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    local_time = checked.astimezone(NEW_YORK).time().replace(tzinfo=None)
    if local_time < FALLBACK_FIRST_GRACE_END:
        return _status(
            checked,
            session,
            ok=True,
            status="PENDING",
            diagnosis="REPLAY_MONITOR_FALLBACK_FIRST_TICK_PENDING",
            reason=(
                "The primary cron is missing, but the first regular-session canonical monitor "
                "completion has not yet had its bounded fail-safe grace window."
            ),
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    if workflow_created_at is not None and workflow_created_at > due_tick:
        return _status(
            checked,
            session,
            ok=True,
            status="PENDING",
            diagnosis="REPLAY_SCHEDULER_ACTIVATION_PENDING",
            reason=(
                "The replay workflow was created after the latest due scheduler tick; the first "
                "eligible automated replay has not occurred yet."
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
            "Neither a due scheduled replay nor a fresh trusted monitor-triggered replay is "
            f"visible for the current cadence after {due_tick.isoformat()}."
        ),
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )


def _evaluate_post_session(
    scheduled_runs: list[dict[str, Any]],
    fallback_runs: list[dict[str, Any]],
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

    scheduled_candidates = [
        run
        for run in scheduled_runs
        if (created := _parse_aware(run.get("createdAt"))) is not None
        and close_utc - FINAL_TICK_WINDOW <= created <= close_utc
    ]
    latest_scheduled = _latest_run(scheduled_candidates)
    if latest_scheduled is not None:
        return _evaluate_final_run(
            latest_scheduled,
            checked=checked,
            session=session,
            success_diagnosis="REPLAY_FINAL_TICK_HEALTHY",
            success_reason=(
                "A scheduled replay run completed successfully within 35 minutes of the official "
                "NYSE core close."
            ),
            pending_diagnosis="REPLAY_FINAL_TICK_PENDING",
            pending_reason="The final scheduled replay run is still pending within the allowed window.",
            stuck_diagnosis="REPLAY_FINAL_TICK_STUCK",
            stuck_reason="The final scheduled replay run is stuck beyond the allowed pending window.",
            failure_diagnosis="REPLAY_FINAL_TICK_NON_SUCCESS",
            failure_reason="The final scheduled replay run completed non-successfully.",
            unknown_diagnosis="REPLAY_FINAL_TICK_UNKNOWN_STATE",
            unknown_reason="The final scheduled replay run has an unrecognized state.",
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    fallback_candidates = [
        run
        for run in fallback_runs
        if (created := _parse_aware(run.get("createdAt"))) is not None
        and close_utc - FALLBACK_FINAL_TICK_WINDOW <= created <= close_utc
    ]
    latest_fallback = _latest_run(fallback_candidates)
    if latest_fallback is not None:
        return _evaluate_final_run(
            latest_fallback,
            checked=checked,
            session=session,
            success_diagnosis="REPLAY_MONITOR_FALLBACK_FINAL_HEALTHY",
            success_reason=(
                "The trusted monitor-triggered replay fail-safe completed successfully within "
                "50 minutes of the official NYSE core close."
            ),
            pending_diagnosis="REPLAY_MONITOR_FALLBACK_FINAL_PENDING",
            pending_reason="The final monitor-triggered replay fail-safe is still pending.",
            stuck_diagnosis="REPLAY_MONITOR_FALLBACK_FINAL_STUCK",
            stuck_reason="The final monitor-triggered replay fail-safe is stuck beyond 60 minutes.",
            failure_diagnosis="REPLAY_MONITOR_FALLBACK_FINAL_NON_SUCCESS",
            failure_reason="The final monitor-triggered replay fail-safe completed non-successfully.",
            unknown_diagnosis="REPLAY_MONITOR_FALLBACK_FINAL_UNKNOWN_STATE",
            unknown_reason="The final monitor-triggered replay fail-safe has an unrecognized state.",
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    final_tick = close_utc - FINAL_TICK_BEFORE_CLOSE
    if workflow_created_at is not None and workflow_created_at > final_tick:
        return _status(
            checked,
            session,
            ok=True,
            status="PENDING",
            diagnosis="REPLAY_SCHEDULER_ACTIVATION_PENDING",
            reason=(
                "The replay workflow was created after the session's final nominal scheduler tick; "
                "first-session final coverage was not technically available."
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
            "No successful scheduled or trusted monitor-triggered replay run started inside the "
            "bounded final pre-close window."
        ),
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )


def _evaluate_run(
    run: dict[str, Any],
    *,
    checked: datetime,
    session: Any,
    max_success_age: float,
    pending_diagnosis: str,
    pending_reason: str,
    stuck_diagnosis: str,
    stuck_reason: str,
    success_diagnosis: str,
    success_reason: str,
    stale_diagnosis: str,
    stale_reason: str,
    failure_diagnosis: str,
    failure_reason: str,
    unknown_diagnosis: str,
    unknown_reason: str,
    workflow_created_at: datetime | None,
    workflow_state: str | None,
) -> ReplaySchedulerStatus:
    reference = _run_reference(run)
    if reference is None:
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis="REPLAY_SCHEDULER_INVALID_TIMESTAMP",
            reason="Latest automated replay run has no valid timezone-aware timestamp.",
            latest=run,
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
            reason="Latest automated replay timestamp is implausibly in the future.",
            latest=run,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )
    age = max(0.0, age)
    run_status = _text(run.get("status")).lower()
    conclusion = _text(run.get("conclusion")).lower()

    if run_status in PENDING_STATUSES:
        if age <= MAX_PENDING_SECONDS:
            return _status(
                checked,
                session,
                ok=True,
                status="PENDING",
                diagnosis=pending_diagnosis,
                reason=pending_reason,
                latest=run,
                age_seconds=age,
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis=stuck_diagnosis,
            reason=stuck_reason,
            latest=run,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    if run_status == "completed" and conclusion == "success":
        if age <= max_success_age:
            return _status(
                checked,
                session,
                ok=True,
                status="PASS",
                diagnosis=success_diagnosis,
                reason=success_reason,
                latest=run,
                age_seconds=age,
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis=stale_diagnosis,
            reason=stale_reason,
            latest=run,
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
            diagnosis=failure_diagnosis,
            reason=failure_reason,
            latest=run,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    return _status(
        checked,
        session,
        ok=False,
        status="FAIL",
        diagnosis=unknown_diagnosis,
        reason=unknown_reason,
        latest=run,
        age_seconds=age,
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )


def _evaluate_final_run(
    run: dict[str, Any],
    *,
    checked: datetime,
    session: Any,
    success_diagnosis: str,
    success_reason: str,
    pending_diagnosis: str,
    pending_reason: str,
    stuck_diagnosis: str,
    stuck_reason: str,
    failure_diagnosis: str,
    failure_reason: str,
    unknown_diagnosis: str,
    unknown_reason: str,
    workflow_created_at: datetime | None,
    workflow_state: str | None,
) -> ReplaySchedulerStatus:
    reference = _run_reference(run)
    age = None if reference is None else max(0.0, (checked - reference).total_seconds())
    run_status = _text(run.get("status")).lower()
    conclusion = _text(run.get("conclusion")).lower()

    if run_status in PENDING_STATUSES:
        if age is not None and age <= MAX_PENDING_SECONDS:
            return _status(
                checked,
                session,
                ok=True,
                status="PENDING",
                diagnosis=pending_diagnosis,
                reason=pending_reason,
                latest=run,
                age_seconds=age,
                workflow_created_at=workflow_created_at,
                workflow_state=workflow_state,
            )
        return _status(
            checked,
            session,
            ok=False,
            status="FAIL",
            diagnosis=stuck_diagnosis,
            reason=stuck_reason,
            latest=run,
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
            diagnosis=success_diagnosis,
            reason=success_reason,
            latest=run,
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
            diagnosis=failure_diagnosis,
            reason=failure_reason,
            latest=run,
            age_seconds=age,
            workflow_created_at=workflow_created_at,
            workflow_state=workflow_state,
        )

    return _status(
        checked,
        session,
        ok=False,
        status="FAIL",
        diagnosis=unknown_diagnosis,
        reason=unknown_reason,
        latest=run,
        age_seconds=age,
        workflow_created_at=workflow_created_at,
        workflow_state=workflow_state,
    )


def _runs_for_session(
    runs: list[dict[str, Any]],
    *,
    session_date: date,
    event: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict) or _text(run.get("event")).lower() != event:
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


def _session_open_utc(session: Any) -> datetime | None:
    if not session.scheduled_open_et:
        return None
    hour, minute = (int(part) for part in session.scheduled_open_et.split(":"))
    local = datetime.combine(
        date.fromisoformat(session.session_date_et),
        time(hour, minute),
        tzinfo=NEW_YORK,
    )
    return local.astimezone(UTC)


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
