from datetime import UTC, datetime

import pytest

from daily_alpha.report_corrections import (
    ReportCorrectionEvent,
    ReportStatus,
    apply_report_correction,
    initial_report_state,
)


def _event(
    event_id: str,
    report_id: str,
    status: ReportStatus,
    *,
    reason: str = "SOURCE_DATA_CORRECTED",
    replacement: str | None = None,
) -> ReportCorrectionEvent:
    return ReportCorrectionEvent(
        event_id=event_id,
        report_id=report_id,
        target_status=status,
        reason_code=reason,
        replacement_report_id=replacement,
        occurred_at=datetime(2026, 8, 18, 20, 0, tzinfo=UTC),
    )


def test_under_review_blocks_performance_and_delivery_replay():
    state = initial_report_state("report-1")
    state = apply_report_correction(
        state,
        _event("evt-1", "report-1", ReportStatus.UNDER_REVIEW),
    )

    assert state.status == ReportStatus.UNDER_REVIEW
    assert state.is_current is False
    assert state.performance_evidence_eligible is False
    assert state.delivery_replay_allowed is False


def test_corrected_report_requires_distinct_replacement_and_is_noncurrent():
    state = initial_report_state("report-1")
    state = apply_report_correction(
        state,
        _event(
            "evt-1",
            "report-1",
            ReportStatus.CORRECTED,
            replacement="report-2",
        ),
    )

    assert state.status == ReportStatus.CORRECTED
    assert state.replacement_report_id == "report-2"
    assert state.performance_evidence_eligible is False
    assert state.delivery_replay_allowed is False


def test_duplicate_event_replay_is_idempotent():
    state = initial_report_state("report-1")
    event = _event("evt-1", "report-1", ReportStatus.UNDER_REVIEW)
    first = apply_report_correction(state, event)
    second = apply_report_correction(first, event)
    assert second == first


def test_conflicting_duplicate_event_id_fails_closed():
    state = initial_report_state("report-1")
    first = apply_report_correction(
        state,
        _event("evt-1", "report-1", ReportStatus.UNDER_REVIEW),
    )

    with pytest.raises(ValueError, match="event_id replay conflicts"):
        apply_report_correction(
            first,
            _event(
                "evt-1",
                "report-1",
                ReportStatus.CORRECTED,
                replacement="report-2",
            ),
        )


def test_retracted_report_cannot_be_restored_to_valid():
    state = initial_report_state("report-1")
    state = apply_report_correction(
        state,
        _event("evt-1", "report-1", ReportStatus.RETRACTED),
    )

    with pytest.raises(ValueError, match="invalid report-status transition"):
        apply_report_correction(
            state,
            _event("evt-2", "report-1", ReportStatus.VALID),
        )


def test_superseded_report_can_only_remain_superseded_or_be_retracted():
    state = initial_report_state("report-1")
    state = apply_report_correction(
        state,
        _event(
            "evt-1",
            "report-1",
            ReportStatus.SUPERSEDED,
            replacement="report-2",
        ),
    )

    with pytest.raises(ValueError, match="invalid report-status transition"):
        apply_report_correction(
            state,
            _event("evt-2", "report-1", ReportStatus.UNDER_REVIEW),
        )

    state = apply_report_correction(
        state,
        _event("evt-3", "report-1", ReportStatus.RETRACTED),
    )
    assert state.status == ReportStatus.RETRACTED


def test_replacement_status_requires_new_report_id():
    with pytest.raises(ValueError, match="replacement_report_id is required"):
        _event("evt-1", "report-1", ReportStatus.CORRECTED)

    with pytest.raises(ValueError, match="must differ"):
        _event(
            "evt-1",
            "report-1",
            ReportStatus.SUPERSEDED,
            replacement="report-1",
        )
