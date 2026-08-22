from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.cio_fusion import (
    CIOContextKind,
    CIOContextRef,
    CIOFusionError,
    CIOFusionInput,
    CIOFusionValidator,
    CIOInvestmentDecision,
    InvestmentAction,
    OverrideRecord,
    OverrideSourceKind,
    QuantModelView,
)
from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.research_council import (
    AgentInputPacket,
    AgentMandate,
    AgentMandateRegistry,
    AgentOpinion,
    CouncilInputKind,
    CouncilInputRef,
    CouncilRole,
    EvidenceEffect,
    OpinionEvidenceRef,
    OpinionStance,
    ResearchCouncilAssembler,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
SECURITY_ID = "DAI-SEC-0001"


def _council(*, blocked: bool = False):
    mandate = AgentMandate(
        role=CouncilRole.BEAR,
        version="TEST_V1",
        objective="Independent downside case",
        required_input_kinds=(CouncilInputKind.FEATURE,),
    )
    registry = AgentMandateRegistry((mandate,))
    input_ref = CouncilInputRef(
        input_kind=CouncilInputKind.FEATURE,
        input_id="a" * 64,
        available_at=NOW - timedelta(minutes=1),
        quality_label="VERIFIED",
    )
    packet = AgentInputPacket(
        security_id=SECURITY_ID,
        role=CouncilRole.BEAR,
        as_of=NOW,
        mandate_id=mandate.mandate_id,
        inputs=(input_ref,),
    )
    if blocked:
        opinion = AgentOpinion(
            security_id=SECURITY_ID,
            role=CouncilRole.BEAR,
            as_of=NOW,
            mandate_id=mandate.mandate_id,
            input_packet_id=packet.packet_id,
            status=ReadinessStatus.BLOCKED,
            stance=OpinionStance.NO_VIEW,
            score=None,
            confidence=0.0,
            input_quality_score=0.0,
            thesis="The downside case cannot be formed with current evidence.",
            counterpoint="The missing evidence may later permit a governed view.",
            evidence_refs=(),
            invalidation_conditions=(),
            blockers=("MISSING_DATA",),
            reasoning_engine="TEST",
            reasoning_engine_version="V1",
        )
    else:
        opinion = AgentOpinion(
            security_id=SECURITY_ID,
            role=CouncilRole.BEAR,
            as_of=NOW,
            mandate_id=mandate.mandate_id,
            input_packet_id=packet.packet_id,
            status=ReadinessStatus.PASS,
            stance=OpinionStance.NEGATIVE,
            score=-60,
            confidence=0.75,
            input_quality_score=0.95,
            thesis="The governed evidence supports a meaningful downside case.",
            counterpoint="Momentum or catalysts could invalidate the downside thesis.",
            evidence_refs=(
                OpinionEvidenceRef(
                    input_id=input_ref.input_id,
                    effect=EvidenceEffect.SUPPORTS,
                    note="Downside evidence",
                ),
            ),
            invalidation_conditions=("Downside evidence reverses",),
            reasoning_engine="TEST",
            reasoning_engine_version="V1",
        )
    council = ResearchCouncilAssembler(registry).assemble(
        security_id=SECURITY_ID,
        as_of=NOW,
        input_packets=(packet,),
        opinions=(opinion,),
        required_roles=(CouncilRole.BEAR,),
    )
    return council, opinion


def _model(
    model_id: str = "SH24",
    *,
    score: int | None = 70,
    status: ReadinessStatus = ReadinessStatus.PASS,
    as_of: datetime = NOW,
) -> QuantModelView:
    return QuantModelView(
        security_id=SECURITY_ID,
        model_id=model_id,
        model_version="V1",
        as_of=as_of,
        status=status,
        signal_label="BUY" if status is not ReadinessStatus.BLOCKED else "NO_VIEW",
        score=score,
        confidence=0.8 if status is not ReadinessStatus.BLOCKED else 0.0,
        input_lineage_ids=("b" * 64,),
    )


def _fusion_input(*, blocked_council: bool = False, models=(), contexts=()):
    council, opinion = _council(blocked=blocked_council)
    return (
        CIOFusionInput(
            security_id=SECURITY_ID,
            as_of=NOW,
            council=council,
            quant_model_views=tuple(models),
            context_refs=tuple(contexts),
        ),
        opinion,
    )


def _decision(
    fusion_input: CIOFusionInput,
    opinion_id: str,
    *,
    action: InvestmentAction = InvestmentAction.BUY,
    model_ids: tuple[str, ...] = (),
    overrides: tuple[OverrideRecord, ...] = (),
    **kwargs,
) -> CIOInvestmentDecision:
    return CIOInvestmentDecision(
        security_id=SECURITY_ID,
        as_of=NOW,
        fusion_input_id=fusion_input.fusion_input_id,
        action=action,
        conviction=0.82,
        expected_alpha_score=65,
        rationale="The total governed evidence supports the selected investment intent.",
        opposing_case="The bearish view remains material and is explicitly retained.",
        invalidation_conditions=("The positive evidence complex materially reverses",),
        cited_opinion_ids=(opinion_id,),
        cited_model_view_ids=model_ids,
        overrides=overrides,
        reasoning_engine="TEST_CIO",
        reasoning_engine_version="V1",
        **kwargs,
    )


def test_cio_cannot_override_risk_governor_or_governance_lock():
    fusion_input, opinion = _fusion_input()
    with pytest.raises(CIOFusionError, match="CIO_DECISION_MUST_REMAIN_BELOW_RISK_AND_GOVERNANCE"):
        _decision(
            fusion_input,
            opinion.opinion_id,
            may_override_risk_governor=True,
        )


def test_future_quant_model_view_is_rejected():
    future_model = _model(as_of=NOW + timedelta(seconds=1))
    with pytest.raises(CIOFusionError, match="FUTURE_QUANT_MODEL_VIEW_NOT_ALLOWED"):
        _fusion_input(models=(future_model,))


def test_future_portfolio_or_regime_context_is_rejected():
    context = CIOContextRef(
        context_kind=CIOContextKind.PORTFOLIO,
        context_id="c" * 64,
        available_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(CIOFusionError, match="FUTURE_CIO_CONTEXT_NOT_ALLOWED"):
        _fusion_input(contexts=(context,))


def test_cio_may_explicitly_override_individual_bear_view():
    model = _model("SH24")
    fusion_input, opinion = _fusion_input(models=(model,))
    override = OverrideRecord(
        source_kind=OverrideSourceKind.AGENT_OPINION,
        source_id=opinion.opinion_id,
        source_label="BEAR",
        reason="Broader evidence and quant confirmation outweigh the bearish view.",
    )
    decision = _decision(
        fusion_input,
        opinion.opinion_id,
        model_ids=(model.model_view_id,),
        overrides=(override,),
    )
    record = CIOFusionValidator().validate(fusion_input, decision)
    assert record.status is ReadinessStatus.PASS
    assert decision.action is InvestmentAction.BUY
    assert decision.execution_authorized is False
    assert decision.may_override_risk_governor is False


def test_unknown_council_citation_is_rejected():
    fusion_input, opinion = _fusion_input()
    decision = CIOInvestmentDecision(
        security_id=SECURITY_ID,
        as_of=NOW,
        fusion_input_id=fusion_input.fusion_input_id,
        action=InvestmentAction.BUY,
        conviction=0.7,
        expected_alpha_score=50,
        rationale="Positive total evidence.",
        opposing_case="Material downside case.",
        invalidation_conditions=("Evidence reversal",),
        cited_opinion_ids=("f" * 64,),
        cited_model_view_ids=(),
    )
    with pytest.raises(CIOFusionError, match="CIO_CITES_UNKNOWN_OPINION"):
        CIOFusionValidator().validate(fusion_input, decision)
    assert opinion.opinion_id != "f" * 64


def test_unknown_override_source_is_rejected():
    fusion_input, opinion = _fusion_input()
    decision = _decision(
        fusion_input,
        opinion.opinion_id,
        overrides=(
            OverrideRecord(
                source_kind=OverrideSourceKind.AGENT_OPINION,
                source_id="f" * 64,
                source_label="UNKNOWN",
                reason="Should fail lineage validation.",
            ),
        ),
    )
    with pytest.raises(CIOFusionError, match="CIO_OVERRIDE_SOURCE_UNKNOWN"):
        CIOFusionValidator().validate(fusion_input, decision)


def test_blocked_council_cannot_produce_active_investment_action():
    fusion_input, opinion = _fusion_input(blocked_council=True)
    decision = _decision(fusion_input, opinion.opinion_id, action=InvestmentAction.BUY)
    with pytest.raises(CIOFusionError, match="BLOCKED_COUNCIL_REQUIRES_WAIT_OR_NO_ACTION"):
        CIOFusionValidator().validate(fusion_input, decision)


def test_blocked_council_can_only_emit_nonactive_research_intent():
    fusion_input, opinion = _fusion_input(blocked_council=True)
    decision = _decision(fusion_input, opinion.opinion_id, action=InvestmentAction.WAIT)
    record = CIOFusionValidator().validate(fusion_input, decision)
    assert record.status is ReadinessStatus.BLOCKED
    assert "RESEARCH_COUNCIL_BLOCKED" in record.blockers


def test_blocked_quant_model_is_visible_warning_not_cio_master_key():
    blocked_model = _model("SH25", score=None, status=ReadinessStatus.BLOCKED)
    fusion_input, opinion = _fusion_input(models=(blocked_model,))
    decision = _decision(fusion_input, opinion.opinion_id, action=InvestmentAction.HOLD)
    record = CIOFusionValidator().validate(fusion_input, decision)
    assert record.status is ReadinessStatus.WARNING
    assert "BLOCKED_QUANT_MODEL:SH25" in record.warnings


def test_fusion_input_id_is_deterministic_across_model_and_context_order():
    council, _ = _council()
    first_model = _model("SH24")
    second_model = _model("SH25", score=40)
    portfolio = CIOContextRef(
        context_kind=CIOContextKind.PORTFOLIO,
        context_id="c" * 64,
        available_at=NOW - timedelta(seconds=2),
    )
    regime = CIOContextRef(
        context_kind=CIOContextKind.REGIME,
        context_id="d" * 64,
        available_at=NOW - timedelta(seconds=2),
    )
    left = CIOFusionInput(
        security_id=SECURITY_ID,
        as_of=NOW,
        council=council,
        quant_model_views=(first_model, second_model),
        context_refs=(portfolio, regime),
    )
    right = CIOFusionInput(
        security_id=SECURITY_ID,
        as_of=NOW,
        council=council,
        quant_model_views=(second_model, first_model),
        context_refs=(regime, portfolio),
    )
    assert left.fusion_input_id == right.fusion_input_id


def test_cio_decision_is_investment_intent_not_order():
    fusion_input, opinion = _fusion_input()
    decision = _decision(fusion_input, opinion.opinion_id, action=InvestmentAction.HOLD)
    assert decision.portfolio_construction_authorized is False
    assert decision.execution_authorized is False
    assert decision.trading_authorized is False
    assert decision.live_trading_enabled is False
    assert not hasattr(decision, "order_quantity")
    assert not hasattr(decision, "limit_price")
