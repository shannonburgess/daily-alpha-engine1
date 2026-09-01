from daily_alpha.factor_attribution import (
    FactorReturnObservation,
    FactorVector,
    ablation_delta,
    evaluate_factor,
    score_factor_vector,
)


def test_factor_score_exposes_normalized_contributions_without_authorizing_trade():
    score = score_factor_vector(
        FactorVector(
            symbol="AMD",
            as_of="2026-08-19T20:00:00+00:00",
            factors={
                "momentum": 0.8,
                "relative_strength": 0.6,
                "trendability": 0.4,
            },
        ),
        weights={
            "momentum": 2.0,
            "relative_strength": 1.0,
            "trendability": 1.0,
        },
    )

    assert score.score == 0.65
    by_factor = {item.factor: item for item in score.contributions}
    assert by_factor["momentum"].weight == 0.5
    assert by_factor["momentum"].contribution == 0.4
    assert score.research_only is True
    assert score.trading_authorized is False
    assert score.live_trading_enabled is False


def test_factor_evidence_detects_monotonic_cross_sectional_edge():
    observations = [
        FactorReturnObservation(
            symbol=f"S{index}",
            factor="momentum",
            factor_value=value,
            forward_return=value * 0.10,
            as_of="2026-08-19",
            horizon_bars=20,
        )
        for index, value in enumerate((-0.9, -0.5, -0.1, 0.2, 0.6, 0.9))
    ]

    evidence = evaluate_factor(observations, minimum_sample=5)

    assert evidence.observations == 6
    assert evidence.rank_ic == 1.0
    assert evidence.high_minus_low_return is not None
    assert evidence.high_minus_low_return > 0
    assert evidence.sufficient_sample is True
    assert evidence.research_only is True
    assert evidence.trading_authorized is False


def test_factor_evidence_does_not_hide_insufficient_sample():
    observations = [
        FactorReturnObservation(
            symbol="AAA",
            factor="relative_strength",
            factor_value=-0.5,
            forward_return=-0.02,
            as_of="2026-08-19",
            horizon_bars=10,
        ),
        FactorReturnObservation(
            symbol="BBB",
            factor="relative_strength",
            factor_value=0.5,
            forward_return=0.03,
            as_of="2026-08-19",
            horizon_bars=10,
        ),
    ]

    evidence = evaluate_factor(observations, minimum_sample=30)

    assert evidence.rank_ic == 1.0
    assert evidence.sufficient_sample is False


def test_ablation_delta_is_labeled_incremental_evidence_only():
    result = ablation_delta(
        full_metric=1.25,
        without_factor_metric=1.10,
        factor="liquidity_capacity",
    )

    assert result["delta"] == 0.15
    assert result["interpretation"] == "INCREMENTAL_EVIDENCE_ONLY"
    assert result["research_only"] is True
    assert result["trading_authorized"] is False
