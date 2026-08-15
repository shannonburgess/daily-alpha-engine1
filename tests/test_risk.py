from daily_alpha.portfolio import (
    AssetType,
    PortfolioDataStatus,
    PortfolioSnapshot,
    Position,
)
from daily_alpha.risk import (
    PortfolioRiskEngine,
    PortfolioRiskState,
    ProposedTradeRisk,
    RiskReason,
)


def snapshot(*, status=PortfolioDataStatus.AVAILABLE) -> PortfolioSnapshot:
    return PortfolioSnapshot.create(
        snapshot_id="snapshot-risk-1",
        account_id="paper-1",
        source="TEST",
        as_of="2026-08-15T12:00:00+00:00",
        cash=100_000,
        buying_power=80_000,
        positions=(Position("SPY", AssetType.STOCK, 0, 500, 500),),
        data_status=status,
    )


def proposed(loss: float = 500, cluster: str = "TECH") -> ProposedTradeRisk:
    return ProposedTradeRisk("decision-1", "AAPL", loss, cluster)


def test_approves_trade_at_exact_position_limit():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(), state=PortfolioRiskState(), proposed=proposed(500)
    )
    assert decision.approved is True
    assert decision.reasons == (RiskReason.APPROVED,)
    assert decision.planned_loss_nav == 0.005
    assert decision.policy_version == "2026-08-15-v2"


def test_rejects_trade_over_position_loss_limit():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(), state=PortfolioRiskState(), proposed=proposed(501)
    )
    assert decision.approved is False
    assert RiskReason.POSITION_RISK_LIMIT in decision.reasons


def test_rejects_when_daily_new_risk_would_exceed_limit():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(),
        state=PortfolioRiskState(daily_new_risk=300),
        proposed=proposed(500),
    )
    assert RiskReason.DAILY_NEW_RISK_LIMIT in decision.reasons


def test_rejects_third_new_position():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(),
        state=PortfolioRiskState(new_positions_today=2),
        proposed=proposed(),
    )
    assert RiskReason.DAILY_POSITION_LIMIT in decision.reasons


def test_drawdown_thresholds_lock_or_pause_new_risk():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(),
        state=PortfolioRiskState(
            daily_loss=2_000,
            weekly_drawdown=4_000,
            rolling_drawdown=6_000,
        ),
        proposed=proposed(),
    )
    assert RiskReason.DAILY_LOSS_LOCKOUT in decision.reasons
    assert RiskReason.WEEKLY_DRAWDOWN_PAUSE in decision.reasons
    assert RiskReason.ROLLING_DRAWDOWN_REVIEW in decision.reasons


def test_stale_portfolio_state_fails_closed():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(status=PortfolioDataStatus.STALE),
        state=PortfolioRiskState(),
        proposed=proposed(),
    )
    assert decision.approved is False
    assert RiskReason.PORTFOLIO_DATA_BLOCKED in decision.reasons


def test_correlated_cluster_risk_is_combined():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(),
        state=PortfolioRiskState(cluster_risk=(("TECH", 300), ("ENERGY", 500))),
        proposed=proposed(500, "TECH"),
    )
    assert RiskReason.CLUSTER_RISK_LIMIT in decision.reasons


def test_all_rejection_reasons_are_preserved_for_audit():
    decision = PortfolioRiskEngine().evaluate(
        snapshot=snapshot(status=PortfolioDataStatus.PARTIAL),
        state=PortfolioRiskState(new_positions_today=2, daily_loss=2_000),
        proposed=proposed(800),
    )
    assert set(decision.reasons) >= {
        RiskReason.PORTFOLIO_DATA_BLOCKED,
        RiskReason.POSITION_RISK_LIMIT,
        RiskReason.DAILY_NEW_RISK_LIMIT,
        RiskReason.DAILY_POSITION_LIMIT,
        RiskReason.DAILY_LOSS_LOCKOUT,
        RiskReason.CLUSTER_RISK_LIMIT,
    }
