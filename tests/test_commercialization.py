import pytest

from daily_alpha.commercialization import (
    REQUIRED_CONTROLS,
    ComplianceReadiness,
    ComplianceStatus,
    PerformanceBasis,
    PublicationArchive,
    RecommendationAction,
    RecommendationRecord,
    RecommendationState,
    ValuationReconciliation,
    gate_commercialization,
)


def recommendation(
    recommendation_id="rec-1",
    action=RecommendationAction.ENTER,
    state=RecommendationState.OPEN,
    instrument="OPTION",
    basis=PerformanceBasis.PAPER,
):
    return RecommendationRecord(
        recommendation_id=recommendation_id,
        decision_id=f"decision-{recommendation_id}",
        as_of="2026-08-15T14:30:00-07:00",
        symbol="AAPL",
        action=action,
        state=state,
        reason_codes=("PINE_ENTRY", "RISK_APPROVED"),
        instrument=instrument,
        instrument_reason="Qualified option passed ORATS quality controls.",
        entry=2.5 if action == RecommendationAction.ENTER else None,
        invalidation=1.5 if action == RecommendationAction.ENTER else None,
        targets=(4.0,) if action == RecommendationAction.ENTER else (),
        horizon="10-20 trading days",
        planned_loss=1000,
        expected_reward=1500,
        confidence=0.72,
        performance_basis=basis,
        gross_pnl=500,
        fees=5,
        slippage=10,
    )


def publication(records=None, disclaimer=None):
    values = records or (recommendation(),)
    kwargs = {}
    if disclaimer is not None:
        kwargs["disclaimer"] = disclaimer
    return PublicationArchive(
        publication_id="pub-2026-08-15",
        report_date="2026-08-15",
        generated_at="2026-08-15T22:00:00+00:00",
        canonical_run_id="run-123",
        methodology_version="daily-alpha-v3",
        records=values,
        changes_since_yesterday=("AAPL entered ENTRY_WATCH",),
        **kwargs,
    )


def test_publication_is_immutable_reproducible_and_net_of_costs():
    first = publication()
    second = publication()
    assert first.archive_hash == second.archive_hash
    assert first.performance_by_basis["PAPER"]["gross_pnl"] == 500
    assert first.performance_by_basis["PAPER"]["net_pnl"] == 485


def test_publication_cannot_mislabel_paper_as_live():
    with pytest.raises(ValueError, match="distinguish"):
        publication(disclaimer="Verified live performance.")


def test_cancelled_and_rejected_history_must_be_retained():
    archive = publication(
        (
            recommendation(),
            recommendation(
                "rec-2",
                RecommendationAction.REJECT,
                RecommendationState.REJECTED,
                "NO_TRADE",
            ),
        )
    )
    archive.validate_complete_history(("rec-1", "rec-2"))
    with pytest.raises(ValueError, match="omitted"):
        publication().validate_complete_history(("rec-1", "rec-2"))


def test_commercialization_is_blocked_without_compliance_and_reconciliation():
    allowed, reasons = gate_commercialization(
        readiness=ComplianceReadiness(ComplianceStatus.NOT_READY, frozenset()),
        reconciliation=ValuationReconciliation(
            "2026-08-15T22:00:00+00:00", 1_000_000, 990_000, 100, "ADMIN"
        ),
        publication=publication(),
        canonical_ids=("rec-1", "rec-2"),
    )
    assert allowed is False
    assert set(reasons) == {
        "INCOMPLETE_TRACK_RECORD",
        "NAV_RECONCILIATION_FAILED",
        "COMPLIANCE_NOT_APPROVED",
    }


def test_completed_controls_and_independent_nav_allow_formal_review_gate():
    readiness = ComplianceReadiness(
        ComplianceStatus.APPROVED,
        REQUIRED_CONTROLS,
        approved_by="Independent compliance reviewer",
        approved_at="2026-08-15T22:00:00+00:00",
    )
    reconciliation = ValuationReconciliation(
        "2026-08-15T22:00:00+00:00",
        1_000_000,
        1_000_025,
        100,
        "INDEPENDENT_ADMINISTRATOR",
    )
    allowed, reasons = gate_commercialization(
        readiness=readiness,
        reconciliation=reconciliation,
        publication=publication(),
        canonical_ids=("rec-1",),
    )
    assert allowed is True
    assert reasons == ("COMMERCIALIZATION_CONTROLS_PASSED",)
