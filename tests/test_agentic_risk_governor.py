from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.contracts import ReadinessStatus
from daily_alpha.agentic.portfolio_construction import (
    AllocationDirection,
    PortfolioAllocationProposal,
    PortfolioPosition,
    PortfolioSnapshot,
    TargetAllocation,
)
from daily_alpha.agentic.risk_governor import (
    DeterministicRiskGovernor,
    GovernanceLockState,
    RiskContext,
    RiskGovernorError,
    RiskPolicy,
    RiskVerdict,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        as_of=NOW,
        nav=1_000_000.0,
        cash_weight=0.50,
        positions=(
            PortfolioPosition("A", 0.30, "ENERGY", 0.22),
            PortfolioPosition("B", 0.20, "FINANCIALS", 0.18),
        ),
        source_id="portfolio",
    )


def _proposal(
    portfolio: PortfolioSnapshot,
    *,
    targets: dict[str, float],
    cash: float,
    volatility: float = 0.18,
    turnover: float = 0.05,
    status: ReadinessStatus = ReadinessStatus.PASS,
) -> PortfolioAllocationProposal:
    current = {item.security_id: item.weight for item in portfolio.positions}
    allocations = []
    for security_id in sorted(set(current) | set(targets)):
        before = current.get(security_id, 0.0)
        target = targets.get(security_id, before)
        delta = target - before
        direction = (
            AllocationDirection.INCREASE
            if delta > 1e-12
            else AllocationDirection.DECREASE
            if delta < -1e-12
            else AllocationDirection.UNCHANGED
        )
        allocations.append(
            TargetAllocation(
                security_id=security_id,
                current_weight=before,
                target_weight=target,
                delta_weight=delta,
                direction=direction,
                cio_decision_id=(security_id.lower() * 64)[:64],
            )
        )
    return PortfolioAllocationProposal(
        as_of=NOW,
        portfolio_snapshot_id=portfolio.snapshot_id,
        correlation_surface_id="c" * 64,
        policy_id="p" * 64,
        target_allocations=tuple(allocations),
        target_cash_weight=cash,
        estimated_portfolio_volatility=volatility,
        estimated_turnover=turnover,
        objective_utility_bps=100.0,
        selected_assessments=(),
        excluded_opportunity_ids=(),
        status=status,
        blockers=("UPSTREAM_BLOCK",) if status is ReadinessStatus.BLOCKED else (),
        warnings=(),
    )


def _context(
    *,
    observed_at: datetime | None = None,
    drawdown: float = 0.05,
    current_vol: float = 0.17,
    sectors=None,
    clusters=None,
    liquidity=None,
    events=None,
    status: ReadinessStatus = ReadinessStatus.PASS,
) -> RiskContext:
    return RiskContext(
        as_of=NOW,
        observed_at=observed_at or NOW - timedelta(seconds=30),
        current_drawdown=drawdown,
        current_portfolio_volatility=current_vol,
        sectors=sectors or {"A": "ENERGY", "B": "FINANCIALS", "C": "TECH"},
        correlation_clusters=clusters or {"A": "COMMODITY", "B": "VALUE", "C": "GROWTH"},
        liquidity_days_to_exit=liquidity or {"A": 1.0, "B": 1.0, "C": 1.0},
        days_to_material_event=events or {"A": 20, "B": 20, "C": 20},
        status=status,
        source_id="risk-context",
    )


def _governance(*, emergency_stop: bool = False, approved: bool = True) -> GovernanceLockState:
    return GovernanceLockState(
        as_of=NOW,
        emergency_stop=emergency_stop,
        model_stack_approved=approved,
        source_id="governance",
    )


def test_clean_allocation_receives_risk_approval_but_not_execution_authority():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    decision = DeterministicRiskGovernor().evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=_context(),
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.APPROVED
    assert decision.risk_governor_approved is True
    assert decision.capital_allocation_authorized is False
    assert decision.execution_authorized is False
    assert decision.live_trading_enabled is False


def test_position_limit_blocks_new_risk_increase():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.12}, cash=0.38)
    decision = DeterministicRiskGovernor().evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=_context(),
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.REJECTED
    assert "MAX_POSITION_WEIGHT:C" in decision.blockers


def test_sector_limit_blocks_concentration_increase():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    context = _context(sectors={"A": "TECH", "B": "FINANCIALS", "C": "TECH"})
    decision = DeterministicRiskGovernor(RiskPolicy(max_sector_weight=0.32)).evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.REJECTED
    assert "MAX_SECTOR_WEIGHT:TECH" in decision.blockers


