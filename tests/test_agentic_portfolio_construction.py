from datetime import UTC, datetime

import pytest

from daily_alpha.agentic.cio_fusion import CIOInvestmentDecision, InvestmentAction
from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.portfolio_construction import (
    AllocationDirection,
    CorrelationSurface,
    FactorLimit,
    MarginalPortfolioConstructor,
    OpportunityEstimate,
    PortfolioConstructionError,
    PortfolioConstructionPolicy,
    PortfolioPosition,
    PortfolioSnapshot,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _decision(security_id: str, action: InvestmentAction) -> CIOInvestmentDecision:
    return CIOInvestmentDecision(
        security_id=security_id,
        as_of=NOW,
        fusion_input_id=(security_id.lower() * 64)[:64],
        action=action,
        conviction=0.8,
        expected_alpha_score=60,
        rationale="The governed investment evidence supports this intent.",
        opposing_case="The opposing case remains material and monitored.",
        invalidation_conditions=("The evidence complex materially reverses",),
        cited_opinion_ids=("a" * 64,),
        cited_model_view_ids=(),
        reasoning_engine="TEST_CIO",
        reasoning_engine_version="V1",
    )


def _opportunity(
    decision: CIOInvestmentDecision,
    *,
    expected_return_bps: float = 1800.0,
    volatility: float = 0.20,
    confidence: float = 0.9,
    sector: str = "TECH",
    capacity: float = 0.10,
    factors=None,
) -> OpportunityEstimate:
    return OpportunityEstimate(
        security_id=decision.security_id,
        as_of=NOW,
        cio_decision_id=decision.decision_id,
        cio_action=decision.action,
        expected_return_bps=expected_return_bps,
        annualized_volatility=volatility,
        confidence=confidence,
        sector=sector,
        liquidity_capacity_weight=capacity,
        factor_exposures=factors or {},
        forecast_model_id="EXPECTED_RETURN_MODEL",
        forecast_model_version="V1",
    )


def _portfolio(*, cash: float = 0.50) -> PortfolioSnapshot:
    invested = 1.0 - cash
    a_weight = invested * 0.6
    b_weight = invested * 0.4
    return PortfolioSnapshot(
        as_of=NOW,
        nav=1_000_000.0,
        cash_weight=cash,
        positions=(
            PortfolioPosition(
                security_id="A",
                weight=a_weight,
                sector="ENERGY",
                annualized_volatility=0.22,
                factor_exposures={"BETA": 1.0},
            ),
            PortfolioPosition(
                security_id="B",
                weight=b_weight,
                sector="FINANCIALS",
                annualized_volatility=0.18,
                factor_exposures={"BETA": 0.8},
            ),
        ),
        source_id="portfolio-snapshot",
    )


def _correlations(ids=("A", "B", "C", "D")) -> CorrelationSurface:
    loadings = {"A": 0.7, "B": 0.6, "C": 0.1, "D": 0.9, "E": 0.3}
    matrix = []
    for left in ids:
        row = []
        for right in ids:
            row.append(1.0 if left == right else loadings[left] * loadings[right])
        matrix.append(tuple(row))
    return CorrelationSurface(
        as_of=NOW,
        security_ids=tuple(ids),
        matrix=tuple(matrix),
        source_id="corr-surface",
        model_version="V1",
    )


def test_portfolio_snapshot_requires_weights_to_sum_to_one():
    with pytest.raises(PortfolioConstructionError, match="PORTFOLIO_WEIGHTS_MUST_SUM_TO_ONE"):
        PortfolioSnapshot(
            as_of=NOW,
            nav=1_000_000,
            cash_weight=0.5,
            positions=(
                PortfolioPosition("A", 0.4, "TECH", 0.2),
            ),
            source_id="x",
        )


def test_correlation_surface_rejects_non_psd_matrix():
    with pytest.raises(
        PortfolioConstructionError,
        match="CORRELATION_MATRIX_NOT_POSITIVE_SEMIDEFINITE",
    ):
        CorrelationSurface(
            as_of=NOW,
            security_ids=("A", "B", "C"),
            matrix=((1.0, 0.9, 0.9), (0.9, 1.0, -0.9), (0.9, -0.9, 1.0)),
            source_id="bad",
            model_version="V1",
        )


def test_low_correlation_candidate_wins_first_marginal_risk_allocation():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    d = _decision("D", InvestmentAction.BUY)
    opportunities = (_opportunity(c), _opportunity(d))
    constructor = MarginalPortfolioConstructor(PortfolioConstructionPolicy(max_turnover=0.02))
    proposal = constructor.propose(
        portfolio=portfolio,
        cio_decisions=(c, d),
        opportunities=opportunities,
        correlations=_correlations(),
    )
    assert proposal.status in {ReadinessStatus.PASS, ReadinessStatus.WARNING}
    assert len(proposal.selected_assessments) == 1
    assert proposal.selected_assessments[0].security_id == "C"
    assert proposal.capital_allocation_authorized is False
    assert proposal.risk_governor_authorized is False
    assert proposal.execution_authorized is False


def test_sector_limit_reduces_candidate_headroom_instead_of_blind_conviction_sizing():
    portfolio = PortfolioSnapshot(
        as_of=NOW,
        nav=1_000_000,
        cash_weight=0.51,
        positions=(
            PortfolioPosition("A", 0.29, "TECH", 0.2),
            PortfolioPosition("B", 0.20, "FINANCIALS", 0.2),
        ),
        source_id="sector-test",
    )
    c = _decision("C", InvestmentAction.BUY)
    policy = PortfolioConstructionPolicy(max_sector_weight=0.30, max_single_step_weight=0.05)
    proposal = MarginalPortfolioConstructor(policy).propose(
        portfolio=portfolio,
        cio_decisions=(c,),
        opportunities=(_opportunity(c, sector="TECH"),),
        correlations=_correlations(ids=("A", "B", "C")),
    )
    target = next(item for item in proposal.target_allocations if item.security_id == "C")
    assert target.target_weight <= 0.01 + 1e-9
    tech_weight = sum(
        item.target_weight
        for item in proposal.target_allocations
        if item.security_id in {"A", "C"}
    )
    assert tech_weight <= 0.30 + 1e-9


def test_liquidity_capacity_caps_target_weight():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    proposal = MarginalPortfolioConstructor(
        PortfolioConstructionPolicy(max_position_weight=0.20, max_single_step_weight=0.05)
    ).propose(
        portfolio=portfolio,
        cio_decisions=(c,),
        opportunities=(_opportunity(c, capacity=0.03),),
        correlations=_correlations(ids=("A", "B", "C")),
    )
    target = next(item for item in proposal.target_allocations if item.security_id == "C")
    assert target.target_weight <= 0.03 + 1e-9


def test_factor_limit_caps_incremental_exposure():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    policy = PortfolioConstructionPolicy(
        max_single_step_weight=0.05,
        factor_limits=(FactorLimit("BETA", 0.55),),
    )
    # Current beta exposure = .3*1 + .2*.8 = .46; candidate beta=2 => headroom .045.
    proposal = MarginalPortfolioConstructor(policy).propose(
        portfolio=portfolio,
        cio_decisions=(c,),
        opportunities=(_opportunity(c, factors={"BETA": 2.0}),),
        correlations=_correlations(ids=("A", "B", "C")),
    )
    target = next(item for item in proposal.target_allocations if item.security_id == "C")
    assert target.target_weight <= 0.045 + 1e-9


def test_sell_intent_translates_to_zero_target_but_not_execution():
    portfolio = _portfolio()
    sell = _decision("A", InvestmentAction.SELL)
    constructor = MarginalPortfolioConstructor(PortfolioConstructionPolicy(max_turnover=0.50))
    proposal = constructor.propose(
        portfolio=portfolio,
        cio_decisions=(sell,),
        opportunities=(_opportunity(sell, expected_return_bps=-1000, sector="ENERGY"),),
        correlations=_correlations(ids=("A", "B")),
    )
    target = next(item for item in proposal.target_allocations if item.security_id == "A")
    assert target.target_weight == 0.0
    assert target.direction is AllocationDirection.DECREASE
    assert proposal.target_cash_weight > portfolio.cash_weight
    assert proposal.execution_authorized is False


def test_trim_intent_reduces_position_by_governed_policy_fraction():
    portfolio = _portfolio()
    trim = _decision("A", InvestmentAction.TRIM)
    proposal = MarginalPortfolioConstructor(
        PortfolioConstructionPolicy(trim_min_fraction=0.25, max_single_step_weight=0.02)
    ).propose(
        portfolio=portfolio,
        cio_decisions=(trim,),
        opportunities=(_opportunity(trim, expected_return_bps=200, sector="ENERGY"),),
        correlations=_correlations(ids=("A", "B")),
    )
    target = next(item for item in proposal.target_allocations if item.security_id == "A")
    assert target.target_weight < portfolio.position_map["A"].weight
    assert target.direction is AllocationDirection.DECREASE


def test_missing_correlation_for_risk_on_candidate_blocks_proposal():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    proposal = MarginalPortfolioConstructor().propose(
        portfolio=portfolio,
        cio_decisions=(c,),
        opportunities=(_opportunity(c),),
        correlations=_correlations(ids=("A", "B")),
    )
    assert proposal.status is ReadinessStatus.BLOCKED
    assert "CORRELATION_SECURITY_MISSING:C" in proposal.blockers
    assert proposal.risk_governor_authorized is False


def test_opportunity_must_match_exact_cio_decision_lineage():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    opportunity = OpportunityEstimate(
        security_id="C",
        as_of=NOW,
        cio_decision_id="f" * 64,
        cio_action=InvestmentAction.BUY,
        expected_return_bps=1000,
        annualized_volatility=0.2,
        confidence=0.8,
        sector="TECH",
        liquidity_capacity_weight=0.1,
        forecast_model_id="FORECAST",
        forecast_model_version="V1",
    )
    with pytest.raises(
        PortfolioConstructionError,
        match="OPPORTUNITY_CIO_DECISION_LINEAGE_MISMATCH",
    ):
        MarginalPortfolioConstructor().propose(
            portfolio=portfolio,
            cio_decisions=(c,),
            opportunities=(opportunity,),
            correlations=_correlations(ids=("A", "B", "C")),
        )


def test_hedge_intent_is_not_silently_forced_into_long_only_allocator():
    portfolio = _portfolio()
    hedge = _decision("C", InvestmentAction.HEDGE)
    proposal = MarginalPortfolioConstructor().propose(
        portfolio=portfolio,
        cio_decisions=(hedge,),
        opportunities=(_opportunity(hedge),),
        correlations=_correlations(ids=("A", "B", "C")),
    )
    assert proposal.status is ReadinessStatus.WARNING
    assert any(item.startswith("HEDGE_SLEEVE_NOT_IMPLEMENTED_IN_LONG_ONLY_V1") for item in proposal.warnings)


def test_proposal_is_deterministic_across_opportunity_input_order():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    d = _decision("D", InvestmentAction.BUY)
    c_opp = _opportunity(c)
    d_opp = _opportunity(d, expected_return_bps=1500)
    constructor = MarginalPortfolioConstructor()
    left = constructor.propose(
        portfolio=portfolio,
        cio_decisions=(c, d),
        opportunities=(c_opp, d_opp),
        correlations=_correlations(),
    )
    right = constructor.propose(
        portfolio=portfolio,
        cio_decisions=(d, c),
        opportunities=(d_opp, c_opp),
        correlations=_correlations(),
    )
    assert left.proposal_id == right.proposal_id


def test_portfolio_proposal_cannot_claim_risk_or_execution_authority():
    portfolio = _portfolio()
    c = _decision("C", InvestmentAction.BUY)
    proposal = MarginalPortfolioConstructor().propose(
        portfolio=portfolio,
        cio_decisions=(c,),
        opportunities=(_opportunity(c),),
        correlations=_correlations(ids=("A", "B", "C")),
    )
    with pytest.raises(
        PortfolioConstructionError,
        match="ALLOCATION_PROPOSAL_MUST_REMAIN_BELOW_RISK_GOVERNOR",
    ):
        proposal.__class__(
            as_of=proposal.as_of,
            portfolio_snapshot_id=proposal.portfolio_snapshot_id,
            correlation_surface_id=proposal.correlation_surface_id,
            policy_id=proposal.policy_id,
            target_allocations=proposal.target_allocations,
            target_cash_weight=proposal.target_cash_weight,
            estimated_portfolio_volatility=proposal.estimated_portfolio_volatility,
            estimated_turnover=proposal.estimated_turnover,
            objective_utility_bps=proposal.objective_utility_bps,
            selected_assessments=proposal.selected_assessments,
            excluded_opportunity_ids=proposal.excluded_opportunity_ids,
            status=proposal.status,
            blockers=proposal.blockers,
            warnings=proposal.warnings,
            risk_governor_authorized=True,
        )
