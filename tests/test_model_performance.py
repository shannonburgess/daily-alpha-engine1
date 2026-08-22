# ruff: noqa: I001
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.cio_fusion import QuantModelView
from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.model_governance import (
    ModelDefinition,
    ModelGovernanceEngine,
    ModelGovernancePolicy,
    ModelLifecycleStage,
    ModelRegistry,
    ModelValidationRecord,
)
from daily_alpha.agentic.model_performance import (
    ModelOutcomeRecord,
    ModelPerformanceEngine,
    ModelPerformanceError,
    ModelPerformancePolicy,
)
from daily_alpha.agentic.model_stress import (
    ModelStressEngine,
    ModelStressResult,
    StressScenarioClass,
    StressScenarioDefinition,
    StressScenarioRegistry,
)


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _view() -> QuantModelView:
    return QuantModelView(
        security_id="SEC-AAPL",
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        as_of=AS_OF,
        status=ReadinessStatus.PASS,
        signal_label="LONG_BIAS",
        score=64,
        confidence=0.84,
        input_lineage_ids=("feature-a", "market-b"),
    )


def _validation(*, expectancy_r: float = 0.24, sharpe: float = 1.40) -> ModelValidationRecord:
    known = AS_OF - timedelta(days=2)
    return ModelValidationRecord(
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        as_of=known,
        window_start=known - timedelta(days=365),
        window_end=known - timedelta(days=1),
        sample_size=180,
        expectancy_r=expectancy_r,
        sharpe=sharpe,
        sortino=1.85,
        max_drawdown=0.11,
        profit_factor=1.48,
        stability_score=0.86,
        input_lineage_ids=("backtest-a", "holdout-b"),
    )


def _governance(validation: ModelValidationRecord | None = None):
    active = validation or _validation()
    registry = ModelRegistry(
        (
            ModelDefinition(
                model_id="R2_MOMENTUM",
                model_version="1.0.0",
                owner="Daily Alpha Quant Research",
                stage=ModelLifecycleStage.SHADOW,
                effective_at=AS_OF - timedelta(days=400),
            ),
        )
    )
    return ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(),),
        validations=(active,),
        policy=ModelGovernancePolicy(
            min_sample_size=100,
            min_expectancy_r=0.10,
            min_sharpe=1.0,
            min_sortino=1.2,
            max_drawdown=0.15,
            min_profit_factor=1.25,
            min_stability_score=0.70,
        ),
    )


def _scenarios() -> tuple[StressScenarioDefinition, ...]:
    classes = (
        StressScenarioClass.HISTORICAL_SHOCK,
        StressScenarioClass.TREND_DOWN,
        StressScenarioClass.HIGH_VOLATILITY,
        StressScenarioClass.LIQUIDITY_STRESS,
        StressScenarioClass.MACRO_SHOCK,
    )
    return tuple(
        StressScenarioDefinition(
            scenario_id=f"FIXTURE_{scenario_class.value}",
            scenario_version="1.0",
            scenario_class=scenario_class,
            effective_at=AS_OF - timedelta(days=300),
        )
        for scenario_class in classes
    )


def _stress_result(
    scenario: StressScenarioDefinition,
    *,
    expectancy_r: float = 0.05,
) -> ModelStressResult:
    known = AS_OF - timedelta(days=1)
    return ModelStressResult(
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        known_at=known,
        window_start=known - timedelta(days=180),
        window_end=known - timedelta(days=1),
        sample_size=90,
        expectancy_r=expectancy_r,
        sharpe=0.25,
        max_drawdown=0.22,
        worst_loss_r=-1.8,
        recovery_periods=14,
        capacity_retention=0.72,
        stability_score=0.68,
        input_lineage_ids=("stress-data-a", scenario.scenario_id.lower()),
    )


def _stress_packet(governance, *, block: bool = False):
    scenarios = _scenarios()
    results = tuple(
        _stress_result(item, expectancy_r=(-0.80 if block and index == 0 else 0.05))
        for index, item in enumerate(scenarios)
    )
    return ModelStressEngine(scenario_registry=StressScenarioRegistry(scenarios)).evaluate(
        governance_packet=governance,
        views=(_view(),),
        results=results,
    )


