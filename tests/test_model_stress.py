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
from daily_alpha.agentic.model_stress import (
    ModelStressEngine,
    ModelStressError,
    ModelStressPolicy,
    ModelStressResult,
    StressScenarioClass,
    StressScenarioDefinition,
    StressScenarioRegistry,
)


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _view(*, as_of: datetime = AS_OF, status: ReadinessStatus = ReadinessStatus.PASS) -> QuantModelView:
    return QuantModelView(
        security_id="SEC-AAPL",
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        as_of=as_of,
        status=status,
        signal_label="LONG_BIAS" if status is not ReadinessStatus.BLOCKED else "BLOCKED",
        score=64 if status is not ReadinessStatus.BLOCKED else None,
        confidence=0.84 if status is not ReadinessStatus.BLOCKED else 0.0,
        input_lineage_ids=("feature-bundle-a", "market-state-b"),
    )


def _definition() -> ModelDefinition:
    return ModelDefinition(
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        owner="Daily Alpha Quant Research",
        stage=ModelLifecycleStage.SHADOW,
        effective_at=AS_OF - timedelta(days=400),
    )


def _validation(*, sharpe: float = 1.40) -> ModelValidationRecord:
    known = AS_OF - timedelta(hours=2)
    return ModelValidationRecord(
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        as_of=known,
        window_start=known - timedelta(days=365),
        window_end=known - timedelta(days=1),
        sample_size=180,
        expectancy_r=0.24,
        sharpe=sharpe,
        sortino=1.85,
        max_drawdown=0.11,
        profit_factor=1.48,
        stability_score=0.86,
        input_lineage_ids=("backtest-snapshot-a", "holdout-snapshot-b"),
    )


def _governance_packet(*, view: QuantModelView | None = None, sharpe: float = 1.40):
    active_view = view or _view()
    return ModelGovernanceEngine(registry=ModelRegistry((_definition(),))).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(active_view,),
        validations=(_validation(sharpe=sharpe),),
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


def _scenario(
    scenario_id: str,
    scenario_class: StressScenarioClass,
    *,
    effective_at: datetime = AS_OF - timedelta(days=300),
) -> StressScenarioDefinition:
    return StressScenarioDefinition(
        scenario_id=scenario_id,
        scenario_version="1.0",
        scenario_class=scenario_class,
        effective_at=effective_at,
        description=f"Fixture {scenario_class.value}",
    )


def _scenarios() -> tuple[StressScenarioDefinition, ...]:
    return (
        _scenario("COVID_GAP", StressScenarioClass.HISTORICAL_SHOCK),
        _scenario("BEAR_TREND", StressScenarioClass.TREND_DOWN),
        _scenario("VOL_SPIKE", StressScenarioClass.HIGH_VOLATILITY),
        _scenario("LIQUIDITY_DRAIN", StressScenarioClass.LIQUIDITY_STRESS),
        _scenario("RATE_SHOCK", StressScenarioClass.MACRO_SHOCK),
    )


def _result(
    scenario: StressScenarioDefinition,
    *,
    known_at: datetime = AS_OF - timedelta(hours=1),
    expectancy_r: float = 0.05,
    sharpe: float = 0.25,
    max_drawdown: float = 0.22,
    worst_loss_r: float = -1.8,
    recovery_periods: int = 14,
    capacity_retention: float = 0.72,
    stability_score: float = 0.68,
) -> ModelStressResult:
    return ModelStressResult(
        model_id="R2_MOMENTUM",
        model_version="1.0.0",
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        known_at=known_at,
        window_start=known_at - timedelta(days=180),
        window_end=known_at - timedelta(days=1),
        sample_size=90,
        expectancy_r=expectancy_r,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        worst_loss_r=worst_loss_r,
        recovery_periods=recovery_periods,
        capacity_retention=capacity_retention,
        stability_score=stability_score,
        input_lineage_ids=(f"stress-data-{scenario.scenario_id.lower()}", "model-snapshot-a"),
    )


