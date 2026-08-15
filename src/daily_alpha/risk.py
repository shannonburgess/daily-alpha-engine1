"""Fail-closed, versioned portfolio risk gate for paper-trading decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .portfolio import PortfolioSnapshot


class RiskDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskReason(StrEnum):
    APPROVED = "APPROVED"
    PORTFOLIO_DATA_BLOCKED = "PORTFOLIO_DATA_BLOCKED"
    INVALID_NAV = "INVALID_NAV"
    INVALID_PLANNED_LOSS = "INVALID_PLANNED_LOSS"
    POSITION_RISK_LIMIT = "POSITION_RISK_LIMIT"
    DAILY_NEW_RISK_LIMIT = "DAILY_NEW_RISK_LIMIT"
    DAILY_POSITION_LIMIT = "DAILY_POSITION_LIMIT"
    DAILY_LOSS_LOCKOUT = "DAILY_LOSS_LOCKOUT"
    WEEKLY_DRAWDOWN_PAUSE = "WEEKLY_DRAWDOWN_PAUSE"
    ROLLING_DRAWDOWN_REVIEW = "ROLLING_DRAWDOWN_REVIEW"
    CLUSTER_RISK_LIMIT = "CLUSTER_RISK_LIMIT"


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "2026-08-15-v1"
    max_position_loss_nav: float = 0.005
    max_daily_new_risk_nav: float = 0.0075
    max_new_positions_per_day: int = 2
    daily_loss_lockout_nav: float = 0.02
    weekly_drawdown_pause_nav: float = 0.04
    rolling_drawdown_review_nav: float = 0.06
    max_cluster_risk_nav: float = 0.0075

    def __post_init__(self) -> None:
        ratios = (
            self.max_position_loss_nav,
            self.max_daily_new_risk_nav,
            self.daily_loss_lockout_nav,
            self.weekly_drawdown_pause_nav,
            self.rolling_drawdown_review_nav,
            self.max_cluster_risk_nav,
        )
        if not self.version:
            raise ValueError("risk policy version is required")
        if any(ratio <= 0 or ratio > 1 for ratio in ratios):
            raise ValueError("risk-policy NAV ratios must be within (0, 1]")
        if self.max_new_positions_per_day <= 0:
            raise ValueError("max_new_positions_per_day must be positive")


@dataclass(frozen=True)
class PortfolioRiskState:
    daily_new_risk: float = 0.0
    new_positions_today: int = 0
    daily_loss: float = 0.0
    weekly_drawdown: float = 0.0
    rolling_drawdown: float = 0.0
    cluster_risk: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        values = (
            self.daily_new_risk,
            self.daily_loss,
            self.weekly_drawdown,
            self.rolling_drawdown,
        )
        if any(value < 0 for value in values) or self.new_positions_today < 0:
            raise ValueError("risk-state values must be non-negative")
        if any(value < 0 for _, value in self.cluster_risk):
            raise ValueError("cluster risk must be non-negative")

    def risk_for_cluster(self, cluster_id: str) -> float:
        return sum(value for name, value in self.cluster_risk if name == cluster_id)


@dataclass(frozen=True)
class ProposedTradeRisk:
    decision_id: str
    symbol: str
    planned_loss: float
    cluster_id: str


@dataclass(frozen=True)
class RiskDecision:
    status: RiskDecisionStatus
    reasons: tuple[RiskReason, ...]
    decision_id: str
    symbol: str
    snapshot_id: str
    policy_version: str
    nav: float
    planned_loss: float
    planned_loss_nav: float

    @property
    def approved(self) -> bool:
        return self.status == RiskDecisionStatus.APPROVED

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["reasons"] = [reason.value for reason in self.reasons]
        return payload


class PortfolioRiskEngine:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        *,
        snapshot: PortfolioSnapshot,
        state: PortfolioRiskState,
        proposed: ProposedTradeRisk,
    ) -> RiskDecision:
        nav = snapshot.net_liquidating_value
        reasons: list[RiskReason] = []
        if snapshot.blocks_new_risk:
            reasons.append(RiskReason.PORTFOLIO_DATA_BLOCKED)
        if nav <= 0:
            reasons.append(RiskReason.INVALID_NAV)
        if proposed.planned_loss <= 0:
            reasons.append(RiskReason.INVALID_PLANNED_LOSS)

        planned_loss_nav = proposed.planned_loss / nav if nav > 0 else float("inf")
        if nav > 0:
            self._apply_nav_limits(reasons, nav=nav, state=state, proposed=proposed)

        if reasons:
            status = RiskDecisionStatus.REJECTED
            final_reasons = tuple(dict.fromkeys(reasons))
        else:
            status = RiskDecisionStatus.APPROVED
            final_reasons = (RiskReason.APPROVED,)
        return RiskDecision(
            status=status,
            reasons=final_reasons,
            decision_id=proposed.decision_id,
            symbol=proposed.symbol,
            snapshot_id=snapshot.snapshot_id,
            policy_version=self.policy.version,
            nav=nav,
            planned_loss=proposed.planned_loss,
            planned_loss_nav=planned_loss_nav,
        )

    def _apply_nav_limits(
        self,
        reasons: list[RiskReason],
        *,
        nav: float,
        state: PortfolioRiskState,
        proposed: ProposedTradeRisk,
    ) -> None:
        policy = self.policy
        if proposed.planned_loss / nav > policy.max_position_loss_nav:
            reasons.append(RiskReason.POSITION_RISK_LIMIT)
        if (state.daily_new_risk + proposed.planned_loss) / nav > policy.max_daily_new_risk_nav:
            reasons.append(RiskReason.DAILY_NEW_RISK_LIMIT)
        if state.new_positions_today >= policy.max_new_positions_per_day:
            reasons.append(RiskReason.DAILY_POSITION_LIMIT)
        if state.daily_loss / nav >= policy.daily_loss_lockout_nav:
            reasons.append(RiskReason.DAILY_LOSS_LOCKOUT)
        if state.weekly_drawdown / nav >= policy.weekly_drawdown_pause_nav:
            reasons.append(RiskReason.WEEKLY_DRAWDOWN_PAUSE)
        if state.rolling_drawdown / nav >= policy.rolling_drawdown_review_nav:
            reasons.append(RiskReason.ROLLING_DRAWDOWN_REVIEW)
        cluster_total = state.risk_for_cluster(proposed.cluster_id) + proposed.planned_loss
        if cluster_total / nav > policy.max_cluster_risk_nav:
            reasons.append(RiskReason.CLUSTER_RISK_LIMIT)

