from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from daily_alpha.behavioral_change import BehavioralSource
from daily_alpha.behavioral_orthogonality import CoreFactorFamily, OrthogonalityDiagnostic
from daily_alpha.behavioral_promotion_gate import (
    BehavioralHoldoutOutcomeEvidence,
    BehavioralPromotionCriteria,
    BehavioralValidationWindow,
    evaluate_behavioral_promotion_readiness,
)
from daily_alpha.behavioral_validation import LeadLagObservation, SourceAblationResult


HOLDOUT_START = datetime(2026, 7, 1, tzinfo=UTC)
CUTOFF = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
WINDOW = BehavioralValidationWindow(
    development_end=datetime(2026, 6, 30, 23, 59, tzinfo=UTC),
    holdout_start=HOLDOUT_START,
    holdout_end=datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
    evaluation_cutoff=CUTOFF,
)
CRITERIA = BehavioralPromotionCriteria(
    min_holdout_dates=3,
    min_lead_lag_observations=3,
    min_behavior_lead_fraction=2 / 3,
    max_single_source_score_delta=20.0,
    min_forward_outcome_observations=30,
    min_rank_ic=0.05,
    min_forward_return_spread=0.01,
    max_false_positive_rate=0.40,
)


def _ablation(delta: float = 8.0) -> tuple[SourceAblationResult, ...]:
    return tuple(
        SourceAblationResult(
            omitted_source=source,
            complete_sources_before=3,
            complete_sources_after=2,
            full_score=72.0,
            ablated_score=72.0 - delta,
            score_delta=delta,
            status="COMPLETE",
        )
        for source in (
            BehavioralSource.GOOGLE_TRENDS,
            BehavioralSource.YOUTUBE,
            BehavioralSource.SIMILARWEB,
        )
    )


def _lead_lag(day: int, *, leads: bool = True) -> LeadLagObservation:
    behavioral = HOLDOUT_START + timedelta(days=day)
    recognition = behavioral + timedelta(days=2 if leads else -2)
    return LeadLagObservation(
        ticker="NVDA",
        behavioral_as_of=behavioral,
        recognition_type="OVTLYR_EMERGENCE",
        recognition_known_at=recognition,
        lead_days=2.0 if leads else -2.0,
        relationship=(
            "BEHAVIOR_LEADS_RECOGNITION" if leads else "RECOGNITION_PRECEDES_BEHAVIOR"
        ),
        provenance=f"event-{day}",
    )


def _orthogonality(*, redundant_family: CoreFactorFamily | None = None):
    rows = []
    for family in CoreFactorFamily:
        redundant = family == redundant_family
        rows.append(
            OrthogonalityDiagnostic(
                family=family,
                evaluation_cutoff=CUTOFF,
                paired_observations=20,
                spearman_rank_correlation=0.85 if redundant else 0.25,
                absolute_rank_correlation=0.85 if redundant else 0.25,
                redundancy_threshold=0.80,
                redundancy_risk=redundant,
                status="REDUNDANCY_RISK" if redundant else "ORTHOGONALITY_NOT_REJECTED",
            )
        )
    return tuple(rows)


def _outcomes(**overrides) -> BehavioralHoldoutOutcomeEvidence:
    values = {
        "evaluation_cutoff": CUTOFF,
        "observations": 50,
        "rank_ic": 0.12,
        "forward_return_spread": 0.03,
        "false_positive_rate": 0.25,
        "evidence_id": "holdout-v1",
    }
    values.update(overrides)
    return BehavioralHoldoutOutcomeEvidence(**values)


def _evaluate(**overrides):
    values = {
        "window": WINDOW,
        "criteria": CRITERIA,
        "holdout_dates": (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)),
        "source_ablation_by_date": (_ablation(), _ablation(), _ablation()),
        "lead_lag": (_lead_lag(0), _lead_lag(1), _lead_lag(2)),
        "orthogonality": _orthogonality(),
        "outcomes": _outcomes(),
    }
    values.update(overrides)
    return evaluate_behavioral_promotion_readiness(**values)


