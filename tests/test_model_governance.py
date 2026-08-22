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
    ModelGovernanceError,
    ModelGovernancePolicy,
    ModelLifecycleStage,
    ModelRegistry,
    ModelValidationRecord,
)


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _definition(
    *,
    model_id: str = "R2_MOMENTUM",
    version: str = "1.0.0",
    stage: ModelLifecycleStage = ModelLifecycleStage.SHADOW,
) -> ModelDefinition:
    return ModelDefinition(
        model_id=model_id,
        model_version=version,
        owner="Daily Alpha Quant Research",
        stage=stage,
        effective_at=AS_OF - timedelta(days=180),
        retired_at=(AS_OF - timedelta(days=1) if stage is ModelLifecycleStage.RETIRED else None),
        description="Fixture model",
    )


def _view(
    *,
    model_id: str = "R2_MOMENTUM",
    version: str = "1.0.0",
    as_of: datetime = AS_OF,
    status: ReadinessStatus = ReadinessStatus.PASS,
    lineage: tuple[str, ...] = ("canonical-state-a", "feature-bundle-b"),
) -> QuantModelView:
    return QuantModelView(
        security_id="SEC-AAPL",
        model_id=model_id,
        model_version=version,
        as_of=as_of,
        status=status,
        signal_label="LONG_BIAS" if status is not ReadinessStatus.BLOCKED else "BLOCKED",
        score=62 if status is not ReadinessStatus.BLOCKED else None,
        confidence=0.81 if status is not ReadinessStatus.BLOCKED else 0.0,
        input_lineage_ids=lineage,
    )


def _validation(
    *,
    model_id: str = "R2_MOMENTUM",
    version: str = "1.0.0",
    as_of: datetime = AS_OF - timedelta(hours=1),
    sample_size: int = 120,
    expectancy_r: float = 0.22,
    sharpe: float = 1.35,
    sortino: float = 1.80,
    max_drawdown: float = 0.12,
    profit_factor: float = 1.42,
    stability_score: float = 0.82,
) -> ModelValidationRecord:
    return ModelValidationRecord(
        model_id=model_id,
        model_version=version,
        as_of=as_of,
        window_start=as_of - timedelta(days=365),
        window_end=as_of - timedelta(days=1),
        sample_size=sample_size,
        expectancy_r=expectancy_r,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        stability_score=stability_score,
        input_lineage_ids=("backtest-snapshot-1", "holdout-snapshot-2"),
    )


def _policy() -> ModelGovernancePolicy:
    return ModelGovernancePolicy(
        min_sample_size=100,
        min_expectancy_r=0.10,
        min_sharpe=1.0,
        min_sortino=1.2,
        max_drawdown=0.15,
        min_profit_factor=1.25,
        min_stability_score=0.70,
    )


def test_shadow_model_with_available_validation_is_cio_research_eligible() -> None:
    view = _view()
    registry = ModelRegistry((_definition(),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(view,),
        validations=(_validation(),),
        policy=_policy(),
    )

    assert packet.status is ReadinessStatus.PASS
    assert packet.eligible_model_view_ids == (view.model_view_id,)
    assert packet.assessments[0].validation_id == _validation().validation_id
    assert packet.assessments[0].eligible_for_cio_research is True
    packet.assert_views_eligible((view,))
    assert packet.portfolio_construction_authorized is False
    assert packet.execution_authorized is False
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False


def test_failed_validation_threshold_blocks_model_view() -> None:
    registry = ModelRegistry((_definition(),))
    validation = _validation(max_drawdown=0.28, sharpe=0.65, expectancy_r=-0.05)
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(),),
        validations=(validation,),
        policy=_policy(),
    )

    assessment = packet.assessments[0]
    assert packet.status is ReadinessStatus.BLOCKED
    assert assessment.status is ReadinessStatus.BLOCKED
    assert assessment.eligible_for_cio_research is False
    assert any("MAX_DRAWDOWN_ABOVE_POLICY" in item for item in assessment.blockers)
    assert any("SHARPE_BELOW_POLICY" in item for item in assessment.blockers)
    assert any("EXPECTANCY_R_BELOW_POLICY" in item for item in assessment.blockers)