def _engine(scenarios: tuple[StressScenarioDefinition, ...] | None = None) -> ModelStressEngine:
    return ModelStressEngine(scenario_registry=StressScenarioRegistry(scenarios or _scenarios()))


def _clean_results(
    scenarios: tuple[StressScenarioDefinition, ...] | None = None,
) -> tuple[ModelStressResult, ...]:
    active = scenarios or _scenarios()
    return tuple(_result(item) for item in active)


def test_governed_model_with_required_stress_coverage_is_stress_qualified() -> None:
    view = _view()
    governance = _governance_packet(view=view)
    packet = _engine().evaluate(
        governance_packet=governance,
        views=(view,),
        results=_clean_results(),
    )

    assert packet.status is ReadinessStatus.PASS
    assert packet.stress_qualified_model_view_ids == (view.model_view_id,)
    assert packet.assessments[0].pass_ratio == 1.0
    packet.assert_views_stress_qualified((view,))
    assert packet.portfolio_construction_authorized is False
    assert packet.execution_authorized is False
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False


def test_missing_required_regime_blocks_stress_qualification() -> None:
    scenarios = _scenarios()
    results = tuple(_result(item) for item in scenarios[:-1])
    packet = _engine(scenarios).evaluate(
        governance_packet=_governance_packet(),
        views=(_view(),),
        results=results,
    )

    assessment = packet.assessments[0]
    assert packet.status is ReadinessStatus.BLOCKED
    assert assessment.stress_qualified_for_cio_research is False
    assert "REQUIRED_STRESS_CLASS_MISSING:MACRO_SHOCK" in assessment.blockers
    assert any("STRESS_SCENARIO_COUNT_BELOW_POLICY" in item for item in assessment.blockers)


def test_future_stress_result_cannot_repair_historical_model_view() -> None:
    view_time = AS_OF - timedelta(days=2)
    view = _view(as_of=view_time)
    scenarios = _scenarios()
    historical = tuple(_result(item, known_at=view_time - timedelta(hours=1)) for item in scenarios[:-1])
    future_macro = _result(scenarios[-1], known_at=AS_OF - timedelta(days=1))
    packet = _engine(scenarios).evaluate(
        governance_packet=_governance_packet(view=view),
        views=(view,),
        results=historical + (future_macro,),
    )

    assessment = packet.assessments[0]
    assert assessment.status is ReadinessStatus.BLOCKED
    assert "REQUIRED_STRESS_CLASS_MISSING:MACRO_SHOCK" in assessment.blockers
    assert future_macro.result_id not in {
        item.stress_result_id for item in assessment.scenario_assessments
    }


def test_required_stress_scenario_failure_blocks_model() -> None:
    scenarios = _scenarios()
    bad_historical = _result(
        scenarios[0],
        expectancy_r=-0.80,
        max_drawdown=0.52,
        worst_loss_r=-4.5,
        recovery_periods=55,
        capacity_retention=0.30,
        stability_score=0.20,
    )
    results = (bad_historical,) + tuple(_result(item) for item in scenarios[1:])
    packet = _engine(scenarios).evaluate(
        governance_packet=_governance_packet(),
        views=(_view(),),
        results=results,
    )

    assessment = packet.assessments[0]
    assert assessment.status is ReadinessStatus.BLOCKED
    assert "REQUIRED_STRESS_CLASS_FAILED:HISTORICAL_SHOCK" in assessment.blockers
    failed = next(item for item in assessment.scenario_assessments if not item.passed)
    assert any("STRESSED_MAX_DRAWDOWN_ABOVE_POLICY" in item for item in failed.reasons)
    assert any("STRESSED_WORST_LOSS_BELOW_POLICY" in item for item in failed.reasons)


