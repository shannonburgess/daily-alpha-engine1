from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.agentic.cio_fusion import (
    CIOFusionInput,
    CIOFusionValidator,
    CIOInvestmentDecision,
    InvestmentAction,
)
from daily_alpha.agentic.command_center import (
    CommandCenterComponentKind,
    InstitutionalCommandCenterBuilder,
)
from daily_alpha.agentic.command_center_decision_adapters import (
    project_cio_fusion,
    project_portfolio_proposal,
    project_research_council,
    project_risk_governor,
)
from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.portfolio_construction import (
    AllocationDirection,
    PortfolioAllocationProposal,
    TargetAllocation,
)
from daily_alpha.agentic.research_council import (
    AgentInputPacket,
    AgentOpinion,
    CouncilInputKind,
    CouncilInputRef,
    CouncilRole,
    EvidenceEffect,
    OpinionEvidenceRef,
    OpinionStance,
    ResearchCouncilPacket,
)
from daily_alpha.agentic.risk_governor import RiskGovernorDecision, RiskVerdict


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _council() -> ResearchCouncilPacket:
    mandate_id = "a" * 64
    evidence_id = "b" * 64
    input_packet = AgentInputPacket(
        security_id="MU",
        role=CouncilRole.SKEPTIC,
        as_of=AS_OF,
        mandate_id=mandate_id,
        inputs=(
            CouncilInputRef(
                input_kind=CouncilInputKind.FEATURE,
                input_id=evidence_id,
                available_at=AS_OF,
                quality_label="CANONICAL",
            ),
        ),
    )
    opinion = AgentOpinion(
        security_id="MU",
        role=CouncilRole.SKEPTIC,
        as_of=AS_OF,
        mandate_id=mandate_id,
        input_packet_id=input_packet.packet_id,
        status=ReadinessStatus.WARNING,
        stance=OpinionStance.NEUTRAL,
        score=0,
        confidence=0.4,
        input_quality_score=0.8,
        thesis="Evidence is mixed.",
        counterpoint="Momentum could still improve.",
        evidence_refs=(
            OpinionEvidenceRef(
                input_id=evidence_id,
                effect=EvidenceEffect.UNCERTAINTY,
                note="Mixed feature evidence.",
            ),
        ),
        invalidation_conditions=("Canonical feature state improves.",),
        warnings=("SKEPTIC_UNCERTAINTY",),
        reasoning_engine="FIXTURE",
        reasoning_engine_version="v1",
    )
    return ResearchCouncilPacket(
        security_id="MU",
        as_of=AS_OF,
        mandate_registry_id="c" * 64,
        input_packets=(input_packet,),
        opinions=(opinion,),
        required_roles=(CouncilRole.SKEPTIC,),
        missing_roles=(),
        status=ReadinessStatus.WARNING,
        blockers=(),
        warnings=("SKEPTIC_UNCERTAINTY",),
    )


def _cio_record(council: ResearchCouncilPacket):
    fusion_input = CIOFusionInput(
        security_id="MU",
        as_of=AS_OF,
        council=council,
    )
    decision = CIOInvestmentDecision(
        security_id="MU",
        as_of=AS_OF,
        fusion_input_id=fusion_input.fusion_input_id,
        action=InvestmentAction.WAIT,
        conviction=0.35,
        expected_alpha_score=5,
        rationale="Preserve the disagreement until evidence improves.",
        opposing_case="Momentum could strengthen enough to justify risk later.",
        invalidation_conditions=("Council warning clears.",),
        cited_opinion_ids=(council.opinions[0].opinion_id,),
        cited_model_view_ids=(),
        reasoning_engine="FIXTURE",
        reasoning_engine_version="v1",
    )
    return CIOFusionValidator().validate(fusion_input, decision)


