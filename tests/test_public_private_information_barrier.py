from datetime import UTC, datetime

import pytest

from daily_alpha.opportunity_contracts import (
    ConflictDisclosure,
    ConflictType,
    EligibilityState,
    InformationClassification,
    InstrumentType,
    InvestmentDirection,
    InvestmentOpportunityEnvelope,
    LiquidityState,
    MarketDomain,
    PrimaryAssetClass,
)
from daily_alpha.public_private_information_barrier import (
    InformationBarrierDisposition,
    InformationBarrierError,
    InformationBarrierReason,
    PublicMarketInformationBarrierDecision,
    evaluate_public_market_information_barrier,
)

AS_OF = datetime(2026, 8, 23, 19, 0, tzinfo=UTC)


def _public_target() -> InvestmentOpportunityEnvelope:
    return InvestmentOpportunityEnvelope(
        as_of=AS_OF,
        thesis_id="AI-INFRASTRUCTURE",
        subject_id="PUBLIC:MU",
        issuer_id="ISSUER:MICRON",
        market_domain=MarketDomain.PUBLIC,
        primary_asset_class=PrimaryAssetClass.EQUITY,
        instrument_type=InstrumentType.SHARE,
        exposure="MEMORY",
        direction=InvestmentDirection.LONG,
        summary="Public market expression.",
        confidence=0.7,
        liquidity_state=LiquidityState.PASS,
        eligibility_state=EligibilityState.AVAILABLE,
        evidence_ids=("ev-public-1",),
    )


def _private_source(
    *,
    classification: InformationClassification = InformationClassification.PUBLIC,
    public_use: bool = True,
    blocked_conflict: bool = False,
) -> InvestmentOpportunityEnvelope:
    conflicts = ()
    evidence_ids = ["ev-private-1"]
    if blocked_conflict:
        conflicts = (
            ConflictDisclosure(
                as_of=AS_OF,
                conflict_type=ConflictType.BOARD_ROLE,
                subject_id="PRIVATE:GRIDCO",
                related_entity_id="PERSON:BOARD-MEMBER",
                evidence_ids=("ev-conflict-1",),
                public_market_use_permitted=False,
            ),
        )
        evidence_ids.append("ev-conflict-1")
    return InvestmentOpportunityEnvelope(
        as_of=AS_OF,
        thesis_id="AI-INFRASTRUCTURE",
        subject_id="PRIVATE:GRIDCO",
        issuer_id="ISSUER:GRIDCO",
        market_domain=MarketDomain.PRIVATE,
        primary_asset_class=PrimaryAssetClass.EQUITY,
        instrument_type=InstrumentType.PRIVATE_COMPANY_EQUITY,
        exposure="POWER",
        direction=InvestmentDirection.LONG,
        summary="Private market evidence source.",
        confidence=0.6,
        liquidity_state=LiquidityState.WARNING,
        eligibility_state=EligibilityState.NOT_SUPPORTED,
        evidence_ids=tuple(evidence_ids),
        conflicts=conflicts,
        information_classification=classification,
        public_market_research_use_permitted=public_use,
    )


def test_public_private_graph_evidence_can_be_allowed_only_when_source_is_public() -> None:
    source = _private_source()
    target = _public_target()

    decision = evaluate_public_market_information_barrier(
        as_of=AS_OF,
        policy_id="CR-INFO-BARRIER-V1",
        source=source,
        target=target,
        evidence_ids=("ev-private-1",),
    )

    assert decision.disposition is InformationBarrierDisposition.ALLOW_PUBLIC_RESEARCH
    assert decision.reason_codes == (InformationBarrierReason.SOURCE_INFORMATION_PUBLIC,)
    assert decision.decision_id
    assert decision.execution_authorized is False
    assert decision.trading_authorized is False
    assert decision.live_trading_enabled is False


def test_mnpi_private_evidence_is_blocked_from_public_market_research() -> None:
    source = _private_source(
        classification=InformationClassification.MNPI_RESTRICTED,
        public_use=False,
    )

    decision = evaluate_public_market_information_barrier(
        as_of=AS_OF,
        policy_id="CR-INFO-BARRIER-V1",
        source=source,
        target=_public_target(),
        evidence_ids=("ev-private-1",),
    )

    assert decision.disposition is InformationBarrierDisposition.BLOCK_PUBLIC_RESEARCH
    assert InformationBarrierReason.SOURCE_MNPI_RESTRICTED in decision.reason_codes
    assert InformationBarrierReason.SOURCE_PUBLIC_USE_NOT_PERMITTED in decision.reason_codes


def test_confidential_private_evidence_is_blocked_even_if_generic_flag_is_true() -> None:
    source = _private_source(
        classification=InformationClassification.CONFIDENTIAL,
        public_use=True,
    )

    decision = evaluate_public_market_information_barrier(
        as_of=AS_OF,
        policy_id="CR-INFO-BARRIER-V1",
        source=source,
        target=_public_target(),
        evidence_ids=("ev-private-1",),
    )

    assert decision.disposition is InformationBarrierDisposition.BLOCK_PUBLIC_RESEARCH
    assert InformationBarrierReason.SOURCE_CONFIDENTIAL in decision.reason_codes


def test_nonpermitted_conflict_blocks_public_use_without_deleting_shared_thesis() -> None:
    source = _private_source(blocked_conflict=True)

    decision = evaluate_public_market_information_barrier(
        as_of=AS_OF,
        policy_id="CR-INFO-BARRIER-V1",
        source=source,
        target=_public_target(),
        evidence_ids=("ev-private-1",),
    )

    assert decision.disposition is InformationBarrierDisposition.BLOCK_PUBLIC_RESEARCH
    assert InformationBarrierReason.SOURCE_CONFLICT_PUBLIC_USE_BLOCKED in decision.reason_codes
    assert decision.source_opportunity_id == source.opportunity_id


def test_information_barrier_rejects_evidence_not_present_in_source_lineage() -> None:
    with pytest.raises(
        InformationBarrierError,
        match="BARRIER_EVIDENCE_MUST_EXIST_IN_SOURCE_OPPORTUNITY",
    ):
        evaluate_public_market_information_barrier(
            as_of=AS_OF,
            policy_id="CR-INFO-BARRIER-V1",
            source=_private_source(),
            target=_public_target(),
            evidence_ids=("invented-evidence",),
        )


def test_information_barrier_record_cannot_smuggle_execution_authority() -> None:
    with pytest.raises(
        InformationBarrierError,
        match="INFORMATION_BARRIER_DECISION_HAS_FORBIDDEN_AUTHORITY",
    ):
        PublicMarketInformationBarrierDecision(
            as_of=AS_OF,
            policy_id="CR-INFO-BARRIER-V1",
            source_opportunity_id="private-opportunity",
            target_opportunity_id="public-opportunity",
            source_information_classification=InformationClassification.PUBLIC,
            evidence_ids=("ev-1",),
            disposition=InformationBarrierDisposition.ALLOW_PUBLIC_RESEARCH,
            reason_codes=(InformationBarrierReason.SOURCE_INFORMATION_PUBLIC,),
            execution_authorized=True,
        )
