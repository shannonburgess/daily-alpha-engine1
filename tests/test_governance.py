import pytest

from daily_alpha.governance import (
    GovernedVersion,
    StrategyGovernance,
    StrategyVersion,
    VersionStatus,
)

RULE_HASH = "a" * 64


def draft():
    return GovernedVersion(
        StrategyVersion(
            "daily-alpha-v2",
            "Daily Alpha",
            RULE_HASH,
            "2026-08-15T20:00:00+00:00",
            parent_version_id="daily-alpha-v1",
            change_summary="Add regime validation.",
        )
    )


def validated():
    return StrategyGovernance().record_validation(
        draft(),
        validation_report_id="validation-123",
        eligible_for_paper=True,
        occurred_at="2026-08-15T21:00:00+00:00",
    )


def test_failed_validation_cannot_advance_strategy():
    with pytest.raises(ValueError, match="failed validation"):
        StrategyGovernance().record_validation(
            draft(),
            validation_report_id="failed-1",
            eligible_for_paper=False,
            occurred_at="2026-08-15T21:00:00+00:00",
        )


def test_paper_approval_requires_validation_and_named_approver():
    with pytest.raises(ValueError, match="validated"):
        StrategyGovernance().approve_for_paper(
            draft(), approved_by="Shannon", approved_at="2026-08-15T22:00:00+00:00"
        )
    with pytest.raises(ValueError, match="approver"):
        StrategyGovernance().approve_for_paper(
            validated(), approved_by="", approved_at="2026-08-15T22:00:00+00:00"
        )


def test_validated_version_can_be_approved_for_paper_with_audit_events():
    result = StrategyGovernance().approve_for_paper(
        validated(), approved_by="Shannon", approved_at="2026-08-15T22:00:00+00:00"
    )
    assert result.paper_eligible is True
    assert result.version.status == VersionStatus.PAPER_APPROVED
    assert result.version.validation_report_id == "validation-123"
    assert [event.event_id for event in result.events] == [
        "daily-alpha-v2:1",
        "daily-alpha-v2:2",
    ]


def test_retirement_is_audited_and_irreversible():
    governance = StrategyGovernance()
    approved = governance.approve_for_paper(
        validated(), approved_by="Shannon", approved_at="2026-08-15T22:00:00+00:00"
    )
    retired = governance.retire(
        approved,
        actor="Shannon",
        occurred_at="2026-09-01T12:00:00+00:00",
        reason="SUPERSEDED_BY_V3",
    )
    assert retired.version.status == VersionStatus.RETIRED
    with pytest.raises(ValueError, match="already retired"):
        governance.retire(
            retired,
            actor="Shannon",
            occurred_at="2026-09-02T12:00:00+00:00",
            reason="DUPLICATE",
        )


def test_rule_hash_must_be_sha256():
    with pytest.raises(ValueError, match="SHA-256"):
        StrategyVersion("v", "name", "bad", "2026-08-15T20:00:00+00:00")
