from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_change import BehavioralSource
from daily_alpha.behavioral_orthogonality import CoreFactorFamily, OrthogonalityDiagnostic
from daily_alpha.behavioral_validation import LeadLagObservation, SourceAblationResult
from daily_alpha.behavioral_validation_artifacts import write_behavioral_validation_artifact


def _rows() -> tuple[
    datetime,
    datetime,
    tuple[SourceAblationResult, ...],
    tuple[LeadLagObservation, ...],
    tuple[OrthogonalityDiagnostic, ...],
]:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    cutoff = as_of + timedelta(days=2)
    ablation = (
        SourceAblationResult(
            omitted_source=BehavioralSource.YOUTUBE,
            complete_sources_before=3,
            complete_sources_after=2,
            full_score=72.0,
            ablated_score=66.0,
            score_delta=6.0,
            status="COMPLETE",
        ),
        SourceAblationResult(
            omitted_source=BehavioralSource.GOOGLE_TRENDS,
            complete_sources_before=3,
            complete_sources_after=2,
            full_score=72.0,
            ablated_score=69.0,
            score_delta=3.0,
            status="COMPLETE",
        ),
    )
    lead_lag = (
        LeadLagObservation(
            ticker="NVDA",
            behavioral_as_of=as_of,
            recognition_type="OVTLYR_EMERGENCE",
            recognition_known_at=as_of + timedelta(days=1),
            lead_days=1.0,
            relationship="BEHAVIOR_LEADS_RECOGNITION",
            provenance="ovtlyr:2026-08-21",
        ),
    )
    orthogonality = (
        OrthogonalityDiagnostic(
            family=CoreFactorFamily.OVTLYR,
            evaluation_cutoff=cutoff,
            paired_observations=40,
            spearman_rank_correlation=0.21,
            absolute_rank_correlation=0.21,
            redundancy_threshold=0.8,
            redundancy_risk=False,
            status="ORTHOGONALITY_NOT_REJECTED",
        ),
        OrthogonalityDiagnostic(
            family=CoreFactorFamily.EARNINGS_REVISIONS,
            evaluation_cutoff=cutoff,
            paired_observations=40,
            spearman_rank_correlation=-0.17,
            absolute_rank_correlation=0.17,
            redundancy_threshold=0.8,
            redundancy_risk=False,
            status="ORTHOGONALITY_NOT_REJECTED",
        ),
    )
    return as_of, cutoff, ablation, lead_lag, orthogonality


def test_validation_artifact_is_order_independent_and_idempotent(tmp_path) -> None:
    as_of, cutoff, ablation, lead_lag, orthogonality = _rows()
    first = write_behavioral_validation_artifact(
        tmp_path,
        entity_id="nvda",
        ticker="NVDA",
        behavioral_as_of=as_of,
        evaluation_cutoff=cutoff,
        source_ablation=ablation,
        lead_lag=lead_lag,
        orthogonality=orthogonality,
    )
    second = write_behavioral_validation_artifact(
        tmp_path,
        entity_id="nvda",
        ticker="NVDA",
        behavioral_as_of=as_of,
        evaluation_cutoff=cutoff,
        source_ablation=tuple(reversed(ablation)),
        lead_lag=tuple(reversed(lead_lag)),
        orthogonality=tuple(reversed(orthogonality)),
    )

    assert first.sha256 == second.sha256
    assert first.path == second.path
    payload = first.path.read_text()
    assert '"promotion_authorized": false' in payload
    assert '"trading_authorized": false' in payload
    assert '"live_trading_enabled": false' in payload


def test_validation_artifact_rejects_lead_lag_lookahead(tmp_path) -> None:
    as_of, cutoff, ablation, _, orthogonality = _rows()
    future = LeadLagObservation(
        ticker="NVDA",
        behavioral_as_of=as_of,
        recognition_type="ANALYST_REVISION",
        recognition_known_at=cutoff + timedelta(seconds=1),
        lead_days=2.000012,
        relationship="BEHAVIOR_LEADS_RECOGNITION",
        provenance="analyst:future",
    )

    with pytest.raises(ValueError, match="LEAD_LAG_LOOKAHEAD_REJECTED"):
        write_behavioral_validation_artifact(
            tmp_path,
            entity_id="nvda",
            ticker="NVDA",
            behavioral_as_of=as_of,
            evaluation_cutoff=cutoff,
            source_ablation=ablation,
            lead_lag=(future,),
            orthogonality=orthogonality,
        )


def test_validation_artifact_rejects_safety_drift(tmp_path) -> None:
    as_of, cutoff, ablation, lead_lag, orthogonality = _rows()
    unsafe = OrthogonalityDiagnostic(
        family=CoreFactorFamily.SECTOR_ROTATION,
        evaluation_cutoff=cutoff,
        paired_observations=40,
        spearman_rank_correlation=0.1,
        absolute_rank_correlation=0.1,
        redundancy_threshold=0.8,
        redundancy_risk=False,
        status="ORTHOGONALITY_NOT_REJECTED",
        trading_authorized=True,
    )

    with pytest.raises(ValueError, match="TRADING_AUTHORIZATION_REJECTED"):
        write_behavioral_validation_artifact(
            tmp_path,
            entity_id="nvda",
            ticker="NVDA",
            behavioral_as_of=as_of,
            evaluation_cutoff=cutoff,
            source_ablation=ablation,
            lead_lag=lead_lag,
            orthogonality=(*orthogonality, unsafe),
        )


def test_validation_artifact_rejects_conflicting_rewrite(tmp_path) -> None:
    as_of, cutoff, ablation, lead_lag, orthogonality = _rows()
    write_behavioral_validation_artifact(
        tmp_path,
        entity_id="nvda",
        ticker="NVDA",
        behavioral_as_of=as_of,
        evaluation_cutoff=cutoff,
        source_ablation=ablation,
        lead_lag=lead_lag,
        orthogonality=orthogonality,
    )
    changed = OrthogonalityDiagnostic(
        family=CoreFactorFamily.OVTLYR,
        evaluation_cutoff=cutoff,
        paired_observations=40,
        spearman_rank_correlation=0.79,
        absolute_rank_correlation=0.79,
        redundancy_threshold=0.8,
        redundancy_risk=False,
        status="ORTHOGONALITY_NOT_REJECTED",
    )

    with pytest.raises(ValueError, match="IMMUTABILITY_VIOLATION"):
        write_behavioral_validation_artifact(
            tmp_path,
            entity_id="nvda",
            ticker="NVDA",
            behavioral_as_of=as_of,
            evaluation_cutoff=cutoff,
            source_ablation=ablation,
            lead_lag=lead_lag,
            orthogonality=(changed, orthogonality[1]),
        )
