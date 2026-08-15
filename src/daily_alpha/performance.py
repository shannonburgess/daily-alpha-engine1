"""Auditable performance analytics and evidence-gated paper sizing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from math import sqrt
from statistics import fmean, stdev

from .models import InstrumentSelected


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    instrument: InstrumentSelected
    net_pnl: float
    initial_risk: float
    capital_deployed: float

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id is required")
        if self.instrument == InstrumentSelected.NONE:
            raise ValueError("closed trade requires OPTION or STOCK")
        if self.initial_risk <= 0 or self.capital_deployed <= 0:
            raise ValueError("risk and capital deployed must be positive")

    @property
    def r_multiple(self) -> float:
        return self.net_pnl / self.initial_risk

    @property
    def return_on_capital(self) -> float:
        return self.net_pnl / self.capital_deployed


@dataclass(frozen=True)
class PerformanceSummary:
    trades: int
    wins: int
    losses: int
    net_pnl: float
    win_rate: float
    average_r: float
    expectancy_r: float
    profit_factor: float | None
    max_drawdown: float
    return_volatility: float
    sharpe_like: float | None


class ScalingDecision(StrEnum):
    HOLD = "HOLD"
    ELIGIBLE_TO_INCREASE = "ELIGIBLE_TO_INCREASE"
    REDUCE = "REDUCE"


@dataclass(frozen=True)
class ScalingPolicy:
    minimum_trades: int = 30
    minimum_expectancy_r: float = 0.20
    minimum_profit_factor: float = 1.25
    maximum_drawdown_r: float = 8.0
    increase_factor: float = 1.25

    def __post_init__(self) -> None:
        if self.minimum_trades <= 0 or self.increase_factor <= 1:
            raise ValueError("scaling thresholds are invalid")
        if self.minimum_profit_factor <= 0 or self.maximum_drawdown_r <= 0:
            raise ValueError("scaling thresholds are invalid")


@dataclass(frozen=True)
class ScalingAssessment:
    decision: ScalingDecision
    size_multiplier: float
    reasons: tuple[str, ...]


def summarize(trades: Iterable[ClosedTrade]) -> PerformanceSummary:
    records = tuple(trades)
    pnl = [trade.net_pnl for trade in records]
    r_values = [trade.r_multiple for trade in records]
    returns = [trade.return_on_capital for trade in records]
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = -sum(value for value in pnl if value < 0)
    volatility = stdev(returns) if len(returns) > 1 else 0.0
    mean_return = fmean(returns) if returns else 0.0
    return PerformanceSummary(
        trades=len(records),
        wins=wins,
        losses=losses,
        net_pnl=sum(pnl),
        win_rate=wins / len(records) if records else 0.0,
        average_r=fmean(r_values) if r_values else 0.0,
        expectancy_r=fmean(r_values) if r_values else 0.0,
        profit_factor=(gross_profit / gross_loss if gross_loss else None),
        max_drawdown=_max_drawdown(r_values),
        return_volatility=volatility,
        sharpe_like=(mean_return / volatility * sqrt(len(returns)) if volatility else None),
    )


def summarize_by_instrument(
    trades: Iterable[ClosedTrade],
) -> dict[InstrumentSelected, PerformanceSummary]:
    records = tuple(trades)
    return {
        instrument: summarize(t for t in records if t.instrument == instrument)
        for instrument in (InstrumentSelected.OPTION, InstrumentSelected.STOCK)
    }


def assess_scaling(
    summary: PerformanceSummary,
    policy: ScalingPolicy | None = None,
) -> ScalingAssessment:
    policy = policy or ScalingPolicy()
    if summary.max_drawdown > policy.maximum_drawdown_r:
        return ScalingAssessment(ScalingDecision.REDUCE, 0.75, ("DRAWDOWN_LIMIT_BREACHED",))

    reasons: list[str] = []
    if summary.trades < policy.minimum_trades:
        reasons.append("INSUFFICIENT_SAMPLE")
    if summary.expectancy_r < policy.minimum_expectancy_r:
        reasons.append("EXPECTANCY_BELOW_THRESHOLD")
    if summary.profit_factor is None:
        reasons.append("PROFIT_FACTOR_NOT_ESTABLISHED")
    elif summary.profit_factor < policy.minimum_profit_factor:
        reasons.append("PROFIT_FACTOR_BELOW_THRESHOLD")
    if reasons:
        return ScalingAssessment(ScalingDecision.HOLD, 1.0, tuple(reasons))
    return ScalingAssessment(
        ScalingDecision.ELIGIBLE_TO_INCREASE,
        policy.increase_factor,
        ("EVIDENCE_THRESHOLDS_MET",),
    )


def _max_drawdown(r_values: list[float]) -> float:
    equity = peak = max_drawdown = 0.0
    for value in r_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown
