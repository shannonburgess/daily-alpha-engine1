from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.multi_asset_contracts import (
    AgentTrackRecord,
    BrokerCapability,
    DecisionReplayRecord,
    DigitalTwinPair,
    Direction,
    EligibilityState,
    ExposureMeasure,
    ExposureTag,
    ExpressionCandidate,
    HardBlockReason,
    InstrumentCapability,
    InstrumentType,
    InvestmentOpportunityEnvelope,
    MandateLimit,
    OutcomeLink,
    OverlayKind,
    OverrideEvaluationState,
    OverrideRecommendation,
    PersonalCIOMandate,
    PortfolioDigitalTwin,
    PortfolioPosition,
    PrimaryAssetClass,
    RiskProfile,
    ScenarioRequest,
    ScenarioResponse,
    ScenarioShock,
    StressLoss,
    TranslationRequest,
    TwinKind,
    WarningSeverity,
    evaluate_risk_override,
    rank_expression_candidates,
)

AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _candidate(
    expression_id: str,
    asset_class: PrimaryAssetClass,
    instrument_type: InstrumentType,
    instrument_id: str,
    score: float,
    eligibility: EligibilityState = EligibilityState.AVAILABLE,
) -> ExpressionCandidate:
    return ExpressionCandidate(
        expression_id=expression_id,
        primary_asset_class=asset_class,
        instrument_type=instrument_type,
        instrument_id=instrument_id,
        implementation_structure="test structure",
        suitability_score=score,
        eligibility=eligibility,
        risk_summary="bounded test risk",
        liquidity_capacity_summary="test liquidity evidence",
        evidence_ids=(f"ev-{expression_id}",),
    )


def test_opportunity_envelope_is_asset_neutral_and_deterministic():
    option_alt = _candidate(
        "mu-option-alt",
        PrimaryAssetClass.EQUITY,
        InstrumentType.OPTION,
        "MU-2026-12-18-C-250",
        88.0,
    )
    cash_alt = _candidate(
        "cash-alt",
        PrimaryAssetClass.FX_CASH_RESERVE,
        InstrumentType.TREASURY_RESERVE,
        "SGOV",
        45.0,
    )
    kwargs = dict(
        version="1.0",
        as_of=AS_OF,
        thesis_id="ai-memory-cycle",
        thesis_summary="Memory demand is accelerating.",
        primary_asset_class=PrimaryAssetClass.EQUITY,
        exposure="AI memory / semiconductor cycle",
        instrument_type=InstrumentType.EQUITY,
        instrument_id="MU",
        implementation_structure="direct shares",
        direction=Direction.LONG,
        risk_description="equity downside and semiconductor-cycle concentration",
        liquidity_capacity_state="PASS",
        volatility_sensitivity_state="ELEVATED",
        portfolio_fit_assessment="positive alpha fit; existing semiconductor concentration",
        account_eligibility=EligibilityState.AVAILABLE,
        recommended_quantity=100.0,
        recommended_allocation_pct=2.5,
        recommended_capital_at_risk=5_000.0,
        alternatives=(option_alt, cash_alt),
        overlays=(
            ExposureTag(OverlayKind.SECTOR_INDUSTRY, "SEMICONDUCTORS", 100.0),
            ExposureTag(OverlayKind.THEMATIC, "AI_INFRASTRUCTURE", 80.0),
        ),
        evidence_ids=("price-1", "sector-1", "model-1"),
        lineage_ids=("decision-input-1",),
        agent_opinion_ids=("equity-agent-1", "sector-agent-1"),
    )

    first = InvestmentOpportunityEnvelope(**kwargs)
    second = InvestmentOpportunityEnvelope(**kwargs)

    assert first.opportunity_id == second.opportunity_id
    assert first.primary_asset_class == PrimaryAssetClass.EQUITY
    assert {overlay.kind for overlay in first.overlays} == {
        OverlayKind.SECTOR_INDUSTRY,
        OverlayKind.THEMATIC,
    }
    assert first.execution_authorized is False
    assert first.trading_authorized is False
    assert first.live_trading_enabled is False


@pytest.mark.parametrize(
    ("asset_class", "instrument_type", "instrument_id"),
    [
        (PrimaryAssetClass.FIXED_INCOME_CREDIT, InstrumentType.BOND, "UST-10Y"),
        (PrimaryAssetClass.COMMODITY, InstrumentType.FUTURE, "HG-COPPER"),
        (PrimaryAssetClass.DIGITAL_ASSET, InstrumentType.DIGITAL_ASSET, "BTC"),
    ],
)
def test_envelope_does_not_require_equity_fields(asset_class, instrument_type, instrument_id):
    envelope = InvestmentOpportunityEnvelope(
        version="1.0",
        as_of=AS_OF,
        thesis_id=f"thesis-{instrument_id}",
        thesis_summary="Cross-asset test thesis.",
        primary_asset_class=asset_class,
        exposure="economic exposure",
        instrument_type=instrument_type,
        instrument_id=instrument_id,
        implementation_structure="direct supported expression",
        direction=Direction.LONG,
        risk_description="asset-specific risk description",
        liquidity_capacity_state="PASS",
        volatility_sensitivity_state="MEASURED",
        portfolio_fit_assessment="diversifying",
        account_eligibility=EligibilityState.AVAILABLE,
        recommended_allocation_pct=1.0,
        recommended_capital_at_risk=2_500.0,
        evidence_ids=(f"ev-{instrument_id}",),
    )

    assert envelope.primary_asset_class == asset_class
    assert envelope.instrument_type == instrument_type
    assert envelope.opportunity_id.startswith("opp_")


def test_personal_cio_mandate_separates_house_guidance_from_hard_constraints():
    mandate = PersonalCIOMandate(
        mandate_id="mandate-balanced-1",
        version="1.0",
        as_of=AS_OF,
        risk_profile=RiskProfile.BALANCED,
        allowed_asset_classes=frozenset(PrimaryAssetClass),
        prohibited_asset_classes=frozenset(),
        target_volatility_pct=12.0,
        minimum_liquidity_reserve_pct=5.0,
        max_position_allocation_pct=8.0,
        limits=(MandateLimit("ASSET_CLASS", "DIGITAL_ASSET", 8.0),),
        allowed_instrument_types=frozenset(InstrumentType),
        objectives=("GROWTH", "LIQUIDITY"),
        restrictions=("NO_UNDEFINED_EXECUTION_AUTHORITY",),
        evidence_ids=("mandate-source-1",),
    )

    assert mandate.risk_profile == RiskProfile.BALANCED
    assert mandate.minimum_liquidity_reserve_pct == 5.0
    assert mandate.execution_authorized is False

    with pytest.raises(ValueError, match="both allowed and prohibited"):
        PersonalCIOMandate(
            mandate_id="bad",
            version="1.0",
            as_of=AS_OF,
            risk_profile=RiskProfile.BALANCED,
            allowed_asset_classes=frozenset({PrimaryAssetClass.EQUITY}),
            prohibited_asset_classes=frozenset({PrimaryAssetClass.EQUITY}),
        )


def test_two_to_fifty_option_override_is_warning_not_arbitrary_hard_block():
    record = evaluate_risk_override(
        opportunity_id="opp-option-1",
        as_of=AS_OF,
        policy_version="house-risk-1",
        actor_id="customer-1",
        actor_role="OWNER",
        recommended_quantity=2,
        selected_quantity=50,
        recommended_capital_at_risk=21_000,
        selected_capital_at_risk=525_000,
        concentration_impact="material concentration increase",
        correlation_impact="growth-beta concentration increase",
        liquidity_capacity_assessment="capacity available",
        account_eligibility=EligibilityState.AVAILABLE,
        stress_losses=(StressLoss("LONG_CALL_MAX_PREMIUM_LOSS", 525_000),),
        acknowledged=False,
        evidence_ids=("quote-1", "portfolio-1", "policy-1"),
    )

    assert record.override_multiple == 25.0
    assert record.recommended_capital_at_risk == 21_000
    assert record.selected_capital_at_risk == 525_000
    assert record.recommendation == OverrideRecommendation.REDUCE
    assert record.warning_severity == WarningSeverity.HIGH
    assert record.evaluation_state == OverrideEvaluationState.ACKNOWLEDGMENT_REQUIRED
    assert record.hard_blocks == ()
    assert record.execution_authorized is False

    acknowledged = evaluate_risk_override(
        opportunity_id="opp-option-1",
        as_of=AS_OF,
        policy_version="house-risk-1",
        actor_id="customer-1",
        actor_role="OWNER",
        recommended_quantity=2,
        selected_quantity=50,
        recommended_capital_at_risk=21_000,
        selected_capital_at_risk=525_000,
        concentration_impact="material concentration increase",
        correlation_impact="growth-beta concentration increase",
        liquidity_capacity_assessment="capacity available",
        account_eligibility=EligibilityState.AVAILABLE,
        stress_losses=(StressLoss("LONG_CALL_MAX_PREMIUM_LOSS", 525_000),),
        acknowledged=True,
        evidence_ids=("quote-1", "portfolio-1", "policy-1"),
    )
    assert acknowledged.evaluation_state == OverrideEvaluationState.ACCEPTABLE
    assert acknowledged.recommendation == OverrideRecommendation.REDUCE
    assert acknowledged.execution_authorized is False


def test_objective_account_constraint_creates_hard_block():
    record = evaluate_risk_override(
        opportunity_id="opp-btc-1",
        as_of=AS_OF,
        policy_version="house-risk-1",
        actor_id="customer-1",
        actor_role="OWNER",
        recommended_quantity=1,
        selected_quantity=1,
        recommended_capital_at_risk=10_000,
        selected_capital_at_risk=10_000,
        concentration_impact="within mandate",
        correlation_impact="within mandate",
        liquidity_capacity_assessment="not applicable because account does not support it",
        account_eligibility=EligibilityState.NOT_SUPPORTED,
        stress_losses=(StressLoss("DIGITAL_ASSET_-30PCT", 3_000),),
        acknowledged=True,
        evidence_ids=("account-capability-1",),
    )

    assert record.recommendation == OverrideRecommendation.BLOCK
    assert record.evaluation_state == OverrideEvaluationState.HARD_BLOCKED
    assert HardBlockReason.NOT_SUPPORTED in record.hard_blocks


def test_broker_capability_exposes_explicit_eligibility_states():
    capability = BrokerCapability(
        account_id="account-1",
        provider="BROKER_FIXTURE",
        as_of=AS_OF,
        account_type="MARGIN",
        settlement_currency="USD",
        capabilities=(
            InstrumentCapability(
                PrimaryAssetClass.EQUITY,
                InstrumentType.EQUITY,
                EligibilityState.AVAILABLE,
                "shares enabled",
                ("broker-ev-1",),
            ),
            InstrumentCapability(
                PrimaryAssetClass.DIGITAL_ASSET,
                InstrumentType.DIGITAL_ASSET,
                EligibilityState.NOT_SUPPORTED,
                "provider does not support direct digital assets",
                ("broker-ev-2",),
            ),
        ),
        buying_power=1_000_000,
        collateral_semantics="provider-reported buying power; read-only",
        evidence_ids=("broker-snapshot-1",),
    )

    assert capability.eligibility_for(
        PrimaryAssetClass.EQUITY,
        InstrumentType.EQUITY,
    ) == EligibilityState.AVAILABLE
    assert capability.eligibility_for(
        PrimaryAssetClass.DIGITAL_ASSET,
        InstrumentType.DIGITAL_ASSET,
    ) == EligibilityState.NOT_SUPPORTED
    assert capability.eligibility_for(
        PrimaryAssetClass.COMMODITY,
        InstrumentType.FUTURE,
    ) == EligibilityState.NOT_SUPPORTED
    assert capability.execution_authorized is False


def _current_twin() -> PortfolioDigitalTwin:
    return PortfolioDigitalTwin(
        portfolio_id="portfolio-1",
        version="1.0",
        kind=TwinKind.CURRENT,
        as_of=AS_OF,
        nav=1_000_000,
        cash=100_000,
        collateral=50_000,
        buying_power=500_000,
        positions=(
            PortfolioPosition(
                position_id="mu-shares",
                primary_asset_class=PrimaryAssetClass.EQUITY,
                instrument_type=InstrumentType.EQUITY,
                instrument_id="MU",
                quantity=500,
                market_value=65_000,
                notional_exposure=65_000,
                capital_at_risk=5_000,
                overlays=(ExposureTag(OverlayKind.SECTOR_INDUSTRY, "SEMICONDUCTORS"),),
                evidence_ids=("position-1",),
            ),
        ),
        exposures=(
            ExposureMeasure("ASSET_CLASS", "EQUITY", 65.0, "PCT_NAV", False, ("exp-1",)),
            ExposureMeasure("FACTOR", "MOMENTUM", 44.0, "PCT_RISK", True, ("factor-1",)),
        ),
        portfolio_volatility_pct=11.0,
        drawdown_pct=3.0,
        liquidity_reserve_requirement_pct=5.0,
        evidence_ids=("portfolio-snapshot-1",),
    )


def test_portfolio_digital_twin_requires_current_to_pro_forma_lineage():
    current = _current_twin()
    pro_forma = PortfolioDigitalTwin(
        portfolio_id=current.portfolio_id,
        version="1.0",
        kind=TwinKind.PRO_FORMA,
        as_of=AS_OF,
        nav=1_000_000,
        cash=75_000,
        collateral=50_000,
        buying_power=475_000,
        positions=current.positions,
        exposures=current.exposures,
        portfolio_volatility_pct=11.5,
        drawdown_pct=3.0,
        liquidity_reserve_requirement_pct=5.0,
        evidence_ids=("portfolio-snapshot-1", "pro-forma-opportunity-1"),
        parent_twin_id=current.twin_id,
    )

    pair = DigitalTwinPair(current=current, pro_forma=pro_forma, decision_id="decision-1")
    assert pair.pro_forma.parent_twin_id == pair.current.twin_id
    assert pair.current.execution_authorized is False
    assert pair.pro_forma.execution_authorized is False


def test_scenario_lab_uses_exact_point_in_time_twin_and_stays_modeled():
    current = _current_twin()
    request = ScenarioRequest(
        as_of=current.as_of,
        portfolio_twin_id=current.twin_id,
        portfolio_as_of=current.as_of,
        shocks=(ScenarioShock("EQUITY_INDEX", "NASDAQ", relative_change_pct=-15.0),),
        evidence_ids=("scenario-policy-1", "portfolio-snapshot-1"),
    )
    response = ScenarioResponse(
        request_id=request.request_id,
        as_of=current.as_of,
        portfolio_twin_id=current.twin_id,
        stressed_nav=880_000,
        estimated_loss=120_000,
        observations=("semiconductor/growth concentration is the largest modeled loss driver",),
    )

    assert response.modeled is True
    assert response.observed_market_value is False
    assert response.execution_authorized is False

    with pytest.raises(ValueError, match="exact point-in-time"):
        ScenarioRequest(
            as_of=current.as_of + timedelta(minutes=1),
            portfolio_twin_id=current.twin_id,
            portfolio_as_of=current.as_of,
            shocks=(ScenarioShock("RATES", "UST_10Y", basis_point_change=100),),
            evidence_ids=("scenario-policy-1",),
        )


def test_cross_asset_translator_ranks_eligible_expressions_and_retains_cash():
    request = TranslationRequest(
        thesis_id="inflation-reacceleration",
        as_of=AS_OF,
        mandate_id="mandate-1",
        account_id="account-1",
        evidence_ids=("macro-1",),
    )
    candidates = (
        _candidate(
            "gold",
            PrimaryAssetClass.COMMODITY,
            InstrumentType.COMMODITY_ETF,
            "GLD",
            80,
        ),
        _candidate(
            "tips",
            PrimaryAssetClass.FIXED_INCOME_CREDIT,
            InstrumentType.ETF,
            "TIP",
            76,
        ),
        _candidate(
            "btc",
            PrimaryAssetClass.DIGITAL_ASSET,
            InstrumentType.DIGITAL_ASSET,
            "BTC",
            95,
            EligibilityState.NOT_SUPPORTED,
        ),
        _candidate(
            "cash",
            PrimaryAssetClass.FX_CASH_RESERVE,
            InstrumentType.TREASURY_RESERVE,
            "SGOV",
            30,
        ),
    )
    result = rank_expression_candidates(
        request,
        candidates,
        no_position_expression_id="cash",
    )

    assert [item.expression_id for item in result.ranked_expressions] == [
        "gold",
        "tips",
        "cash",
        "btc",
    ]
    assert result.no_position_expression_id == "cash"
    assert result.execution_authorized is False


def test_agent_track_record_and_decision_replay_preserve_lineage():
    track = AgentTrackRecord(
        agent_id="equity-agent",
        agent_version="3.2",
        domain="EQUITY",
        as_of=AS_OF,
        sample_size=120,
        directional_hit_rate=58.0,
        expectancy_r=0.22,
        max_drawdown_r=4.5,
        max_loss_streak=6,
        calibration_error=0.08,
        stale_data_incidence_pct=0.5,
        evidence_ids=("agent-outcomes-v3.2",),
    )
    same_track = AgentTrackRecord(
        agent_id="equity-agent",
        agent_version="3.2",
        domain="EQUITY",
        as_of=AS_OF,
        sample_size=120,
        directional_hit_rate=58.0,
        expectancy_r=0.22,
        max_drawdown_r=4.5,
        max_loss_streak=6,
        calibration_error=0.08,
        stale_data_incidence_pct=0.5,
        evidence_ids=("agent-outcomes-v3.2",),
    )
    outcome = OutcomeLink(
        outcome_id="outcome-1",
        observed_at=AS_OF + timedelta(days=5),
        evidence_ids=("realized-outcome-1",),
    )
    replay = DecisionReplayRecord(
        decision_id="decision-1",
        as_of=AS_OF,
        evidence_ids=("evidence-at-decision-1",),
        agent_opinion_ids=("equity-opinion-1", "macro-opinion-1"),
        cio_decision_id="cio-1",
        portfolio_assessment_id="portfolio-assessment-1",
        risk_evaluation_id="risk-1",
        opportunity_id="opp-1",
        recommended_size_id="size-1",
        customer_override_id=None,
        broker_capability_id="broker-cap-1",
        outcome=outcome,
    )

    assert track.record_id == same_track.record_id
    assert replay.outcome.observed_at > replay.as_of
    assert replay.execution_authorized is False

    with pytest.raises(ValueError, match="cannot predate"):
        DecisionReplayRecord(
            decision_id="decision-1",
            as_of=AS_OF,
            evidence_ids=("evidence-at-decision-1",),
            agent_opinion_ids=("equity-opinion-1",),
            cio_decision_id="cio-1",
            portfolio_assessment_id="portfolio-assessment-1",
            risk_evaluation_id="risk-1",
            opportunity_id="opp-1",
            recommended_size_id="size-1",
            customer_override_id=None,
            broker_capability_id="broker-cap-1",
            outcome=OutcomeLink(
                outcome_id="future-leak",
                observed_at=AS_OF - timedelta(minutes=1),
                evidence_ids=("invalid",),
            ),
        )


def test_naive_timestamps_fail_closed():
    with pytest.raises(ValueError, match="timezone-aware"):
        TranslationRequest(
            thesis_id="test",
            as_of=datetime(2026, 8, 21, 20, 0),
            mandate_id="mandate-1",
            account_id="account-1",
            evidence_ids=("evidence-1",),
        )
