from datetime import UTC, datetime

import pytest
from daily_alpha.opportunity_contracts import (
    BusinessLine,
    ConflictDisclosure,
    ConflictType,
    EligibilityState,
    InformationClassification,
    InstrumentType,
    InvestmentDirection,
    InvestmentOpportunityEnvelope,
    InvestmentVehicleContext,
    LiquidityState,
    MarketDomain,
    OpportunityContractError,
    OpportunityGraphEdge,
    OpportunityRelationship,
    PrimaryAssetClass,
    PrivateMarketTerms,
    PublicPrivateOpportunityGraph,
    VehicleType,
)


AS_OF = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)


def _public_equity() -> InvestmentOpportunityEnvelope:
    return InvestmentOpportunityEnvelope(
        as_of=AS_OF,
        thesis_id="AI-INFRASTRUCTURE",
        subject_id="PUBLIC:MU",
        issuer_id="ISSUER:MICRON",
        market_domain=MarketDomain.PUBLIC,
        primary_asset_class=PrimaryAssetClass.EQUITY,
        instrument_type=InstrumentType.SHARE,
        exposure="memory_semiconductors",
        direction=InvestmentDirection.LONG,
        summary="Public equity expression of AI memory demand.",
        confidence=0.78,
        liquidity_state=LiquidityState.PASS,
        eligibility_state=EligibilityState.AVAILABLE,
        evidence_ids=("ev-market-1", "ev-sector-1"),
        lineage_ids=("agent-equity-1", "cio-context-1"),
    )


def _venture_context() -> InvestmentVehicleContext:
    return InvestmentVehicleContext(
        as_of=AS_OF,
        business_line=BusinessLine.VENTURE_CAPITAL,
        vehicle_type=VehicleType.VENTURE_FUND,
        legal_entity_id="CONVEXRIDGE-VENTURES-GP",
        vehicle_id="CRV-FUND-I",
        mandate_id="CRV-MANDATE-V1",
        conflict_policy_id="CR-CONFLICT-V1",
        information_barrier_policy_id="CR-INFO-BARRIER-V1",
    )


def _private_company() -> InvestmentOpportunityEnvelope:
    conflict = ConflictDisclosure(
        as_of=AS_OF,
        conflict_type=ConflictType.VENTURE_HOLDING,
        subject_id="PRIVATE:GRIDCO",
        related_entity_id="CRV-FUND-I",
        evidence_ids=("ev-conflict-1",),
        public_market_use_permitted=True,
        note="Disclose any ConvexRidge Ventures economic interest downstream.",
    )
    terms = PrivateMarketTerms(
        stage="series a",
        financing_instrument=InstrumentType.SAFE,
        source_evidence_ids=("ev-private-round-1",),
        post_money_valuation=150_000_000,
        round_size=25_000_000,
        ownership_target=0.08,
        expected_liquidity_horizon_months=84,
    )
    return InvestmentOpportunityEnvelope(
        as_of=AS_OF,
        thesis_id="AI-INFRASTRUCTURE",
        subject_id="PRIVATE:GRIDCO",
        issuer_id="ISSUER:GRIDCO",
        market_domain=MarketDomain.PRIVATE,
        primary_asset_class=PrimaryAssetClass.EQUITY,
        instrument_type=InstrumentType.SAFE,
        exposure="grid_infrastructure",
        direction=InvestmentDirection.LONG,
        summary="Private company solving a power-delivery bottleneck for data centers.",
        confidence=0.66,
        liquidity_state=LiquidityState.WARNING,
        eligibility_state=EligibilityState.NOT_SUPPORTED,
        evidence_ids=("ev-conflict-1", "ev-private-round-1"),
        lineage_ids=("agent-thematic-1", "agent-private-market-1"),
        vehicle_context=_venture_context(),
        private_market_terms=terms,
        conflicts=(conflict,),
        information_classification=InformationClassification.PUBLIC,
        public_market_research_use_permitted=True,
    )


def test_public_and_private_opportunities_share_one_asset_neutral_contract() -> None:
    public = _public_equity()
    private = _private_company()

    assert public.market_domain is MarketDomain.PUBLIC
    assert private.market_domain is MarketDomain.PRIVATE
    assert public.primary_asset_class is PrimaryAssetClass.EQUITY
    assert private.primary_asset_class is PrimaryAssetClass.EQUITY
    assert private.vehicle_context is not None
    assert private.vehicle_context.vehicle_type is VehicleType.VENTURE_FUND
    assert public.execution_authorized is False
    assert private.execution_authorized is False
    assert public.live_trading_enabled is False
    assert private.live_trading_enabled is False


