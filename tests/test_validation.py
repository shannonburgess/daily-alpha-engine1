import pytest

from daily_alpha.validation import (
    PromotionDecision,
    ReturnObservation,
    Sample,
    ValidationPolicy,
    WalkForwardFold,
    validate_strategy,
)

FOLDS = (WalkForwardFold("f1", "2025-01-01", "2025-06-30", "2025-07-01", "2025-12-31"),)


def observation(index, strategy, benchmark=0.0, regime="RISK_ON", sample=Sample.TEST):
    return ReturnObservation(
        f"2025-08-{index + 1:02d}", strategy, benchmark, regime, sample
    )


def test_overlapping_train_and_test_window_is_rejected():
    with pytest.raises(ValueError, match="overlap"):
        WalkForwardFold("bad", "2025-01-01", "2025-07-02", "2025-07-01", "2025-12-31")


def test_in_sample_strength_cannot_override_insufficient_test_history():
    records = tuple(
        [observation(i, 0.05, sample=Sample.TRAIN) for i in range(10)]
        + [observation(i + 10, 0.01) for i in range(5)]
    )
    report = validate_strategy(strategy_version="v1", observations=records, folds=FOLDS)
    assert report.decision == PromotionDecision.HOLD_RESEARCH
    assert "INSUFFICIENT_OUT_OF_SAMPLE_HISTORY" in report.reasons


def test_negative_benchmark_relative_test_results_block_promotion():
    records = tuple(observation(i, 0.001, benchmark=0.002) for i in range(30))
    report = validate_strategy(strategy_version="v1", observations=records, folds=FOLDS)
    assert report.decision == PromotionDecision.HOLD_RESEARCH
    assert "OUT_OF_SAMPLE_EXCESS_RETURN_NOT_POSITIVE" in report.reasons


def test_drawdown_blocks_promotion_even_with_positive_average():
    returns = [0.03] * 29 + [-0.20]
    records = tuple(observation(i, value) for i, value in enumerate(returns))
    report = validate_strategy(strategy_version="v1", observations=records, folds=FOLDS)
    assert "OUT_OF_SAMPLE_DRAWDOWN_LIMIT" in report.reasons


def test_robust_out_of_sample_results_are_eligible_for_paper_only():
    records = tuple(
        observation(i, 0.01, benchmark=0.002, regime="RISK_ON" if i % 2 else "RISK_OFF")
        for i in range(30)
    )
    report = validate_strategy(strategy_version="v2", observations=records, folds=FOLDS)
    assert report.decision == PromotionDecision.ELIGIBLE_FOR_PAPER
    assert report.test_observations == 30
    assert len(report.regime_mean_excess) == 2


def test_policy_validation():
    with pytest.raises(ValueError, match="positive"):
        ValidationPolicy(minimum_test_observations=0)
