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
    SECTOR_RISK_LIMIT = "SECTOR_RISK_LIMIT"
    BETA_EXPOSURE_LIMIT = "BETA_EXPOSURE_LIMIT"
    DELTA_EXPOSURE_LIMIT = "DELTA_EXPOSURE_LIMIT"
    EVENT_RISK_BLOCKED = "EVENT_RISK_BLOCKED"
    LIQUIDITY_LIMIT = "LIQUIDITY_LIMIT"
    TOTAL_RISK_LIMIT = "TOTAL_RISK_LIMIT"


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "2026-08-15-v2"
    max_position_loss_nav: float = 0.005
    max_daily_new_risk_nav: float = 0.0075
    max_new_positions_per_day: int = 2
    daily_loss_lockout_nav: float = 0.02
    weekly_drawdown_pause_nav: float = 0.04
    rolling_drawdown_review_nav: float = 0.06
    max_cluster_risk_nav: float = 0.0075
    max_sector_risk_nav: float = 0.01
    max_total_risk_nav: float = 0.02
    max_abs_beta_exposure_nav: float = 1.0
    max_abs_delta_exposure_nav: float = 1.0
    min_liquidity_score: float = 0.60
    block_event_risk: bool = True

    def __post_init__(self) -> None:
        ratios = (
            self.max_position_loss_nav, self.max_daily_new_risk_nav,
            self.daily_loss_lockout_nav, self.weekly_drawdown_pause_nav,
            self.rolling_drawdown_review_nav, self.max_cluster_risk_nav,
            self.max_sector_risk_nav, self.max_total_risk_nav,
            self.max_abs_beta_exposure_nav, self.max_abs_delta_exposure_nav,
        )
        if not self.version:
            raise ValueError("risk policy version is required")
        if any(ratio <= 0 for ratio in ratios):
            raise ValueError("risk-policy limits must be positive")
        if self.max_new_positions_per_day <= 0:
            raise ValueError("max_new_positions_per_day must be positive")
        if not 0 <= self.min_liquidity_score <= 1:
            raise ValueError("min_liquidity_score must be within [0, 1]")


@dataclass(frozen=True)
class PortfolioRiskState:
    daily_new_risk: float = 0.0
    new_positions_today: int = 0
    daily_loss: float = 0.0
    weekly_drawdown: float = 0.0
    rolling_drawdown: float = 0.0
    total_risk: float = 0.0
    beta_exposure: float = 0.0
    delta_exposure: float = 0.0
    cluster_risk: tuple[tuple[str, float], ...] = ()
    sector_risk: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        values = (self.daily_new_risk, self.daily_loss, self.weekly_drawdown,
                  self.rolling_drawdown, self.total_risk)
        if any(value < 0 for value in values) or self.new_positions_today < 0:
            raise ValueError("risk-state values must be non-negative")
        if any(value < 0 for _, value in (*self.cluster_risk, *self.sector_risk)):
            raise ValueError("cluster and sector risk must be non-negative")

    def risk_for_cluster(self, cluster_id: str) -> float:
        return sum(value for name, value in self.cluster_risk if name == cluster_id)

    def risk_for_sector(self, sector: str) -> float:
        return sum(value for name, value in self.sector_risk if name == sector)


@dataclass(frozen=True)
class ProposedTradeRisk:
    decision_id: str
    symbol: str
    planned_loss: float
    cluster_id: str
    sector: str = "UNKNOWN"
    beta_exposure: float = 0.0
    delta_exposure: float = 0.0
    event_risk: bool = False
    liquidity_score: float = 1.0


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
    risk_snapshot: dict[str, Any]

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

    def evaluate(self, *, snapshot: PortfolioSnapshot, state: PortfolioRiskState,
                 proposed: ProposedTradeRisk) -> RiskDecision:
        nav = snapshot.net_liquidating_value
        reasons: list[RiskReason] = []
        if snapshot.blocks_new_risk:
            reasons.append(RiskReason.PORTFOLIO_DATA_BLOCKED)
        if nav <= 0:
            reasons.append(RiskReason.INVALID_NAV)
        if proposed.planned_loss <= 0:
            reasons.append(RiskReason.INVALID_PLANNED_LOSS)
        if not 0 <= proposed.liquidity_score <= 1:
            reasons.append(RiskReason.LIQUIDITY_LIMIT)
        planned_loss_nav = proposed.planned_loss / nav if nav > 0 else float("inf")
        if nav > 0:
            self._apply_limits(reasons, nav, state, proposed)
        final = tuple(dict.fromkeys(reasons)) if reasons else (RiskReason.APPROVED,)
        return RiskDecision(
            RiskDecisionStatus.REJECTED if reasons else RiskDecisionStatus.APPROVED,
            final, proposed.decision_id, proposed.symbol, snapshot.snapshot_id,
            self.policy.version, nav, proposed.planned_loss, planned_loss_nav,
            {"portfolio": asdict(state), "proposed": asdict(proposed)},
        )

    def _apply_limits(self, reasons: list[RiskReason], nav: float,
                      state: PortfolioRiskState, proposed: ProposedTradeRisk) -> None:
        p = self.policy
        checks = (
            (proposed.planned_loss / nav > p.max_position_loss_nav, RiskReason.POSITION_RISK_LIMIT),
            ((state.daily_new_risk + proposed.planned_loss) / nav > p.max_daily_new_risk_nav, RiskReason.DAILY_NEW_RISK_LIMIT),
            (state.new_positions_today >= p.max_new_positions_per_day, RiskReason.DAILY_POSITION_LIMIT),
            (state.daily_loss / nav >= p.daily_loss_lockout_nav, RiskReason.DAILY_LOSS_LOCKOUT),
            (state.weekly_drawdown / nav >= p.weekly_drawdown_pause_nav, RiskReason.WEEKLY_DRAWDOWN_PAUSE),
            (state.rolling_drawdown / nav >= p.rolling_drawdown_review_nav, RiskReason.ROLLING_DRAWDOWN_REVIEW),
            ((state.risk_for_cluster(proposed.cluster_id) + proposed.planned_loss) / nav > p.max_cluster_risk_nav, RiskReason.CLUSTER_RISK_LIMIT),
            ((state.risk_for_sector(proposed.sector) + proposed.planned_loss) / nav > p.max_sector_risk_nav, RiskReason.SECTOR_RISK_LIMIT),
            ((state.total_risk + proposed.planned_loss) / nav > p.max_total_risk_nav, RiskReason.TOTAL_RISK_LIMIT),
            (abs(state.beta_exposure + proposed.beta_exposure) / nav > p.max_abs_beta_exposure_nav, RiskReason.BETA_EXPOSURE_LIMIT),
            (abs(state.delta_exposure + proposed.delta_exposure) / nav > p.max_abs_delta_exposure_nav, RiskReason.DELTA_EXPOSURE_LIMIT),
            (p.block_event_risk and proposed.event_risk, RiskReason.EVENT_RISK_BLOCKED),
            (proposed.liquidity_score < p.min_liquidity_score, RiskReason.LIQUIDITY_LIMIT),
        )
        reasons.extend(reason for failed, reason in checks if failed)