def test_private_terms_are_point_in_time_and_deterministically_identified() -> None:
    first = _private_company()
    second = _private_company()

    assert first.opportunity_id == second.opportunity_id
    assert first.private_market_terms is not None
    assert first.private_market_terms.stage == "SERIES A"
    assert first.private_market_terms.post_money_valuation == 150_000_000


def test_mnpi_restricted_private_information_cannot_feed_public_market_research() -> None:
    with pytest.raises(
        OpportunityContractError,
        match="MNPI_RESTRICTED_CANNOT_FEED_PUBLIC_MARKET_RESEARCH",
    ):
        InvestmentOpportunityEnvelope(
            as_of=AS_OF,
            thesis_id="AI-INFRASTRUCTURE",
            subject_id="PRIVATE:GRIDCO",
            issuer_id="ISSUER:GRIDCO",
            market_domain=MarketDomain.PRIVATE,
            primary_asset_class=PrimaryAssetClass.EQUITY,
            instrument_type=InstrumentType.PRIVATE_COMPANY_EQUITY,
            exposure="grid_infrastructure",
            direction=InvestmentDirection.LONG,
            summary="Restricted private-company information.",
            confidence=0.7,
            liquidity_state=LiquidityState.WARNING,
            eligibility_state=EligibilityState.NOT_AUTHORIZED,
            evidence_ids=("ev-mnpi-1",),
            information_classification=InformationClassification.MNPI_RESTRICTED,
            public_market_research_use_permitted=True,
        )


def test_authority_cannot_be_smuggled_into_the_opportunity_envelope() -> None:
    with pytest.raises(
        OpportunityContractError,
        match="OPPORTUNITY_ENVELOPE_HAS_FORBIDDEN_AUTHORITY",
    ):
        InvestmentOpportunityEnvelope(
            as_of=AS_OF,
            thesis_id="AI-INFRASTRUCTURE",
            subject_id="PUBLIC:MU",
            issuer_id="ISSUER:MICRON",
            market_domain=MarketDomain.PUBLIC,
            primary_asset_class=PrimaryAssetClass.EQUITY,
            instrument_type=InstrumentType.SHARE,
            exposure="memory_semiconductors",
            direction=InvestmentDirection.LONG,
            summary="Research only.",
            confidence=0.7,
            liquidity_state=LiquidityState.PASS,
            eligibility_state=EligibilityState.AVAILABLE,
            evidence_ids=("ev-1",),
            execution_authorized=True,
        )


def test_public_private_opportunity_graph_links_one_thesis_without_cross_authority() -> None:
    public = _public_equity()
    private = _private_company()
    edge = OpportunityGraphEdge(
        thesis_id="AI-INFRASTRUCTURE",
        from_opportunity_id=private.opportunity_id,
        to_opportunity_id=public.opportunity_id,
        relationship=OpportunityRelationship.BOTTLENECK_SOLVER,
        evidence_ids=("ev-graph-1",),
    )
    graph = PublicPrivateOpportunityGraph(
        as_of=AS_OF,
        thesis_id="AI-INFRASTRUCTURE",
        opportunities=(private, public),
        edges=(edge,),
        evidence_ids=("ev-graph-1",),
    )

    assert graph.graph_id
    assert {item.market_domain for item in graph.opportunities} == {
        MarketDomain.PUBLIC,
        MarketDomain.PRIVATE,
    }
    assert graph.capital_allocation_authorized is False
    assert graph.execution_authorized is False


def test_future_conflict_disclosure_is_rejected() -> None:
    future_conflict = ConflictDisclosure(
        as_of=datetime(2026, 8, 24, 14, 0, tzinfo=UTC),
        conflict_type=ConflictType.VENTURE_HOLDING,
        subject_id="PRIVATE:GRIDCO",
        related_entity_id="CRV-FUND-I",
        evidence_ids=("ev-future-conflict",),
        public_market_use_permitted=False,
    )
    with pytest.raises(
        OpportunityContractError,
        match="CONFLICT_DISCLOSURE_CANNOT_BE_FUTURE_DATED",
    ):
        InvestmentOpportunityEnvelope(
            as_of=AS_OF,
            thesis_id="AI-INFRASTRUCTURE",
            subject_id="PRIVATE:GRIDCO",
            issuer_id="ISSUER:GRIDCO",
            market_domain=MarketDomain.PRIVATE,
            primary_asset_class=PrimaryAssetClass.EQUITY,
            instrument_type=InstrumentType.PRIVATE_COMPANY_EQUITY,
            exposure="grid_infrastructure",
            direction=InvestmentDirection.LONG,
            summary="Future knowledge must not enter the record.",
            confidence=0.5,
            liquidity_state=LiquidityState.WARNING,
            eligibility_state=EligibilityState.NOT_SUPPORTED,
            evidence_ids=("ev-private-1",),
            conflicts=(future_conflict,),
        )