def test_future_validation_cannot_repair_historical_model_view() -> None:
    view_time = AS_OF - timedelta(days=2)
    view = _view(as_of=view_time)
    future_validation = _validation(as_of=AS_OF - timedelta(days=1))
    registry = ModelRegistry((_definition(),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(view,),
        validations=(future_validation,),
        policy=_policy(),
    )

    assessment = packet.assessments[0]
    assert assessment.validation_id is None
    assert "MODEL_VALIDATION_NOT_AVAILABLE_AS_OF_VIEW" in assessment.blockers
    assert packet.status is ReadinessStatus.BLOCKED


def test_research_lifecycle_stage_is_not_eligible_by_default() -> None:
    registry = ModelRegistry((_definition(stage=ModelLifecycleStage.RESEARCH),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(),),
        validations=(_validation(),),
        policy=_policy(),
    )

    assert packet.status is ReadinessStatus.BLOCKED
    assert "MODEL_STAGE_NOT_ELIGIBLE:RESEARCH" in packet.assessments[0].blockers


def test_retired_model_version_is_blocked() -> None:
    registry = ModelRegistry((_definition(stage=ModelLifecycleStage.RETIRED),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(),),
        validations=(_validation(),),
        policy=_policy(),
    )

    assert packet.status is ReadinessStatus.BLOCKED
    assert "MODEL_VERSION_RETIRED" in packet.assessments[0].blockers


def test_blocked_quant_model_view_remains_blocked_even_with_good_validation() -> None:
    registry = ModelRegistry((_definition(),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(status=ReadinessStatus.BLOCKED),),
        validations=(_validation(),),
        policy=_policy(),
    )

    assert packet.status is ReadinessStatus.BLOCKED
    assert "QUANT_MODEL_VIEW_BLOCKED" in packet.assessments[0].blockers


def test_model_view_without_input_lineage_is_governance_blocked() -> None:
    registry = ModelRegistry((_definition(),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(lineage=()),),
        validations=(_validation(),),
        policy=_policy(),
    )

    assert packet.status is ReadinessStatus.BLOCKED
    assert "QUANT_MODEL_VIEW_INPUT_LINEAGE_REQUIRED" in packet.assessments[0].blockers


def test_registry_rejects_silent_redefinition_of_same_model_version() -> None:
    definition = _definition()
    registry = ModelRegistry((definition,))
    conflicting = replace(definition, owner="Different owner")

    with pytest.raises(ModelGovernanceError, match="MODEL_DEFINITION_CONFLICT"):
        registry.register(conflicting)


def test_packet_identity_is_deterministic_across_view_and_validation_order() -> None:
    definitions = (
        _definition(model_id="R2_MOMENTUM", version="1.0.0"),
        _definition(model_id="EVENT_ALPHA", version="2.1.0"),
    )
    registry = ModelRegistry(definitions)
    views = (
        _view(model_id="R2_MOMENTUM", version="1.0.0"),
        _view(model_id="EVENT_ALPHA", version="2.1.0"),
    )
    validations = (
        _validation(model_id="R2_MOMENTUM", version="1.0.0"),
        _validation(model_id="EVENT_ALPHA", version="2.1.0"),
    )
    engine = ModelGovernanceEngine(registry=registry)

    first = engine.evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=views,
        validations=validations,
        policy=_policy(),
    )
    second = engine.evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=tuple(reversed(views)),
        validations=tuple(reversed(validations)),
        policy=_policy(),
    )

    assert first.packet_id == second.packet_id
    assert first.eligible_model_view_ids == second.eligible_model_view_ids


def test_packet_rejects_ungoverned_view_at_cio_boundary() -> None:
    governed = _view()
    unknown = _view(model_id="UNKNOWN_MODEL", version="9.9.9")
    registry = ModelRegistry((_definition(),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(governed,),
        validations=(_validation(),),
        policy=_policy(),
    )

    with pytest.raises(ModelGovernanceError, match="MODEL_VIEW_NOT_GOVERNANCE_ELIGIBLE"):
        packet.assert_views_eligible((unknown,))


def test_validation_record_rejects_future_window_end() -> None:
    with pytest.raises(ModelGovernanceError, match="MODEL_VALIDATION_WINDOW_END_AFTER_AS_OF"):
        ModelValidationRecord(
            model_id="R2_MOMENTUM",
            model_version="1.0.0",
            as_of=AS_OF,
            window_start=AS_OF - timedelta(days=30),
            window_end=AS_OF + timedelta(seconds=1),
            sample_size=100,
            expectancy_r=0.2,
            sharpe=1.0,
            sortino=1.2,
            max_drawdown=0.1,
            profit_factor=1.3,
            stability_score=0.8,
            input_lineage_ids=("lineage",),
        )


def test_governance_packet_cannot_claim_execution_or_trading_authority() -> None:
    registry = ModelRegistry((_definition(),))
    packet = ModelGovernanceEngine(registry=registry).evaluate(
        security_id="SEC-AAPL",
        as_of=AS_OF,
        views=(_view(),),
        validations=(_validation(),),
        policy=_policy(),
    )

    with pytest.raises(ModelGovernanceError, match="MODEL_GOVERNANCE_PACKET_MUST_REMAIN_RESEARCH_ONLY"):
        replace(packet, execution_authorized=True)