def test_ready_only_means_ready_for_separate_governance_review() -> None:
    result = _evaluate()

    assert result.status == "READY_FOR_GOVERNANCE_REVIEW"
    assert result.reasons == ()
    assert result.holdout_dates == 3
    assert result.complete_ablation_dates == 3
    assert result.behavior_lead_fraction == 1.0
    assert result.orthogonality_families_complete == len(CoreFactorFamily)
    assert result.research_only is True
    assert result.promotion_authorized is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_incomplete_ablation_blocks_readiness() -> None:
    incomplete = (
        SourceAblationResult(
            omitted_source=BehavioralSource.YOUTUBE,
            complete_sources_before=2,
            complete_sources_after=1,
            full_score=70.0,
            ablated_score=None,
            score_delta=None,
            status="INSUFFICIENT_INDEPENDENT_SOURCES_AFTER_ABLATION",
        ),
    )
    result = _evaluate(
        source_ablation_by_date=(incomplete, _ablation(), _ablation())
    )

    assert result.status == "EVIDENCE_INCOMPLETE_OR_REJECTED"
    assert "SOURCE_ABLATION_INCOMPLETE" in result.reasons
    assert "INSUFFICIENT_COMPLETE_ABLATION_DATES" in result.reasons


def test_single_source_concentration_and_core_redundancy_are_explicit() -> None:
    result = _evaluate(
        source_ablation_by_date=(_ablation(25.0), _ablation(), _ablation()),
        orthogonality=_orthogonality(redundant_family=CoreFactorFamily.OVTLYR),
    )

    assert "SOURCE_CONCENTRATION_RISK" in result.reasons
    assert "CORE_FACTOR_REDUNDANCY_RISK" in result.reasons
    assert "ORTHOGONALITY_NOT_FULLY_VALIDATED" in result.reasons
    assert result.promotion_authorized is False


def test_holdout_outcomes_and_lead_lag_must_clear_declared_criteria() -> None:
    result = _evaluate(
        lead_lag=(_lead_lag(0, leads=False), _lead_lag(1, leads=False), _lead_lag(2)),
        outcomes=_outcomes(
            observations=20,
            rank_ic=0.01,
            forward_return_spread=-0.01,
            false_positive_rate=0.60,
        ),
    )

    assert "LEAD_LAG_NOT_SUPPORTIVE" in result.reasons
    assert "INSUFFICIENT_FORWARD_OUTCOME_EVIDENCE" in result.reasons
    assert "RANK_IC_THRESHOLD_NOT_MET" in result.reasons
    assert "FORWARD_RETURN_SPREAD_THRESHOLD_NOT_MET" in result.reasons
    assert "FALSE_POSITIVE_RATE_THRESHOLD_NOT_MET" in result.reasons


def test_development_and_holdout_windows_cannot_overlap() -> None:
    with pytest.raises(ValueError, match="BEHAVIORAL_DEVELOPMENT_HOLDOUT_OVERLAP"):
        BehavioralValidationWindow(
            development_end=datetime(2026, 7, 2, tzinfo=UTC),
            holdout_start=datetime(2026, 7, 1, tzinfo=UTC),
            holdout_end=datetime(2026, 7, 31, tzinfo=UTC),
            evaluation_cutoff=datetime(2026, 7, 31, tzinfo=UTC),
        )


def test_future_or_wrong_cutoff_evidence_fails_closed() -> None:
    wrong_cutoff = OrthogonalityDiagnostic(
        family=CoreFactorFamily.OVTLYR,
        evaluation_cutoff=CUTOFF + timedelta(days=1),
        paired_observations=20,
        spearman_rank_correlation=0.2,
        absolute_rank_correlation=0.2,
        redundancy_threshold=0.8,
        redundancy_risk=False,
        status="ORTHOGONALITY_NOT_REJECTED",
    )
    with pytest.raises(ValueError, match="BEHAVIORAL_ORTHOGONALITY_CUTOFF_MISMATCH"):
        _evaluate(orthogonality=(wrong_cutoff, *_orthogonality()[1:]))


def test_duplicate_holdout_dates_fail_closed() -> None:
    with pytest.raises(ValueError, match="BEHAVIORAL_DUPLICATE_HOLDOUT_DATE"):
        _evaluate(
            holdout_dates=(date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 3))
        )