def test_optional_scenario_failure_is_warning_when_required_coverage_and_ratio_hold() -> None:
    required = _scenarios()
    optional = _scenario("CORRELATION_BREAK", StressScenarioClass.CORRELATION_SHOCK)
    scenarios = required + (optional,)
    results = _clean_results(required) + (_result(optional, expectancy_r=-0.60),)
    packet = _engine(scenarios).evaluate(
        governance_packet=_governance_packet(),
        views=(_view(),),
        results=results,
    )

    assessment = packet.assessments[0]
    assert packet.status is ReadinessStatus.WARNING
    assert assessment.status is ReadinessStatus.WARNING
    assert assessment.stress_qualified_for_cio_research is True
    assert assessment.pass_ratio == pytest.approx(5 / 6)
    assert any("CORRELATION_BREAK" in item for item in assessment.warnings)


def test_upstream_model_governance_block_remains_a_hard_stress_block() -> None:
    view = _view()
    governance = _governance_packet(view=view, sharpe=0.20)
    assert governance.status is ReadinessStatus.BLOCKED
    packet = _engine().evaluate(
        governance_packet=governance,
        views=(view,),
        results=_clean_results(),
    )

    assert packet.status is ReadinessStatus.BLOCKED
    assert "UPSTREAM_MODEL_GOVERNANCE_BLOCKED" in packet.assessments[0].blockers
    with pytest.raises(ModelStressError, match="MODEL_VIEW_NOT_STRESS_QUALIFIED"):
        packet.assert_views_stress_qualified((view,))


def test_stress_packet_identity_is_stable_across_order_and_duplicate_results() -> None:
    scenarios = _scenarios()
    results = _clean_results(scenarios)
    engine = _engine(tuple(reversed(scenarios)))
    governance = _governance_packet()

    first = engine.evaluate(
        governance_packet=governance,
        views=(_view(),),
        results=results,
    )
    second = engine.evaluate(
        governance_packet=governance,
        views=(_view(), _view()),
        results=tuple(reversed(results)) + (results[0],),
    )

    assert first.packet_id == second.packet_id
    assert first.assessments[0].assessment_id == second.assessments[0].assessment_id


def test_scenario_registry_rejects_silent_same_version_redefinition() -> None:
    scenario = _scenario("COVID_GAP", StressScenarioClass.HISTORICAL_SHOCK)
    registry = StressScenarioRegistry((scenario,))

    with pytest.raises(ModelStressError, match="STRESS_SCENARIO_CONFLICT"):
        registry.register(replace(scenario, description="Changed definition"))


def test_future_scenario_definition_cannot_be_used_at_historical_boundary() -> None:
    scenarios = _scenarios()
    future = _scenario(
        "FUTURE_MACRO",
        StressScenarioClass.MACRO_SHOCK,
        effective_at=AS_OF + timedelta(days=1),
    )
    policy = ModelStressPolicy(
        min_scenarios=1,
        required_classes=(StressScenarioClass.MACRO_SHOCK,),
    )
    packet = _engine(scenarios + (future,)).evaluate(
        governance_packet=_governance_packet(),
        views=(_view(),),
        results=(_result(future),),
        policy=policy,
    )

    assert packet.status is ReadinessStatus.BLOCKED
    assert any("STRESS_RESULT_SCENARIO_NOT_ACTIVE" in item for item in packet.blockers)
    assert any("REQUIRED_STRESS_CLASS_MISSING" in item for item in packet.blockers)


def test_stress_result_contract_rejects_execution_or_live_authority() -> None:
    scenario = _scenarios()[0]

    with pytest.raises(ModelStressError, match="MUST_REMAIN_RESEARCH_ONLY"):
        replace(_result(scenario), trading_authorized=True)
    with pytest.raises(ModelStressError, match="MUST_REMAIN_RESEARCH_ONLY"):
        replace(_result(scenario), execution_authorized=True)
    with pytest.raises(ModelStressError, match="MUST_REMAIN_RESEARCH_ONLY"):
        replace(_result(scenario), live_trading_enabled=True)


def test_stress_result_requires_point_in_time_window_integrity() -> None:
    scenario = _scenarios()[0]
    result = _result(scenario)

    with pytest.raises(ModelStressError, match="WINDOW_END_AFTER_KNOWN_AT"):
        replace(result, window_end=result.known_at + timedelta(seconds=1))