def _outcome(
    index: int,
    realized_r: float,
    *,
    known_at: datetime | None = None,
    model_id: str = "R2_MOMENTUM",
) -> ModelOutcomeRecord:
    end = AS_OF - timedelta(days=(index % 80) + 1)
    known = known_at or end + timedelta(hours=2)
    return ModelOutcomeRecord(
        security_id=f"SEC-{index:04d}",
        model_view_id=f"historical-model-view-{index:04d}",
        model_id=model_id,
        model_version="1.0.0",
        known_at=known,
        measurement_start=end - timedelta(hours=6),
        measurement_end=end,
        realized_r=realized_r,
        realized_return=realized_r * 0.01,
        fees_bps=2.0,
        input_lineage_ids=(f"outcome-source-{index:04d}", "immutable-scorecard"),
    )


def _good_outcomes(count: int = 40) -> tuple[ModelOutcomeRecord, ...]:
    pattern = (0.5, 0.4, 0.3, -0.2)
    return tuple(_outcome(index, pattern[index % len(pattern)]) for index in range(count))


def _evaluate(
    *,
    outcomes: tuple[ModelOutcomeRecord, ...],
    validation: ModelValidationRecord | None = None,
    block_stress: bool = False,
    policy: ModelPerformancePolicy | None = None,
):
    active_validation = validation or _validation()
    governance = _governance(active_validation)
    stress = _stress_packet(governance, block=block_stress)
    return ModelPerformanceEngine().evaluate(
        governance_packet=governance,
        stress_packet=stress,
        views=(_view(),),
        validations=(active_validation,),
        outcomes=outcomes,
        policy=policy,
    )


def test_healthy_realized_model_performance_is_cio_research_eligible() -> None:
    packet = _evaluate(outcomes=_good_outcomes())
    assessment = packet.assessments[0]

    assert packet.status is ReadinessStatus.PASS
    assert assessment.metrics.sample_size == 40
    assert assessment.metrics.hit_rate == pytest.approx(0.75)
    assert assessment.metrics.expectancy_r == pytest.approx(0.25)
    assert assessment.metrics.profit_factor == pytest.approx(6.0)
    assert assessment.performance_eligible_for_cio_research is True
    packet.assert_views_performance_eligible((_view(),))
    assert packet.paper_ledger_mutation_authorized is False
    assert packet.execution_authorized is False
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False


def test_insufficient_history_is_warning_not_invented_block() -> None:
    packet = _evaluate(outcomes=_good_outcomes(5))
    assessment = packet.assessments[0]

    assert packet.status is ReadinessStatus.WARNING
    assert assessment.performance_eligible_for_cio_research is True
    assert assessment.metrics.sample_size == 5
    assert any("MODEL_PERFORMANCE_HISTORY_INSUFFICIENT" in item for item in assessment.warnings)


def test_material_realized_decay_blocks_model_research_eligibility() -> None:
    outcomes = tuple(_outcome(index, -0.30) for index in range(35))
    packet = _evaluate(outcomes=outcomes)
    assessment = packet.assessments[0]

    assert packet.status is ReadinessStatus.BLOCKED
    assert assessment.performance_eligible_for_cio_research is False
    assert any("MODEL_HIT_RATE_BELOW_POLICY" in item for item in assessment.blockers)
    assert any("MODEL_EXPECTANCY_BELOW_POLICY" in item for item in assessment.blockers)
    assert any("MODEL_EXPECTANCY_DECAY_ABOVE_POLICY" in item for item in assessment.blockers)
    assert any("MODEL_LOSS_STREAK_ABOVE_POLICY" in item for item in assessment.blockers)


def test_future_outcomes_cannot_repair_historical_surveillance() -> None:
    known = _good_outcomes(5)
    future = tuple(
        _outcome(
            100 + index,
            1.0,
            known_at=AS_OF + timedelta(days=1),
        )
        for index in range(30)
    )
    packet = _evaluate(outcomes=known + future)

    assert packet.assessments[0].metrics.sample_size == 5
    assert packet.status is ReadinessStatus.WARNING
    assert not ({item.outcome_id for item in future} & set(packet.assessments[0].metrics.outcome_ids))


