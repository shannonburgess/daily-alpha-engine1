"""Read-only command-center projections for the governed decision chain.

These adapters expose Research Council, CIO/Fusion, Portfolio Construction, and Risk
Governor state to the institutional command center without creating a second decision
engine or granting presentation-layer authority. Upstream status, blockers, warnings,
and immutable lineage are preserved rather than recomputed from UI-facing metrics.
"""

from __future__ import annotations

from .cio_fusion import CIOFusionRecord
from .command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
)
from .contracts import ReadinessStatus
from .portfolio_construction import PortfolioAllocationProposal
from .research_council import ResearchCouncilPacket
from .risk_governor import RiskGovernorDecision, RiskVerdict


def project_research_council(packet: ResearchCouncilPacket) -> CommandCenterComponent:
    """Project one governed Research Council packet for a security."""
    return CommandCenterComponent(
        kind=CommandCenterComponentKind.RESEARCH_COUNCIL,
        entity_kind=CommandCenterEntityKind.SECURITY,
        entity_id=packet.security_id,
        security_id=packet.security_id,
        as_of=packet.as_of,
        source_record_id=packet.council_packet_id,
        status=packet.status,
        headline=f"Research Council for {packet.security_id}: {packet.status.value}",
        metrics={
            "opinion_count": len(packet.opinions),
            "input_packet_count": len(packet.input_packets),
            "required_role_count": len(packet.required_roles),
            "missing_roles": [item.value for item in packet.missing_roles],
            "mandate_registry_id": packet.mandate_registry_id,
        },
        blockers=packet.blockers,
        warnings=packet.warnings,
        lineage_ids=(
            packet.mandate_registry_id,
            *(item.packet_id for item in packet.input_packets),
            *(item.opinion_id for item in packet.opinions),
        ),
    )


def project_cio_fusion(record: CIOFusionRecord) -> CommandCenterComponent:
    """Project one validated CIO/Fusion decision without creating order authority."""
    decision = record.decision
    fusion_input = record.fusion_input
    return CommandCenterComponent(
        kind=CommandCenterComponentKind.CIO_DECISION,
        entity_kind=CommandCenterEntityKind.DECISION,
        entity_id=f"{decision.security_id}:CIO",
        security_id=decision.security_id,
        as_of=decision.as_of,
        source_record_id=record.fusion_record_id,
        status=record.status,
        headline=f"CIO {decision.action.value} for {decision.security_id}: {record.status.value}",
        metrics={
            "action": decision.action.value,
            "conviction": decision.conviction,
            "expected_alpha_score": decision.expected_alpha_score,
            "override_count": len(decision.overrides),
            "cited_opinion_count": len(decision.cited_opinion_ids),
            "cited_model_count": len(decision.cited_model_view_ids),
            "reasoning_engine": decision.reasoning_engine,
            "reasoning_engine_version": decision.reasoning_engine_version,
        },
        blockers=record.blockers,
        warnings=record.warnings,
        lineage_ids=(
            fusion_input.fusion_input_id,
            fusion_input.council.council_packet_id,
            decision.decision_id,
            *(item.context_id for item in fusion_input.context_refs),
            *(item.model_view_id for item in fusion_input.quant_model_views),
            *decision.cited_opinion_ids,
            *decision.cited_model_view_ids,
            *(item.source_id for item in decision.overrides),
        ),
    )


def project_portfolio_proposal(
    proposal: PortfolioAllocationProposal,
    *,
    portfolio_id: str,
) -> CommandCenterComponent:
    """Project one portfolio-construction proposal below the Risk Governor."""
    cio_decision_ids = tuple(
        item.cio_decision_id
        for item in proposal.target_allocations
        if item.cio_decision_id is not None
    )
    return CommandCenterComponent(
        kind=CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
        entity_kind=CommandCenterEntityKind.PORTFOLIO,
        entity_id=portfolio_id,
        portfolio_id=portfolio_id,
        as_of=proposal.as_of,
        source_record_id=proposal.proposal_id,
        status=proposal.status,
        headline=f"Portfolio proposal for {portfolio_id}: {proposal.status.value}",
        metrics={
            "target_allocation_count": len(proposal.target_allocations),
            "selected_assessment_count": len(proposal.selected_assessments),
            "excluded_opportunity_count": len(proposal.excluded_opportunity_ids),
            "target_cash_weight": proposal.target_cash_weight,
            "estimated_portfolio_volatility": proposal.estimated_portfolio_volatility,
            "estimated_turnover": proposal.estimated_turnover,
            "objective_utility_bps": proposal.objective_utility_bps,
        },
        blockers=proposal.blockers,
        warnings=proposal.warnings,
        lineage_ids=(
            proposal.portfolio_snapshot_id,
            proposal.correlation_surface_id,
            proposal.policy_id,
            *(item.assessment_id for item in proposal.selected_assessments),
            *proposal.excluded_opportunity_ids,
            *cio_decision_ids,
        ),
    )


def _risk_status(decision: RiskGovernorDecision) -> ReadinessStatus:
    if decision.verdict is RiskVerdict.REJECTED:
        return ReadinessStatus.BLOCKED
    if decision.warnings:
        return ReadinessStatus.WARNING
    return ReadinessStatus.PASS


def project_risk_governor(
    decision: RiskGovernorDecision,
    *,
    portfolio_id: str,
) -> CommandCenterComponent:
    """Project one deterministic Risk Governor verdict for a portfolio."""
    return CommandCenterComponent(
        kind=CommandCenterComponentKind.RISK_GOVERNOR,
        entity_kind=CommandCenterEntityKind.PORTFOLIO,
        entity_id=portfolio_id,
        portfolio_id=portfolio_id,
        as_of=decision.as_of,
        source_record_id=decision.decision_id,
        status=_risk_status(decision),
        headline=f"Risk Governor {decision.verdict.value} for {portfolio_id}",
        metrics={
            "verdict": decision.verdict.value,
            "risk_governor_approved": decision.risk_governor_approved,
            "reviewed_target_allocation_count": len(decision.reviewed_target_allocations),
        },
        blockers=decision.blockers,
        warnings=decision.warnings,
        lineage_ids=(
            decision.proposal_id,
            decision.portfolio_snapshot_id,
            decision.policy_id,
            decision.risk_context_id,
            decision.governance_id,
            *(
                item.cio_decision_id
                for item in decision.reviewed_target_allocations
                if item.cio_decision_id is not None
            ),
        ),
    )
