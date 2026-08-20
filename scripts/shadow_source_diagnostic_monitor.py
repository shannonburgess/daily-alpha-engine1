"""Fail-closed health projection for the bounded SH24 source-side diagnostic.

This monitor consumes only the sanitized publication manifest written by
``diagnose-shadow-signal-coverage.yml``. It never calls ORATS itself and never
mutates TradingView or execution state. The expensive source diagnostic keeps its
bounded post-close cadence; the hourly PAPER-shadow monitor only verifies that the
latest completed NYSE session has the expected publication state once that cadence
is due.
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
PUBLICATION_SCHEMA = "SH24_SOURCE_DIAGNOSTIC_PUBLICATION_V1"
FIRST_SCHEDULE_UTC = time(3, 25)
SECOND_SCHEDULE_UTC = time(6, 25)
SCHEDULER_GRACE = timedelta(minutes=75)
FUTURE_SKEW = timedelta(seconds=60)


@dataclass(frozen=True)
class SourceDiagnosticStatus:
    ok: bool
    status: str
    diagnosis: str
    reason: str
    target_session_date: str
    first_due_at: str
    second_due_at: str
    publication_found: bool
    publication_target_date: str | None
    published_at_utc: str | None
    publication_age_seconds: float | None
    source_data_status: str | None
    source_diagnostic_complete: bool | None
    interpretation: str | None
    requested_symbol_count: int | None
    symbols_evaluated: int | None
    expected_entry_count: int | None
    workflow_run_id: int | None
    workflow_head_sha: str | None
    checked_at: str
    research_only: bool = True
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False
    tradingview_configuration_frozen: bool = True
    tradingview_mutation_attempted: bool = False


def evaluate_source_diagnostic(
    publication: dict[str, Any] | None,
    *,
    now: datetime,
) -> SourceDiagnosticStatus:
    """Evaluate sanitized SH24 source-diagnostic publication health."""
    _require_aware(now, "now")
    checked = now.astimezone(UTC)
    target = _latest_completed_session(checked)
    first_due, second_due = _due_times(target)

    if publication is None:
        if checked < first_due + SCHEDULER_GRACE:
            return _status(
                checked,
                target,
                first_due,
                second_due,
                publication=None,
                ok=True,
                status="PENDING",
                diagnosis="SH24_SOURCE_DIAGNOSTIC_NOT_DUE",
                reason=(
                    "The bounded post-close SH24 source diagnostic has not reached its first "
                    "scheduled-attempt grace boundary for the latest completed NYSE session."
                ),
            )
        return _status(
            checked,
            target,
            first_due,
            second_due,
            publication=None,
            ok=False,
            status="FAIL",
            diagnosis="SH24_SOURCE_DIAGNOSTIC_PUBLICATION_MISSING",
            reason=(
                "No sanitized SH24 source-diagnostic publication is available after the first "
                "bounded post-close attempt grace boundary."
            ),
        )

    contract_error = _publication_contract_error(publication, checked=checked)
    if contract_error is not None:
        return _status(
            checked,
            target,
            first_due,
            second_due,
            publication=publication,
            ok=False,
            status="FAIL",
            diagnosis="SH24_SOURCE_DIAGNOSTIC_PUBLICATION_INVALID",
            reason=contract_error,
        )

    publication_target = str(publication["target_date"])
    expected_target = target.isoformat()
    if publication_target > expected_target:
        return _status(
            checked,
            target,
            first_due,
            second_due,
            publication=publication,
            ok=False,
            status="FAIL",
            diagnosis="SH24_SOURCE_DIAGNOSTIC_FUTURE_TARGET",
            reason=(
                f"Latest sanitized publication targets {publication_target}, later than the latest "
                f"completed verified NYSE session {expected_target}."
            ),
        )
    if publication_target < expected_target:
        if checked < first_due + SCHEDULER_GRACE:
            return _status(
                checked,
                target,
                first_due,
                second_due,
                publication=publication,
                ok=True,
                status="PENDING",
                diagnosis="SH24_SOURCE_DIAGNOSTIC_CURRENT_SESSION_NOT_DUE",
                reason=(
                    f"Latest publication covers {publication_target}; the {expected_target} bounded "
                    "post-close diagnostic is not yet past its first scheduled-attempt grace boundary."
                ),
            )
        return _status(
            checked,
            target,
            first_due,
            second_due,
            publication=publication,
            ok=False,
            status="FAIL",
            diagnosis="SH24_SOURCE_DIAGNOSTIC_STALE_TARGET",
            reason=(
                f"Latest publication covers {publication_target}, but {expected_target} is now due."
            ),
        )

    source_status = str(publication.get("source_data_status") or "").upper()
    complete = publication.get("source_diagnostic_complete") is True

    if source_status == "COMPLETE" and complete:
        return _status(
            checked,
            target,
            first_due,
            second_due,
            publication=publication,
            ok=True,
            status="PASS",
            diagnosis="SH24_SOURCE_DIAGNOSTIC_COMPLETE",
            reason=(
                "The latest completed NYSE session has a sanitized, safety-bounded SH24 source "
                "diagnostic publication. TradingView private alert coverage remains outside this "
                "control and is not inferred."
            ),
        )

    if source_status == "PENDING_PROVIDER_PUBLICATION" and not complete:
        second_boundary = second_due + SCHEDULER_GRACE
        reason = (
            "ORATS historical daily data had not uniformly published the target session when the "
            "latest bounded diagnostic ran; no zero-signal inference is made from missing bars."
        )
        if checked >= second_boundary:
            reason += " The second bounded attempt has also passed; provider publication remains pending."
        return _status(
            checked,
            target,
            first_due,
            second_due,
            publication=publication,
            ok=True,
            status="PENDING",
            diagnosis="SH24_SOURCE_DATA_PENDING_PROVIDER_PUBLICATION",
            reason=reason,
        )

    return _status(
        checked,
        target,
        first_due,
        second_due,
        publication=publication,
        ok=False,
        status="FAIL",
        diagnosis="SH24_SOURCE_DIAGNOSTIC_INCOMPLETE",
        reason=(
            "The latest sanitized SH24 source diagnostic is neither complete nor an explicitly "
            "uniform provider-publication delay; fail closed on partial/malformed source evidence."
        ),
    )


def render_markdown(status: SourceDiagnosticStatus) -> str:
    age = (
        "unknown"
        if status.publication_age_seconds is None
        else f"{status.publication_age_seconds:.1f}s"
    )
    return "\n".join(
        [
            "",
            "### SH24 source-side diagnostic health",
            f"Status: **{status.status}**  ",
            f"Diagnosis: `{status.diagnosis}`  ",
            f"Latest completed NYSE session: `{status.target_session_date}`  ",
            f"First/second bounded attempt UTC: `{status.first_due_at}` / `{status.second_due_at}`  ",
            f"Publication found: **{status.publication_found}**  ",
            f"Published target: `{status.publication_target_date or 'none'}`  ",
            f"Published at: `{status.published_at_utc or 'none'}`; age=`{age}`  ",
            f"Source data: `{status.source_data_status or 'none'}`; complete={status.source_diagnostic_complete}  ",
            f"Interpretation: `{status.interpretation or 'none'}`  ",
            (
                "Requested/evaluated/expected-entry counts: "
                f"`{status.requested_symbol_count}` / `{status.symbols_evaluated}` / "
                f"`{status.expected_entry_count}`  "
            ),
            f"Diagnostic workflow run/head: `{status.workflow_run_id or 'none'}` / `{status.workflow_head_sha or 'none'}`  ",
            f"Reason: {status.reason}  ",
            "TradingView configuration: **frozen; private alert membership is not inferred**  ",
            (
                "Safety: `research_only=true`, `promotion_authorized=false`, "
                "`trading_authorized=false`, `live_trading_enabled=false`"
            ),
            "",
        ]
    )


def _latest_completed_session(now: datetime) -> date:
    current = core_session_for(now)
    if (
        current.calendar_status == "VERIFIED"
        and current.is_trading_day
        and current.session_phase == "POST_SESSION"
    ):
        return date.fromisoformat(current.session_date_et)

    local_date = now.astimezone(NEW_YORK).date()
    for offset in range(1, 8):
        candidate = local_date - timedelta(days=offset)
        after_close = datetime.combine(candidate, time(17, 0), tzinfo=NEW_YORK)
        session = core_session_for(after_close)
        if session.calendar_status == "VERIFIED" and session.is_trading_day:
            return candidate
    raise ValueError("No verified completed NYSE session found within the previous seven days")


def _due_times(target: date) -> tuple[datetime, datetime]:
    next_utc_day = target + timedelta(days=1)
    return (
        datetime.combine(next_utc_day, FIRST_SCHEDULE_UTC, tzinfo=UTC),
        datetime.combine(next_utc_day, SECOND_SCHEDULE_UTC, tzinfo=UTC),
    )


def _publication_contract_error(publication: dict[str, Any], *, checked: datetime) -> str | None:
    if publication.get("schema_version") != PUBLICATION_SCHEMA:
        return "Unexpected SH24 source-diagnostic publication schema."
    if publication.get("workflow") != "diagnose-shadow-signal-coverage.yml":
        return "Unexpected SH24 source-diagnostic workflow identity."
    if publication.get("research_only") is not True:
        return "SH24 source-diagnostic publication is not explicitly research_only=true."
    if publication.get("promotion_authorized") is not False:
        return "SH24 source-diagnostic publication promotion_authorized is not false."
    if publication.get("trading_authorized") is not False:
        return "SH24 source-diagnostic publication trading_authorized is not false."
    if publication.get("live_trading_enabled") is not False:
        return "SH24 source-diagnostic publication live_trading_enabled is not false."
    try:
        date.fromisoformat(str(publication.get("target_date")))
    except ValueError:
        return "SH24 source-diagnostic target_date is malformed."
    published = _parse_aware(publication.get("published_at_utc"))
    if published is None:
        return "SH24 source-diagnostic published_at_utc is missing or not timezone-aware."
    if published - checked > FUTURE_SKEW:
        return "SH24 source-diagnostic publication timestamp is implausibly in the future."
    for key in ("requested_symbol_count", "symbols_evaluated", "expected_entry_count", "run_id"):
        value = publication.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return f"SH24 source-diagnostic {key} must be a non-negative integer."
    if not str(publication.get("head_sha") or "").strip():
        return "SH24 source-diagnostic head_sha is missing."
    if not str(publication.get("source_data_status") or "").strip():
        return "SH24 source-diagnostic source_data_status is missing."
    return None


def _status(
    checked: datetime,
    target: date,
    first_due: datetime,
    second_due: datetime,
    *,
    publication: dict[str, Any] | None,
    ok: bool,
    status: str,
    diagnosis: str,
    reason: str,
) -> SourceDiagnosticStatus:
    published = None if publication is None else _parse_aware(publication.get("published_at_utc"))
    age = None if published is None else max(0.0, (checked - published).total_seconds())
    return SourceDiagnosticStatus(
        ok=ok,
        status=status,
        diagnosis=diagnosis,
        reason=reason,
        target_session_date=target.isoformat(),
        first_due_at=first_due.isoformat(),
        second_due_at=second_due.isoformat(),
        publication_found=publication is not None,
        publication_target_date=None if publication is None else str(publication.get("target_date") or "") or None,
        published_at_utc=None if published is None else published.isoformat(),
        publication_age_seconds=age,
        source_data_status=None if publication is None else str(publication.get("source_data_status") or "") or None,
        source_diagnostic_complete=None if publication is None else publication.get("source_diagnostic_complete") is True,
        interpretation=None if publication is None else str(publication.get("interpretation") or "") or None,
        requested_symbol_count=None if publication is None else publication.get("requested_symbol_count"),
        symbols_evaluated=None if publication is None else publication.get("symbols_evaluated"),
        expected_entry_count=None if publication is None else publication.get("expected_entry_count"),
        workflow_run_id=None if publication is None else publication.get("run_id"),
        workflow_head_sha=None if publication is None else str(publication.get("head_sha") or "") or None,
        checked_at=checked.isoformat(),
    )


def _parse_aware(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _load(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    status = evaluate_source_diagnostic(_load(args.publication), now=datetime.now(UTC))
    Path(args.output_json).write_text(json.dumps(asdict(status), indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(status))
    return 0 if status.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
