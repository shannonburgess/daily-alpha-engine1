import pytest

from daily_alpha.research import (
    BacktestTrade,
    ExperimentManifest,
    ExperimentRecord,
    ExperimentRegistry,
    ExperimentStatus,
    ModelRegistryEntry,
    PromotionStage,
    ResearchThresholds,
    assess_parameter_stability,
    compare_challenger,
    grouped_metrics,
    monte_carlo_trade_sequences,
    request_live_promotion,
    require_version_bump_and_review,
    summarize_research,
)


THRESHOLDS = ResearchThresholds(4, 0.1, 1.1, 0.20, 0.75)


def manifest(experiment_id="exp-1"):
    return ExperimentManifest(
        experiment_id=experiment_id,
        strategy_version="daily-alpha-v3",
        code_version="abc123",
        model_version="3.0.0",
        feature_version="features-2",
        data_version="orats-2026-08-15",
        config_version="config-4",
        universe_as_of="2026-08-15",
        train_range=("2024-01-01", "2024-12-31"),
        validation_range=("2025-01-01", "2025-12-31"),
        test_range=("2026-01-01", "2026-08-15"),
        parameters=(("lookback", "20"),),
        thresholds=THRESHOLDS,
        hypothesis="Trend plus options quality improves risk-adjusted return.",
        multiple_testing_disclosure="One of four predeclared variants; no post-hoc selection.",
        created_at="2026-08-15T22:00:00+00:00",
    )


def trade(index, value, instrument="OPTION", regime="RISK_ON"):
    return BacktestTrade(
        trade_id=f"trade-{index}",
        closed_on=f"2026-01-{index + 1:02d}",
        net_pnl=value * 1000,
        capital_deployed=1000,
        benchmark_return=0.001,
        factor_return=0.0005,
        turnover=1.0,
        capacity=100_000,
        mae=-0.02,
        mfe=0.04,
        holding_days=3,
        strategy="TURTLE",
        regime=regime,
        sector="TECH",
        score_band="HIGH",
        instrument=instrument,
    )


def test_manifest_is_reproducible_and_partitions_cannot_overlap():
    assert manifest().manifest_hash == manifest().manifest_hash
    with pytest.raises(ValueError, match="overlap"):
        ExperimentManifest(
            **{
                **manifest().__dict__,
                "validation_range": ("2024-12-31", "2025-12-31"),
            }
        )


def test_failed_experiment_is_retained():
    registry = ExperimentRegistry()
    registry.add(ExperimentRecord(manifest(), ExperimentStatus.FAILED, failure_reason="DATA_GAP"))
    assert registry.records[0].failure_reason == "DATA_GAP"


def test_institutional_metrics_and_grouping_are_reported():
    records = tuple(
        trade(i, value, instrument="OPTION" if i % 2 else "STOCK")
        for i, value in enumerate((0.03, -0.01, 0.02, 0.01))
    )
    summary = summarize_research(records)
    assert summary.trades == 4
    assert summary.hit_rate == 0.75
    assert summary.profit_factor == pytest.approx(6.0)
    assert summary.benchmark_alpha > 0
    assert set(grouped_metrics(records, "instrument")) == {"OPTION", "STOCK"}


def test_seeded_monte_carlo_is_reproducible():
    first = monte_carlo_trade_sequences((0.03, -0.02, 0.01), simulations=100, seed=7)
    second = monte_carlo_trade_sequences((0.03, -0.02, 0.01), simulations=100, seed=7)
    assert first == second


def test_parameter_instability_and_drawdown_block_headline_return_promotion():
    champion = summarize_research(
        tuple(trade(i, value) for i, value in enumerate((0.01, 0.01, 0.01, 0.01)))
    )
    challenger = summarize_research(
        tuple(trade(i, value) for i, value in enumerate((0.50, -0.40, 0.50, -0.20)))
    )
    unstable = assess_parameter_stability(
        (0.5, -0.5, 0.4, -0.4),
        minimum_positive_share=0.75,
        maximum_range=0.5,
    )
    decision = compare_challenger(
        champion=champion,
        challenger=challenger,
        stability=unstable,
        thresholds=THRESHOLDS,
    )
    assert decision.approved is False
    assert "PARAMETER_INSTABILITY" in decision.reasons
    assert "DRAWDOWN_ABOVE_THRESHOLD" in decision.reasons


def test_model_change_requires_version_bump_and_review():
    common = dict(
        model_id="daily-alpha",
        strategy_version="v3",
        feature_version="f1",
        data_version="d1",
        config_version="c1",
        experiment_id="exp-1",
        reviewed_by="Shannon",
    )
    previous = ModelRegistryEntry(model_version="3.0.0", **common)
    with pytest.raises(ValueError, match="version bump"):
        require_version_bump_and_review(
            previous, ModelRegistryEntry(model_version="3.0.0", **common)
        )
    require_version_bump_and_review(previous, ModelRegistryEntry(model_version="3.1.0", **common))


def test_live_promotion_is_always_disabled():
    decision = request_live_promotion()
    assert decision.stage == PromotionStage.LIVE_DISABLED
    assert decision.approved is False
