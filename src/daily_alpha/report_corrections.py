"""Disconnected commercial-beta report correction/retraction controls.

This module models customer-visible research status transitions only. It has no
publishing, email, billing, trading, or production side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum


class ReportStatus(StrEnum):
    VALID = "VALID"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPERSEDED = "SUPERSEDED"
    CORRECTED = "CORRECTED"
    RETRACTED = "RETRACTED"


TERMINAL_OR_NONCURRENT = frozenset(
    {ReportStatus.SUPERSEDED, ReportStatus.CORRECTED, ReportStatus.RETRACTED}
)

_ALLOWED_TRANSITIONS: dict[ReportStatus, frozenset[ReportStatus]] = {
    ReportStatus.VALID: frozenset(
        {
            ReportStatus.VALID,
            ReportStatus.UNDER_REVIEW,
            ReportStatus.SUPERSEDED,
            ReportStatus.CORRECTED,
            ReportStatus.RETRACTED,
        }
    ),
    ReportStatus.UNDER_REVIEW: frozenset(
        {
            ReportStatus.UNDER_REVIEW,
            ReportStatus.VALID,
            ReportStatus.SUPERSEDED,
            ReportStatus.CORRECTED,
            ReportStatus.RETRACTED,
        }
    ),
    ReportStatus.SUPERSEDED: frozenset(
        {ReportStatus.SUPERSEDED, ReportStatus.RETRACTED}
    ),
    ReportStatus.CORRECTED: frozenset(
        {ReportStatus.CORRECTED, ReportStatus.RETRACTED}
    ),
    ReportStatus.RETRACTED: frozenset({ReportStatus.RETRACTED}),
}


@dataclass(frozen=True)
class ReportCorrectionEvent:
    event_id: str
    report_id: str
    target_status: ReportStatus
    reason_code: str
    occurred_at: datetime
    replacement_report_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    methodology_ids: tuple[str, ...] = ()
    delivery_correlation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if not self.report_id.strip():
            raise ValueError("report_id is required")
        if not self.reason_code.strip():
            raise ValueError("reason_code is required")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.target_status in {ReportStatus.SUPERSEDED, ReportStatus.CORRECTED}:
            if not self.replacement_report_id:
                raise ValueError("replacement_report_id is required for replacement status")
            if self.replacement_report_id == self.report_id:
                raise ValueError("replacement_report_id must differ from report_id")


@dataclass(frozen=True)
class ReportCorrectionState:
    report_id: str
    status: ReportStatus = ReportStatus.VALID
    last_event_id: str | None = None
    last_reason_code: str | None = None
    last_transition_at: datetime | None = None
    replacement_report_id: str | None = None

    @property
    def is_current(self) -> bool:
        return self.status == ReportStatus.VALID

    @property
    def performance_evidence_eligible(self) -> bool:
        return self.status == ReportStatus.VALID

    @property
    def delivery_replay_allowed(self) -> bool:
        return self.status == ReportStatus.VALID


def initial_report_state(report_id: str) -> ReportCorrectionState:
    value = report_id.strip()
    if not value:
        raise ValueError("report_id is required")
    return ReportCorrectionState(report_id=value)


def apply_report_correction(
    state: ReportCorrectionState,
    event: ReportCorrectionEvent,
) -> ReportCorrectionState:
    """Apply one immutable correction event with fail-closed transition rules.

    Replaying the same event id against the already-projected state is idempotent.
    A different event cannot restore a non-current artifact to VALID.
    """

    if event.report_id != state.report_id:
        raise ValueError("event report_id does not match state")

    if event.event_id == state.last_event_id:
        expected_status = event.target_status
        expected_replacement = event.replacement_report_id
        if (
            state.status == expected_status
            and state.replacement_report_id == expected_replacement
            and state.last_reason_code == event.reason_code
        ):
            return state
        raise ValueError("event_id replay conflicts with projected state")

    allowed = _ALLOWED_TRANSITIONS[state.status]
    if event.target_status not in allowed:
        raise ValueError(
            f"invalid report-status transition: {state.status}->{event.target_status}"
        )

    if state.status in TERMINAL_OR_NONCURRENT and event.target_status == ReportStatus.VALID:
        raise ValueError("non-current report cannot be silently restored to VALID")

    replacement_id = (
        event.replacement_report_id
        if event.target_status in {ReportStatus.SUPERSEDED, ReportStatus.CORRECTED}
        else state.replacement_report_id
    )

    return replace(
        state,
        status=event.target_status,
        last_event_id=event.event_id,
        last_reason_code=event.reason_code,
        last_transition_at=event.occurred_at.astimezone(UTC),
        replacement_report_id=replacement_id,
    )


def correction_event(
    *,
    event_id: str,
    report_id: str,
    target_status: ReportStatus,
    reason_code: str,
    replacement_report_id: str | None = None,
    occurred_at: datetime | None = None,
) -> ReportCorrectionEvent:
    """Convenience constructor used by staging/tests; no side effects."""

    return ReportCorrectionEvent(
        event_id=event_id,
        report_id=report_id,
        target_status=target_status,
        reason_code=reason_code,
        replacement_report_id=replacement_report_id,
        occurred_at=occurred_at or datetime.now(UTC),
    )
