from datetime import UTC, datetime, timedelta

import pytest

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
    ResearchCouncilError,
    default_research_council_registry,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
SECURITY_ID = "DAI-SEC-0001"


def _mandate(role: CouncilRole, required: CouncilInputKind) -> AgentMandate:
    return AgentMandate(
        role=role,
        version="TEST_V1",
        objective=f"Independent {role.value} assessment",
        required_input_kinds=(required,),
    )


def _input(kind: CouncilInputKind, suffix: str) -> CouncilInputRef:
    return CouncilInputRef(
        input_kind=kind,
        input_id=f"{suffix:0>64}"[-64:],
        available_at=NOW - timedelta(minutes=1),
        quality_label="VERIFIED",
    )


def _packet(mandate: AgentMandate, refs: tuple[CouncilInputRef, ...]) -> AgentInputPacket:
    return AgentInputPacket(
        security_id=SECURITY_ID,
        role=mandate.role,
        as_of=NOW,
        mandate_id=mandate.mandate_id,
        inputs=refs,
    )


def _opinion(
    mandate: AgentMandate,
    packet: AgentInputPacket,
    *,
    status: ReadinessStatus = ReadinessStatus.PASS,
    warning: str | None = None,
) -> AgentOpinion:
    if status is ReadinessStatus.BLOCKED:
        return AgentOpinion(
            security_id=SECURITY_ID,
            role=mandate.role,
            as_of=NOW,
            mandate_id=mandate.mandate_id,
            input_packet_id=packet.packet_id,
            status=status,
            stance=OpinionStance.NO_VIEW,
            score=None,
            confidence=0.0,
            input_quality_score=0.0,
            thesis="Insufficient evidence to form a governed view.",
            counterpoint="A view may become possible when the missing evidence arrives.",
            evidence_refs=(),
            invalidation_conditions=(),
            blockers=("MISSING_REQUIRED_INPUT",),
            reasoning_engine="TEST",
            reasoning_engine_version="V1",
        )
    return AgentOpinion(
        security_id=SECURITY_ID,
        role=mandate.role,
        as_of=NOW,
        mandate_id=mandate.mandate_id,
        input_packet_id=packet.packet_id,
        status=status,
        stance=OpinionStance.POSITIVE,
        score=40,
        confidence=0.7,
        input_quality_score=0.9,
        thesis="The governed inputs support a positive research view.",
        counterpoint="The opposing evidence could weaken the thesis.",
        evidence_refs=(
            OpinionEvidenceRef(
                input_id=packet.input_ids[0],
                effect=EvidenceEffect.SUPPORTS,
                note="Primary cited input",
            ),
        ),
        invalidation_conditions=("Core supporting evidence reverses",),
        warnings=(warning,) if warning else (),
        reasoning_engine="TEST",
        reasoning_engine_version="V1",
    )


def test_default_registry_contains_full_independent_research_council():
    registry = default_research_council_registry()
    assert {mandate.role for mandate in registry.mandates()} == set(CouncilRole)
    assert len(registry.mandates()) == 11
    for mandate in registry.mandates():
        assert mandate.peer_opinion_access is False
        assert mandate.may_place_orders is False
        assert mandate.may_authorize_trading is False
        assert mandate.may_mutate_portfolio is False
        assert mandate.may_modify_risk_limits is False


def test_research_mandate_cannot_receive_control_authority():
    with pytest.raises(ResearchCouncilError, match="RESEARCH_ANALYST_MUST_NOT_HAVE_CONTROL_AUTHORITY"):
        AgentMandate(
            role=CouncilRole.MOMENTUM,
            version="V1",
            objective="Momentum research",
            required_input_kinds=(CouncilInputKind.FEATURE,),
            may_place_orders=True,
        )


def test_future_input_is_rejected_before_agent_can_see_it():
    mandate = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    future = CouncilInputRef(
        input_kind=CouncilInputKind.FEATURE,
        input_id="a" * 64,
        available_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ResearchCouncilError, match="FUTURE_AGENT_INPUT_NOT_ALLOWED"):
        _packet(mandate, (future,))


def test_packet_must_include_mandates_required_input_kind():
    mandate = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    packet = _packet(mandate, (_input(CouncilInputKind.MARKET_STATE, "1"),))
    with pytest.raises(ResearchCouncilError, match="AGENT_REQUIRED_INPUT_KIND_MISSING"):
        packet.validate_against(mandate)


def test_input_packet_id_is_independent_of_input_order():
    mandate = AgentMandate(
        role=CouncilRole.MOMENTUM,
        version="V1",
        objective="Momentum research",
        required_input_kinds=(CouncilInputKind.FEATURE, CouncilInputKind.MARKET_STATE),
    )
    feature = _input(CouncilInputKind.FEATURE, "1")
    market = _input(CouncilInputKind.MARKET_STATE, "2")
    left = _packet(mandate, (feature, market))
    right = _packet(mandate, (market, feature))
    assert left.packet_id == right.packet_id


def test_nonblocked_opinion_requires_cited_evidence_and_invalidation():
    mandate = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    packet = _packet(mandate, (_input(CouncilInputKind.FEATURE, "1"),))
    with pytest.raises(ResearchCouncilError, match="NONBLOCKED_OPINION_REQUIRES_EVIDENCE_REFS"):
        AgentOpinion(
            security_id=SECURITY_ID,
            role=mandate.role,
            as_of=NOW,
            mandate_id=mandate.mandate_id,
            input_packet_id=packet.packet_id,
            status=ReadinessStatus.PASS,
            stance=OpinionStance.POSITIVE,
            score=25,
            confidence=0.5,
            input_quality_score=1.0,
            thesis="Positive thesis",
            counterpoint="Counterpoint",
            evidence_refs=(),
            invalidation_conditions=("Invalidation",),
        )


