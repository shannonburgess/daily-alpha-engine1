import pytest

from daily_alpha.performance_claims import (
    ClaimChannel,
    ClaimReviewStatus,
    EvidenceBasis,
    MarketingClaim,
    PerformanceEvidence,
    evaluate_customer_claim,
)


def evidence(
    evidence_id="ev-1",
    basis=EvidenceBasis.PAPER,
    assumptions=("Paper fills use recorded bid/ask assumptions.",),
    limitations=("Paper performance is not live performance.",),
):
    return PerformanceEvidence(
        evidence_id=evidence_id,
        basis=basis,
        metric_name="cumulative_return",
        period_start="2026-01-01",
        period_end="2026-08-15",
        as_of="2026-08-15T22:00:00+00:00",
        methodology_version="daily-alpha-v2.4",
        source_hash="a" * 64,
        sample_size=100,
        gross_value=0.22,
        net_value=0.19,
        assumptions=assumptions,
        limitations=limitations,
    )


def claim(
    evidence_ids=("ev-1",),
    displayed_basis=EvidenceBasis.PAPER,
    channel=ClaimChannel.WEBSITE,
    review_status=ClaimReviewStatus.EXTERNAL_REVIEW_COMPLETE,
    external_review_reference="counsel-review-2026-08-15",
):
    return MarketingClaim(
        claim_id="claim-1",
        text="Daily Alpha paper account returned 19% net in the measured period.",
        channel=channel,
        audience="Commercial beta subscribers",
        created_at="2026-08-15T22:00:00+00:00",
        expires_on="2026-09-15",
        evidence_ids=evidence_ids,
        displayed_basis=displayed_basis,
        risks_and_limitations=("Paper results do not represent live client performance.",),
        review_status=review_status,
        external_review_reference=external_review_reference,
    )


def test_customer_claim_passes_only_after_evidence_and_external_review():
    result = evaluate_customer_claim(
        claim=claim(), evidence=(evidence(),), as_of="2026-08-16"
    )
    assert result.allowed is True
    assert result.reasons == (
        "EVIDENCE_GATE_PASSED_EXTERNAL_LEGAL_REVIEW_STILL_REQUIRED",
    )


def test_customer_claim_fails_closed_when_evidence_is_missing():
    result = evaluate_customer_claim(claim=claim(), evidence=(), as_of="2026-08-16")
    assert result.allowed is False
    assert "MISSING_EVIDENCE" in result.reasons


def test_claim_cannot_mix_actual_and_paper_results_under_one_claim():
    result = evaluate_customer_claim(
        claim=claim(evidence_ids=("ev-1", "ev-2")),
        evidence=(
            evidence(),
            evidence("ev-2", EvidenceBasis.ACTUAL),
        ),
        as_of="2026-08-16",
    )
    assert result.allowed is False
    assert "MIXED_PERFORMANCE_BASES" in result.reasons


def test_claim_cannot_mislabel_backtest_as_actual():
    result = evaluate_customer_claim(
        claim=claim(displayed_basis=EvidenceBasis.ACTUAL),
        evidence=(evidence(),),
        as_of="2026-08-16",
    )
    assert result.allowed is False
    assert "MISLABELED_PERFORMANCE_BASIS" in result.reasons


def test_public_claim_requires_external_review_reference():
    result = evaluate_customer_claim(
        claim=claim(
            review_status=ClaimReviewStatus.INTERNAL_EVIDENCE_READY,
            external_review_reference=None,
        ),
        evidence=(evidence(),),
        as_of="2026-08-16",
    )
    assert result.allowed is False
    assert set(result.reasons) >= {
        "EXTERNAL_REVIEW_REQUIRED",
        "EXTERNAL_REVIEW_REFERENCE_REQUIRED",
    }


def test_backtest_evidence_requires_assumptions_and_limitations():
    with pytest.raises(ValueError, match="requires assumptions and limitations"):
        evidence(
            basis=EvidenceBasis.BACKTEST,
            assumptions=(),
            limitations=(),
        )


def test_expired_claim_is_blocked():
    result = evaluate_customer_claim(
        claim=MarketingClaim(
            claim_id="claim-old",
            text="Historical paper result.",
            channel=ClaimChannel.NEWSLETTER,
            audience="Commercial beta subscribers",
            created_at="2026-08-01T22:00:00+00:00",
            expires_on="2026-08-10",
            evidence_ids=("ev-1",),
            displayed_basis=EvidenceBasis.PAPER,
            risks_and_limitations=("Paper results are not live performance.",),
            review_status=ClaimReviewStatus.EXTERNAL_REVIEW_COMPLETE,
            external_review_reference="review-1",
        ),
        evidence=(evidence(),),
        as_of="2026-08-16",
    )
    assert result.allowed is False
    assert "CLAIM_EVIDENCE_EXPIRED" in result.reasons