def _proposal(cio_decision_id: str) -> PortfolioAllocationProposal:
    allocation = TargetAllocation(
        security_id="MU",
        current_weight=0.80,
        target_weight=0.90,
        delta_weight=0.10,
        direction=AllocationDirection.INCREASE,
        cio_decision_id=cio_decision_id,
    )
    return PortfolioAllocationProposal(
        as_of=AS_OF,
        portfolio_snapshot_id="d" * 64,
        correlation_surface_id="e" * 64,
        policy_id="f" * 64,
        target_allocations=(allocation,),
        target_cash_weight=0.10,
        estimated_portfolio_volatility=0.18,
        estimated_turnover=0.10,
        objective_utility_bps=25.0,
        selected_assessments=(),
        excluded_opportunity_ids=(),
        status=ReadinessStatus.PASS,
        blockers=(),
        warnings=(),
    )


def test_decision_chain_projection_preserves_disagreement_and_risk_veto() -> None:
    council = _council()
    cio_record = _cio_record(council)
    proposal = _proposal(cio_record.decision.decision_id)
    risk = RiskGovernorDecision(
        as_of=AS_OF,
        proposal_id=proposal.proposal_id,
        portfolio_snapshot_id=proposal.portfolio_snapshot_id,
        policy_id="1" * 64,
        risk_context_id="2" * 64,
        governance_id="3" * 64,
        verdict=RiskVerdict.REJECTED,
        risk_governor_approved=False,
        reviewed_target_allocations=proposal.target_allocations,
        blockers=("DRAWDOWN_THROTTLE_BLOCKS_NEW_RISK",),
        warnings=(),
    )

    council_component = project_research_council(council)
    cio_component = project_cio_fusion(cio_record)
    proposal_component = project_portfolio_proposal(proposal, portfolio_id="SHADOW")
    risk_component = project_risk_governor(risk, portfolio_id="SHADOW")
    snapshot = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(risk_component, proposal_component, cio_component, council_component),
        portfolio_id="SHADOW",
        security_id="MU",
    )

    assert council_component.kind is CommandCenterComponentKind.RESEARCH_COUNCIL
    assert council_component.status is ReadinessStatus.WARNING
    assert council.opinions[0].opinion_id in council_component.lineage_ids
    assert cio_component.kind is CommandCenterComponentKind.CIO_DECISION
    assert cio_component.status is ReadinessStatus.WARNING
    assert dict(cio_component.metrics)["action"] == "WAIT"
    assert council.council_packet_id in cio_component.lineage_ids
    assert proposal_component.kind is CommandCenterComponentKind.PORTFOLIO_PROPOSAL
    assert proposal_component.portfolio_id == "SHADOW"
    assert cio_record.decision.decision_id in proposal_component.lineage_ids
    assert risk_component.kind is CommandCenterComponentKind.RISK_GOVERNOR
    assert risk_component.status is ReadinessStatus.BLOCKED
    assert proposal.proposal_id in risk_component.lineage_ids
    assert snapshot.status is ReadinessStatus.BLOCKED
    assert snapshot.pass_count == 1
    assert snapshot.warning_count == 2
    assert snapshot.blocked_count == 1

    for component in snapshot.components:
        assert component.research_only is True
        assert component.paper_ledger_mutation_authorized is False
        assert component.portfolio_construction_authorized is False
        assert component.execution_authorized is False
        assert component.trading_authorized is False
        assert component.live_trading_enabled is False


def test_approved_risk_with_warning_remains_warning_grade() -> None:
    proposal = _proposal("4" * 64)
    risk = RiskGovernorDecision(
        as_of=AS_OF,
        proposal_id=proposal.proposal_id,
        portfolio_snapshot_id=proposal.portfolio_snapshot_id,
        policy_id="5" * 64,
        risk_context_id="6" * 64,
        governance_id="7" * 64,
        verdict=RiskVerdict.APPROVED,
        risk_governor_approved=True,
        reviewed_target_allocations=proposal.target_allocations,
        blockers=(),
        warnings=("VOLATILITY_REMAINS_ELEVATED_WHILE_DERISKING",),
    )

    projected = project_risk_governor(risk, portfolio_id="SHADOW")

    assert projected.status is ReadinessStatus.WARNING
    assert dict(projected.metrics)["verdict"] == "APPROVED"
    assert projected.warnings == ("VOLATILITY_REMAINS_ELEVATED_WHILE_DERISKING",)
