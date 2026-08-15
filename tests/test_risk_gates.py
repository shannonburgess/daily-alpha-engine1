import pytest

from daily_alpha.portfolio import PortfolioSnapshot
from daily_alpha.risk import PortfolioRiskEngine, PortfolioRiskState, ProposedTradeRisk, RiskReason


def snap():
    return PortfolioSnapshot("snap-1", 100_000)


def trade(**overrides):
    values = dict(decision_id="d-1", symbol="AAPL", planned_loss=500,
                  cluster_id="TECH", sector="Technology")
    values.update(overrides)
    return ProposedTradeRisk(**values)


@pytest.mark.parametrize(
    ("state", "proposed", "reason"),
    [
        (PortfolioRiskState(sector_risk=(("Technology", 600),)), trade(), RiskReason.SECTOR_RISK_LIMIT),
        (PortfolioRiskState(beta_exposure=99_900), trade(beta_exposure=200), RiskReason.BETA_EXPOSURE_LIMIT),
        (PortfolioRiskState(delta_exposure=99_900), trade(delta_exposure=200), RiskReason.DELTA_EXPOSURE_LIMIT),
        (PortfolioRiskState(), trade(event_risk=True), RiskReason.EVENT_RISK_BLOCKED),
        (PortfolioRiskState(), trade(liquidity_score=.59), RiskReason.LIQUIDITY_LIMIT),
        (PortfolioRiskState(total_risk=1_600), trade(), RiskReason.TOTAL_RISK_LIMIT),
    ],
)
def test_missing_acceptance_gates_fail_closed(state, proposed, reason):
    decision = PortfolioRiskEngine().evaluate(snapshot=snap(), state=state, proposed=proposed)
    assert not decision.approved
    assert reason in decision.reasons
    assert decision.risk_snapshot["proposed"]["decision_id"] == "d-1"


def test_exact_gate_boundaries_are_approved():
    state = PortfolioRiskState(
        sector_risk=(("Technology", 500),), total_risk=1_500,
        beta_exposure=99_500, delta_exposure=99_500,
    )
    decision = PortfolioRiskEngine().evaluate(snapshot=snap(), state=state, proposed=trade(liquidity_score=.60))
    assert decision.approved


def test_multiple_gate_failures_preserve_all_reason_codes():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snap(),
        state=PortfolioRiskState(total_risk=2_000, sector_risk=(("Technology", 1_000),)),
        proposed=trade(event_risk=True, liquidity_score=.1),
    )
    assert {RiskReason.TOTAL_RISK_LIMIT, RiskReason.SECTOR_RISK_LIMIT,
            RiskReason.EVENT_RISK_BLOCKED, RiskReason.LIQUIDITY_LIMIT} <= set(decision.reasons)