def test_cluster_limit_blocks_hidden_correlated_concentration():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.08}, cash=0.42)
    context = _context(clusters={"A": "RISK_ON", "B": "VALUE", "C": "RISK_ON"})
    decision = DeterministicRiskGovernor(RiskPolicy(max_cluster_weight=0.35)).evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.REJECTED
    assert "MAX_CLUSTER_WEIGHT:RISK_ON" in decision.blockers


def test_drawdown_throttle_blocks_new_risk():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    decision = DeterministicRiskGovernor(RiskPolicy(max_drawdown=0.10)).evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=_context(drawdown=0.12),
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.REJECTED
    assert "DRAWDOWN_THROTTLE_BLOCKS_NEW_RISK" in decision.blockers


def test_material_event_blackout_blocks_only_increase():
    portfolio = _portfolio()
    increase = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    context = _context(events={"A": 20, "B": 20, "C": 1})
    rejected = DeterministicRiskGovernor().evaluate(
        proposal=increase,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert "MATERIAL_EVENT_BLACKOUT:C" in rejected.blockers

    reduction = _proposal(portfolio, targets={"A": 0.20}, cash=0.60, turnover=0.10)
    approved = DeterministicRiskGovernor().evaluate(
        proposal=reduction,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert approved.verdict is RiskVerdict.APPROVED


def test_illiquid_position_can_be_derisked_but_not_increased():
    portfolio = _portfolio()
    context = _context(liquidity={"A": 10.0, "B": 1.0, "C": 1.0})
    reduction = _proposal(portfolio, targets={"A": 0.20}, cash=0.60, turnover=0.10)
    reduced = DeterministicRiskGovernor().evaluate(
        proposal=reduction,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert reduced.verdict is RiskVerdict.APPROVED
    assert "ILLIQUID_POSITION_DERISKING:A" in reduced.warnings

    increase = _proposal(portfolio, targets={"A": 0.32}, cash=0.48, turnover=0.02)
    rejected = DeterministicRiskGovernor(RiskPolicy(max_position_weight=0.40)).evaluate(
        proposal=increase,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert "LIQUIDITY_DAYS_TO_EXIT:A" in rejected.blockers


def test_stale_risk_context_fails_closed():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    context = _context(observed_at=NOW - timedelta(minutes=30))
    decision = DeterministicRiskGovernor(RiskPolicy(max_context_age_seconds=300)).evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.REJECTED
    assert "RISK_CONTEXT_STALE" in decision.blockers


def test_governance_emergency_stop_overrides_everything_below_it():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    decision = DeterministicRiskGovernor().evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=_context(),
        governance=_governance(emergency_stop=True),
    )
    assert decision.verdict is RiskVerdict.REJECTED
    assert "GOVERNANCE_EMERGENCY_STOP" in decision.blockers


def test_derisking_is_allowed_even_when_existing_position_remains_over_limit():
    portfolio = PortfolioSnapshot(
        as_of=NOW,
        nav=1_000_000,
        cash_weight=0.50,
        positions=(
            PortfolioPosition("A", 0.35, "ENERGY", 0.22),
            PortfolioPosition("B", 0.15, "FINANCIALS", 0.18),
        ),
        source_id="over-limit-portfolio",
    )
    proposal = _proposal(portfolio, targets={"A": 0.25}, cash=0.60, turnover=0.10)
    context = _context()
    decision = DeterministicRiskGovernor(RiskPolicy(max_position_weight=0.10)).evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=context,
        governance=_governance(),
    )
    assert decision.verdict is RiskVerdict.APPROVED
    assert "POSITION_REMAINS_ABOVE_LIMIT_WHILE_DERISKING:A" in decision.warnings


def test_risk_decision_id_is_deterministic():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    governor = DeterministicRiskGovernor()
    first = governor.evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=_context(),
        governance=_governance(),
    )
    second = governor.evaluate(
        proposal=proposal,
        portfolio=portfolio,
        context=_context(),
        governance=_governance(),
    )
    assert first.decision_id == second.decision_id


def test_risk_governor_rejects_lineage_mismatch():
    portfolio = _portfolio()
    proposal = _proposal(portfolio, targets={"C": 0.05}, cash=0.45)
    other = PortfolioSnapshot(
        as_of=NOW,
        nav=900_000,
        cash_weight=0.50,
        positions=(
            PortfolioPosition("A", 0.30, "ENERGY", 0.22),
            PortfolioPosition("B", 0.20, "FINANCIALS", 0.18),
        ),
        source_id="other",
    )
    with pytest.raises(RiskGovernorError, match="RISK_PORTFOLIO_LINEAGE_MISMATCH"):
        DeterministicRiskGovernor().evaluate(
            proposal=proposal,
            portfolio=other,
            context=_context(),
            governance=_governance(),
        )