def test_blocked_opinion_cannot_smuggle_directional_view():
    mandate = _mandate(CouncilRole.SKEPTIC, CouncilInputKind.EVIDENCE)
    packet = _packet(mandate, (_input(CouncilInputKind.EVIDENCE, "1"),))
    with pytest.raises(ResearchCouncilError, match="BLOCKED_OPINION_CANNOT_HAVE_DIRECTIONAL_VIEW"):
        AgentOpinion(
            security_id=SECURITY_ID,
            role=mandate.role,
            as_of=NOW,
            mandate_id=mandate.mandate_id,
            input_packet_id=packet.packet_id,
            status=ReadinessStatus.BLOCKED,
            stance=OpinionStance.NEGATIVE,
            score=-50,
            confidence=0.0,
            input_quality_score=0.0,
            thesis="Blocked",
            counterpoint="Blocked",
            evidence_refs=(),
            invalidation_conditions=(),
            blockers=("DATA_MISSING",),
        )


def test_assembler_rejects_opinion_citing_input_not_in_its_packet():
    mandate = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    registry = AgentMandateRegistry((mandate,))
    packet = _packet(mandate, (_input(CouncilInputKind.FEATURE, "1"),))
    opinion = AgentOpinion(
        security_id=SECURITY_ID,
        role=mandate.role,
        as_of=NOW,
        mandate_id=mandate.mandate_id,
        input_packet_id=packet.packet_id,
        status=ReadinessStatus.PASS,
        stance=OpinionStance.POSITIVE,
        score=25,
        confidence=0.5,
        input_quality_score=1.0,
        thesis="Positive thesis",
        counterpoint="Counterpoint",
        evidence_refs=(
            OpinionEvidenceRef(
                input_id="f" * 64,
                effect=EvidenceEffect.SUPPORTS,
                note="Unknown input",
            ),
        ),
        invalidation_conditions=("Invalidation",),
    )
    with pytest.raises(ResearchCouncilError, match="COUNCIL_OPINION_CITES_UNKNOWN_INPUT"):
        ResearchCouncilAssembler(registry).assemble(
            security_id=SECURITY_ID,
            as_of=NOW,
            input_packets=(packet,),
            opinions=(opinion,),
            required_roles=(CouncilRole.MOMENTUM,),
        )


def test_missing_required_role_blocks_council_without_creating_consensus():
    momentum = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    bear = _mandate(CouncilRole.BEAR, CouncilInputKind.RESEARCH_FACT)
    registry = AgentMandateRegistry((momentum, bear))
    packet = _packet(momentum, (_input(CouncilInputKind.FEATURE, "1"),))
    opinion = _opinion(momentum, packet)
    council = ResearchCouncilAssembler(registry).assemble(
        security_id=SECURITY_ID,
        as_of=NOW,
        input_packets=(packet,),
        opinions=(opinion,),
        required_roles=(CouncilRole.MOMENTUM, CouncilRole.BEAR),
    )
    assert council.status is ReadinessStatus.BLOCKED
    assert council.missing_roles == (CouncilRole.BEAR,)
    assert "MISSING_COUNCIL_ROLE:BEAR" in council.blockers
    assert not hasattr(council, "composite_score")


def test_warning_opinion_propagates_warning_without_becoming_trade_decision():
    momentum = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    registry = AgentMandateRegistry((momentum,))
    packet = _packet(momentum, (_input(CouncilInputKind.FEATURE, "1"),))
    opinion = _opinion(
        momentum,
        packet,
        status=ReadinessStatus.WARNING,
        warning="LOW_INPUT_QUALITY",
    )
    council = ResearchCouncilAssembler(registry).assemble(
        security_id=SECURITY_ID,
        as_of=NOW,
        input_packets=(packet,),
        opinions=(opinion,),
        required_roles=(CouncilRole.MOMENTUM,),
    )
    assert council.status is ReadinessStatus.WARNING
    assert council.trading_authorized is False
    assert council.live_trading_enabled is False


def test_council_packet_id_is_deterministic_across_input_order():
    momentum = _mandate(CouncilRole.MOMENTUM, CouncilInputKind.FEATURE)
    bear = _mandate(CouncilRole.BEAR, CouncilInputKind.RESEARCH_FACT)
    registry = AgentMandateRegistry((momentum, bear))
    momentum_packet = _packet(momentum, (_input(CouncilInputKind.FEATURE, "1"),))
    bear_packet = _packet(bear, (_input(CouncilInputKind.RESEARCH_FACT, "2"),))
    momentum_opinion = _opinion(momentum, momentum_packet)
    bear_opinion = _opinion(bear, bear_packet)
    assembler = ResearchCouncilAssembler(registry)
    left = assembler.assemble(
        security_id=SECURITY_ID,
        as_of=NOW,
        input_packets=(momentum_packet, bear_packet),
        opinions=(momentum_opinion, bear_opinion),
        required_roles=(CouncilRole.MOMENTUM, CouncilRole.BEAR),
    )
    right = assembler.assemble(
        security_id=SECURITY_ID,
        as_of=NOW,
        input_packets=(bear_packet, momentum_packet),
        opinions=(bear_opinion, momentum_opinion),
        required_roles=(CouncilRole.BEAR, CouncilRole.MOMENTUM),
    )
    assert left.status is ReadinessStatus.PASS
    assert left.council_packet_id == right.council_packet_id
