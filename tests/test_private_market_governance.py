from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.opportunity_contracts import (
    EligibilityState,
    InformationClassification,
    InstrumentType,
    InvestmentDirection,
    InvestmentOpportunityEnvelope,
    LiquidityState,
    MarketDomain,
    PrimaryAssetClass,
)
from daily_alpha.private_market_governance import (
    InvestmentGovernanceBoundary,
    PrivateMarketDecisionContext,
    PrivateMarketGovernanceError,
    PrivateMarketValuationSnapshot,
    PrivateValuationMethod,
)

AS_OF = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)


def _private_credit() -> InvestmentOpportunityEnvelope:
    return InvestmentOpportunityEnvelope(
        as_of=AS_OF,
        thesis_id="AI-INFRASTRUCTURE",
        subject_id="PRIVATE:POWER-CREDIT-I",
        issuer_id="ISSUER:POWERCO",
        market_domain=MarketDomain.PRIVATE,
        primary_asset_class=PrimaryAssetClass.FIXED_INCOME_CREDIT,
        instrument_type=InstrumentType.CREDIT,
        exposure="data_center_power_financing",
        direction=InvestmentDirection.LONG,
        summary="Private credit expression of data-center power buildout.",
        confidence=0.61,
        liquidity_state=LiquidityState.WARNING,
        eligibility_state=EligibilityState.NOT_SUPPORTED,
        evidence_ids=("ev-credit-1", "ev-credit-valuation-1"),
        information_classification=InformationClassification.PUBLIC,
    )


def _governance(opportunity_id: str) -> InvestmentGovernanceBoundary:
    return InvestmentGovernanceBoundary(
        as_of=AS_OF,
        opportunity_id=opportunity_id,
        vehicle_context_id="vehicle-context-1",
        mandate_id="venture-mandate-1",
        conflict_policy_id="conflict-policy-1",
        information_barrier_policy_id="information-barrier-1",
        valuation_policy_id="valuation-policy-1",
        portfolio_policy_id="portfolio-policy-1",
        risk_policy_id="risk-policy-1",
        execution_policy_id="execution-policy-1",
    )


def _valuation(opportunity_id: str) -> PrivateMarketValuationSnapshot:
    return PrivateMarketValuationSnapshot(
        as_of=AS_OF,
        opportunity_id=opportunity_id,
        currency="usd",
        method=PrivateValuationMethod.COMPARABLES,
        base_value=50_000_000,
        low_value=42_000_000,
        high_value=60_000_000,
        evidence_ids=("ev-credit-valuation-1",),
    )


def test_private_credit_uses_shared_opportunity_with_separate_governance_layers() -> None:
    opportunity = _private_credit()
    governance = _governance(opportunity.opportunity_id)
    valuation = _valuation(opportunity.opportunity_id)
    context = PrivateMarketDecisionContext(
        as_of=AS_OF,
        opportunity_id=opportunity.opportunity_id,
        governance=governance,
        valuation=valuation,
        evidence_ids=opportunity.evidence_ids,
    )

    assert opportunity.market_domain is MarketDomain.PRIVATE
    assert opportunity.primary_asset_class is PrimaryAssetClass.FIXED_INCOME_CREDIT
    assert opportunity.instrument_type is InstrumentType.CREDIT
    assert governance.mandate_id == "venture-mandate-1"
    assert governance.conflict_policy_id == "conflict-policy-1"
    assert governance.information_barrier_policy_id == "information-barrier-1"
    assert governance.valuation_policy_id == "valuation-policy-1"
    assert governance.portfolio_policy_id == "portfolio-policy-1"
    assert governance.risk_policy_id == "risk-policy-1"
    assert governance.execution_policy_id == "execution-policy-1"
    assert governance.capital_commitment_authorized is False
    assert governance.execution_authorized is False
    assert context.decision_context_id


def test_private_valuation_is_not_observed_market_price() -> None:
    opportunity = _private_credit()

    with pytest.raises(
        PrivateMarketGovernanceError,
        match="PRIVATE_VALUATION_CANNOT_BE_MARKED_AS_OBSERVED_MARKET_PRICE",
    ):
        PrivateMarketValuationSnapshot(
            as_of=AS_OF,
            opportunity_id=opportunity.opportunity_id,
            currency="USD",
            method=PrivateValuationMethod.LAST_ROUND,
            base_value=50_000_000,
            evidence_ids=("ev-credit-valuation-1",),
            observed_market_price=True,
        )


def test_private_governance_cannot_smuggle_execution_or_capital_authority() -> None:
    opportunity = _private_credit()

    with pytest.raises(
        PrivateMarketGovernanceError,
        match="GOVERNANCE_BOUNDARY_HAS_FORBIDDEN_AUTHORITY",
    ):
        InvestmentGovernanceBoundary(
            as_of=AS_OF,
            opportunity_id=opportunity.opportunity_id,
            vehicle_context_id="vehicle-context-1",
            mandate_id="venture-mandate-1",
            conflict_policy_id="conflict-policy-1",
            information_barrier_policy_id="information-barrier-1",
            valuation_policy_id="valuation-policy-1",
            portfolio_policy_id="portfolio-policy-1",
            risk_policy_id="risk-policy-1",
            execution_policy_id="execution-policy-1",
            capital_commitment_authorized=True,
        )


def test_private_decision_context_rejects_future_valuation_knowledge() -> None:
    opportunity = _private_credit()
    governance = _governance(opportunity.opportunity_id)
    valuation = PrivateMarketValuationSnapshot(
        as_of=AS_OF + timedelta(minutes=1),
        opportunity_id=opportunity.opportunity_id,
        currency="USD",
        method=PrivateValuationMethod.COMPARABLES,
        base_value=50_000_000,
        evidence_ids=("ev-credit-valuation-1",),
    )

    with pytest.raises(
        PrivateMarketGovernanceError,
        match="PRIVATE_DECISION_CONTAINS_FUTURE_KNOWLEDGE",
    ):
        PrivateMarketDecisionContext(
            as_of=AS_OF,
            opportunity_id=opportunity.opportunity_id,
            governance=governance,
            valuation=valuation,
            evidence_ids=opportunity.evidence_ids,
        )


def test_private_valuation_requires_evidence_in_decision_lineage() -> None:
    opportunity = _private_credit()
    governance = _governance(opportunity.opportunity_id)
    valuation = _valuation(opportunity.opportunity_id)

    with pytest.raises(
        PrivateMarketGovernanceError,
        match="VALUATION_EVIDENCE_MUST_BE_IN_DECISION_EVIDENCE",
    ):
        PrivateMarketDecisionContext(
            as_of=AS_OF,
            opportunity_id=opportunity.opportunity_id,
            governance=governance,
            valuation=valuation,
            evidence_ids=("ev-credit-1",),
        )
