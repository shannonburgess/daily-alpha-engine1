from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_change import BehavioralSnapshot
from daily_alpha.behavioral_factors import build_behavioral_research_factors
from daily_alpha.behavioral_recognition import (
    InformationImbalanceResult,
    RecognitionFamily,
    RecognitionStatus,
    WallStreetRecognitionObservation,
    build_information_imbalance,
    build_wall_street_recognition_snapshot,
)

AS_OF = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)


def recognition(
    family: RecognitionFamily,
    score: float,
    *,
    provider_id: str = "provider-a",
    as_of: datetime = AS_OF,
    source_timestamp: datetime | None = None,
) -> WallStreetRecognitionObservation:
    return WallStreetRecognitionObservation(
        ticker="NVDA",
        family=family,
        provider_id=provider_id,
        as_of=as_of,
        source_timestamp=source_timestamp or (as_of - timedelta(minutes=5)),
        score=score,
        provenance=f"research://{provider_id}/{family.value}",
        version="recognition-v1",
    )


def behavioral_snapshot(*, score: float | None = 80.0) -> BehavioralSnapshot:
    return BehavioralSnapshot(
        entity_id="NVDA:2026-08-19-v1",
        ticker="NVDA",
        as_of=AS_OF,
        source_signals=(),
        cross_source_confirmation=100.0,
        behavioral_change_score=score,
        information_imbalance_score=None,
        information_imbalance_reason="WALL_STREET_RECOGNITION_NOT_CONNECTED",
    )


def test_two_independent_recognition_families_enable_information_imbalance():
    snapshot = build_wall_street_recognition_snapshot(
        [
            recognition(RecognitionFamily.ANALYST_REVISIONS, 20.0),
            recognition(RecognitionFamily.CONSENSUS_ESTIMATES, 40.0),
        ],
        ticker="NVDA",
        as_of=AS_OF,
    )
    result = build_information_imbalance(behavioral_snapshot(), snapshot)

    assert snapshot.status == RecognitionStatus.COMPLETE
    assert snapshot.wall_street_recognition_score == 30.0
    assert snapshot.independent_families == 2
    assert result.unrecognized_fraction == 0.7
    assert result.information_imbalance_score == 56.0
    assert result.formula_version == "BEHAVIOR_X_UNRECOGNIZED_V1"
    assert result.promotion_authorized is False
    assert result.trading_authorized is False
    assert result.live_trading_enabled is False


def test_information_imbalance_can_flow_into_named_research_factor_only():
    wall_street = build_wall_street_recognition_snapshot(
        [
            recognition(RecognitionFamily.ANALYST_REVISIONS, 20.0),
            recognition(RecognitionFamily.CONSENSUS_ESTIMATES, 40.0),
        ],
        ticker="NVDA",
        as_of=AS_OF,
    )
    behavior = behavioral_snapshot()
    imbalance = build_information_imbalance(behavior, wall_street)
    factors = build_behavioral_research_factors(
        behavior,
        information_imbalance=imbalance,
    )

    assert factors.information_imbalance_score == 56.0
    assert "INFORMATION_IMBALANCE_SCORE" not in dict(factors.unavailable_reasons)
    assert factors.research_only is True
    assert factors.trading_authorized is False
    assert factors.live_trading_enabled is False


def test_named_factor_rejects_mismatched_information_imbalance_binding():
    behavior = behavioral_snapshot()
    mismatched = InformationImbalanceResult(
        ticker="AMD",
        as_of=AS_OF,
        behavioral_change_score=80.0,
        wall_street_recognition_score=30.0,
        information_imbalance_score=56.0,
        unrecognized_fraction=0.7,
        reason="",
    )

    with pytest.raises(ValueError, match="information imbalance ticker mismatch"):
        build_behavioral_research_factors(
            behavior,
            information_imbalance=mismatched,
        )