def test_outcomes_outside_rolling_lookback_are_excluded() -> None:
    old_end = AS_OF - timedelta(days=120)
    old = ModelOutcomeRecord(
        security_id="SEC-OLD",
        model_view_id="historical-old-view",
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        known_at=old_end + timedelta(hours=2),
        measurement_start=old_end - timedelta(hours=6),
        measurement_end=old_end,
        realized_r=5.0,
        realized_return=0.05,
        fees_bps=1.0,
        input_lineage_ids=("old-source",),
    )
    packet = _evaluate(outcomes=_good_outcomes(5) + (old,))

    assert packet.assessments[0].metrics.sample_size == 5
    assert old.outcome_id not in packet.assessments[0].metrics.outcome_ids


def test_duplicate_and_input_order_do_not_change_packet_identity() -> None:
    outcomes = _good_outcomes()
    first = _evaluate(outcomes=outcomes)
    second = _evaluate(outcomes=tuple(reversed(outcomes)) + (outcomes[0],))

    assert first.packet_id == second.packet_id
    assert first.assessments[0].assessment_id == second.assessments[0].assessment_id
    assert first.assessments[0].metrics.metrics_id == second.assessments[0].metrics.metrics_id


def test_upstream_stress_block_cannot_be_repaired_by_good_realized_performance() -> None:
    packet = _evaluate(outcomes=_good_outcomes(), block_stress=True)

    assert packet.status is ReadinessStatus.BLOCKED
    assert "UPSTREAM_MODEL_STRESS_BLOCKED" in packet.assessments[0].blockers
    with pytest.raises(ModelPerformanceError, match="MODEL_VIEW_NOT_PERFORMANCE_ELIGIBLE"):
        packet.assert_views_performance_eligible((_view(),))


def test_exact_stage_9g_validation_baseline_is_required() -> None:
    validation = _validation()
    governance = _governance(validation)
    stress = _stress_packet(governance)

    with pytest.raises(ModelPerformanceError, match="BASELINE_VALIDATION_NOT_AVAILABLE"):
        ModelPerformanceEngine().evaluate(
            governance_packet=governance,
            stress_packet=stress,
            views=(_view(),),
            validations=(),
            outcomes=_good_outcomes(),
        )


def test_no_loss_window_uses_unbounded_profit_factor_without_nonfinite_value() -> None:
    outcomes = tuple(_outcome(index, 0.20) for index in range(30))
    packet = _evaluate(outcomes=outcomes)

    assert packet.status is ReadinessStatus.PASS
    assert packet.assessments[0].metrics.profit_factor is None


def test_model_outcome_contract_cannot_mutate_paper_or_claim_execution_authority() -> None:
    outcome = _outcome(1, 0.5)

    with pytest.raises(ModelPerformanceError, match="MUST_REMAIN_RESEARCH_ONLY"):
        replace(outcome, paper_ledger_mutation_authorized=True)
    with pytest.raises(ModelPerformanceError, match="MUST_REMAIN_RESEARCH_ONLY"):
        replace(outcome, execution_authorized=True)
    with pytest.raises(ModelPerformanceError, match="MUST_REMAIN_RESEARCH_ONLY"):
        replace(outcome, live_trading_enabled=True)


def test_model_outcome_requires_point_in_time_measurement_integrity() -> None:
    outcome = _outcome(1, 0.5)

    with pytest.raises(ModelPerformanceError, match="MEASUREMENT_END_AFTER_KNOWN_AT"):
        replace(outcome, measurement_end=outcome.known_at + timedelta(seconds=1))


def test_outcomes_for_other_model_versions_do_not_contaminate_metrics() -> None:
    other = tuple(_outcome(100 + index, 10.0, model_id="OTHER_MODEL") for index in range(30))
    packet = _evaluate(outcomes=_good_outcomes(5) + other)

    assert packet.assessments[0].metrics.sample_size == 5
    assert packet.status is ReadinessStatus.WARNING