def test_multiple_providers_do_not_overweight_one_recognition_family():
    snapshot = build_wall_street_recognition_snapshot(
        [
            recognition(RecognitionFamily.ANALYST_REVISIONS, 10.0, provider_id="a"),
            recognition(RecognitionFamily.ANALYST_REVISIONS, 30.0, provider_id="b"),
            recognition(RecognitionFamily.CONSENSUS_ESTIMATES, 60.0, provider_id="a"),
        ],
        ticker="NVDA",
        as_of=AS_OF,
    )

    assert snapshot.family_scores == (
        ("ANALYST_REVISIONS", 20.0),
        ("CONSENSUS_ESTIMATES", 60.0),
    )
    assert snapshot.wall_street_recognition_score == 40.0
    assert snapshot.provider_observations == 3


def test_one_recognition_family_fails_closed():
    snapshot = build_wall_street_recognition_snapshot(
        [recognition(RecognitionFamily.ANALYST_REVISIONS, 20.0)],
        ticker="NVDA",
        as_of=AS_OF,
    )
    result = build_information_imbalance(behavioral_snapshot(), snapshot)

    assert snapshot.status == RecognitionStatus.SOURCE_UNAVAILABLE
    assert snapshot.wall_street_recognition_score is None
    assert result.information_imbalance_score is None
    assert result.reason == "INSUFFICIENT_INDEPENDENT_RECOGNITION_FAMILIES"


def test_missing_behavioral_composite_keeps_imbalance_unavailable():
    snapshot = build_wall_street_recognition_snapshot(
        [
            recognition(RecognitionFamily.ANALYST_REVISIONS, 20.0),
            recognition(RecognitionFamily.CONSENSUS_ESTIMATES, 40.0),
        ],
        ticker="NVDA",
        as_of=AS_OF,
    )
    result = build_information_imbalance(behavioral_snapshot(score=None), snapshot)

    assert result.information_imbalance_score is None
    assert result.reason == "BEHAVIORAL_CHANGE_SCORE_UNAVAILABLE"


def test_recognition_observation_rejects_lookahead():
    with pytest.raises(ValueError, match="source_timestamp cannot be after as_of"):
        recognition(
            RecognitionFamily.ANALYST_REVISIONS,
            20.0,
            source_timestamp=AS_OF + timedelta(seconds=1),
        )


def test_snapshot_does_not_carry_prior_recognition_forward():
    prior = recognition(
        RecognitionFamily.ANALYST_REVISIONS,
        20.0,
        as_of=AS_OF - timedelta(days=1),
    )
    snapshot = build_wall_street_recognition_snapshot(
        [prior],
        ticker="NVDA",
        as_of=AS_OF,
    )

    assert snapshot.provider_observations == 0
    assert snapshot.independent_families == 0
    assert snapshot.status == RecognitionStatus.SOURCE_UNAVAILABLE


def test_conflicting_duplicate_recognition_observations_fail_closed():
    first = recognition(RecognitionFamily.ANALYST_REVISIONS, 20.0)
    second = WallStreetRecognitionObservation(
        ticker=first.ticker,
        family=first.family,
        provider_id=first.provider_id,
        as_of=first.as_of,
        source_timestamp=first.source_timestamp,
        score=25.0,
        provenance=first.provenance,
        version=first.version,
    )

    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE_RECOGNITION_OBSERVATION"):
        build_wall_street_recognition_snapshot(
            [first, second],
            ticker="NVDA",
            as_of=AS_OF,
        )


def test_information_imbalance_requires_exact_ticker_and_timestamp_binding():
    snapshot = build_wall_street_recognition_snapshot(
        [
            recognition(RecognitionFamily.ANALYST_REVISIONS, 20.0),
            recognition(RecognitionFamily.CONSENSUS_ESTIMATES, 40.0),
        ],
        ticker="NVDA",
        as_of=AS_OF,
    )
    mismatched = snapshot.__class__(
        ticker="AMD",
        as_of=snapshot.as_of,
        status=snapshot.status,
        reason=snapshot.reason,
        family_scores=snapshot.family_scores,
        independent_families=snapshot.independent_families,
        provider_observations=snapshot.provider_observations,
        wall_street_recognition_score=snapshot.wall_street_recognition_score,
    )

    with pytest.raises(ValueError, match="recognition snapshot ticker mismatch"):
        build_information_imbalance(behavioral_snapshot(), mismatched)
