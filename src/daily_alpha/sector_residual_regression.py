"""Point-in-time regression diagnostics for sector-residual momentum research.

This module implements the regression feature families pre-registered in issue #156 without
changing any production/PAPER decision path. The caller supplies the trailing calibration
window explicitly; this code does not tune or optimize an alpha threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import fmean


@dataclass(frozen=True, slots=True)
class ResidualCalibrationPoint:
    """One point-in-time periodic return observation used only for factor calibration."""

    period_end: datetime
    known_at: datetime
    stock_return: float
    market_return: float
    sector_return: float

    def __post_init__(self) -> None:
        if self.period_end.tzinfo is None or self.known_at.tzinfo is None:
            raise ValueError("period_end and known_at must be timezone-aware")
        if self.known_at < self.period_end:
            raise ValueError("known_at cannot precede period_end")
        values = (self.stock_return, self.market_return, self.sector_return)
        if any(not isfinite(value) for value in values):
            raise ValueError("calibration returns must be finite")


@dataclass(frozen=True, slots=True)
class ResidualRegressionObservation:
    """Frozen candidate plus factor returns and a trailing calibration window."""

    security_id: str
    ticker: str
    sector: str
    sector_proxy: str
    as_of: datetime
    known_at: datetime
    stock_return_20d: float
    stock_return_63d: float
    stock_return_126d: float
    market_return_20d: float
    market_return_63d: float
    market_return_126d: float
    sector_return_20d: float
    sector_return_63d: float
    sector_return_126d: float
    calibration_points: tuple[ResidualCalibrationPoint, ...]
    sector_proxy_leverage: float = 1.0

    def __post_init__(self) -> None:
        for name in ("security_id", "ticker", "sector", "sector_proxy"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be blank")
        if self.as_of.tzinfo is None or self.known_at.tzinfo is None:
            raise ValueError("as_of and known_at must be timezone-aware")
        if self.known_at < self.as_of:
            raise ValueError("known_at cannot precede as_of")
        if self.sector_proxy_leverage != 1.0:
            raise ValueError("regression signal decomposition requires a 1x sector proxy")
        horizon_values = (
            self.stock_return_20d,
            self.stock_return_63d,
            self.stock_return_126d,
            self.market_return_20d,
            self.market_return_63d,
            self.market_return_126d,
            self.sector_return_20d,
            self.sector_return_63d,
            self.sector_return_126d,
        )
        if any(not isfinite(value) for value in horizon_values):
            raise ValueError("horizon returns must be finite")
        if len(self.calibration_points) < 3:
            raise ValueError("at least three calibration points are required")
        if tuple(sorted(self.calibration_points, key=lambda point: point.period_end)) != self.calibration_points:
            raise ValueError("calibration points must be sorted by period_end")
        seen: set[datetime] = set()
        for point in self.calibration_points:
            if point.period_end in seen:
                raise ValueError("duplicate calibration period_end")
            seen.add(point.period_end)


@dataclass(frozen=True, slots=True)
class ResidualRegressionState:
    """Research-only market and sector+market residual-momentum diagnostics."""

    security_id: str
    ticker: str
    sector: str
    sector_proxy: str
    decision_at: datetime
    calibration_count: int
    market_beta: float
    joint_market_beta: float
    joint_sector_beta: float
    market_residual_20d: float
    market_residual_63d: float
    market_residual_126d: float
    joint_residual_20d: float
    joint_residual_63d: float
    joint_residual_126d: float
    market_residual_positive_fraction: float
    joint_residual_positive_fraction: float
    research_only: bool = True
    paper_entry_authorized: bool = False
    portfolio_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def _utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _sample_beta(stock: list[float], factor: list[float]) -> float:
    stock_mean = fmean(stock)
    factor_mean = fmean(factor)
    denominator = sum((value - factor_mean) ** 2 for value in factor)
    if denominator <= 1e-18:
        raise ValueError("market calibration variance is singular")
    numerator = sum(
        (factor_value - factor_mean) * (stock_value - stock_mean)
        for stock_value, factor_value in zip(stock, factor, strict=True)
    )
    return numerator / denominator


def _joint_betas(
    stock: list[float], market: list[float], sector: list[float]
) -> tuple[float, float]:
    stock_mean = fmean(stock)
    market_mean = fmean(market)
    sector_mean = fmean(sector)
    centered_stock = [value - stock_mean for value in stock]
    centered_market = [value - market_mean for value in market]
    centered_sector = [value - sector_mean for value in sector]

    mm = sum(value * value for value in centered_market)
    ss = sum(value * value for value in centered_sector)
    ms = sum(
        market_value * sector_value
        for market_value, sector_value in zip(centered_market, centered_sector, strict=True)
    )
    my = sum(
        market_value * stock_value
        for market_value, stock_value in zip(centered_market, centered_stock, strict=True)
    )
    sy = sum(
        sector_value * stock_value
        for sector_value, stock_value in zip(centered_sector, centered_stock, strict=True)
    )
    determinant = mm * ss - ms * ms
    if determinant <= 1e-18:
        raise ValueError("market/sector calibration matrix is singular")
    market_beta = (my * ss - sy * ms) / determinant
    sector_beta = (sy * mm - my * ms) / determinant
    return market_beta, sector_beta


class ResidualRegressionAnalyzer:
    """Compute point-in-time factor residuals for an already-qualified candidate."""

    def evaluate(
        self,
        observation: ResidualRegressionObservation,
        *,
        decision_at: datetime,
    ) -> ResidualRegressionState:
        decision_at_utc = _utc(decision_at, name="decision_at")
        if _utc(observation.as_of, name="as_of") > decision_at_utc:
            raise ValueError("future residual-regression as_of")
        if _utc(observation.known_at, name="known_at") > decision_at_utc:
            raise ValueError("future residual-regression known_at")
        for point in observation.calibration_points:
            if _utc(point.period_end, name="period_end") > decision_at_utc:
                raise ValueError("future calibration period")
            if _utc(point.known_at, name="known_at") > decision_at_utc:
                raise ValueError("future calibration knowledge")

        stock = [point.stock_return for point in observation.calibration_points]
        market = [point.market_return for point in observation.calibration_points]
        sector = [point.sector_return for point in observation.calibration_points]

        market_beta = _sample_beta(stock, market)
        joint_market_beta, joint_sector_beta = _joint_betas(stock, market, sector)

        stock_mean = fmean(stock)
        market_mean = fmean(market)
        sector_mean = fmean(sector)
        market_alpha = stock_mean - market_beta * market_mean
        joint_alpha = stock_mean - joint_market_beta * market_mean - joint_sector_beta * sector_mean
        market_weekly_residuals = [
            stock_value - (market_alpha + market_beta * market_value)
            for stock_value, market_value in zip(stock, market, strict=True)
        ]
        joint_weekly_residuals = [
            stock_value
            - (joint_alpha + joint_market_beta * market_value + joint_sector_beta * sector_value)
            for stock_value, market_value, sector_value in zip(stock, market, sector, strict=True)
        ]

        market_residuals = (
            observation.stock_return_20d - market_beta * observation.market_return_20d,
            observation.stock_return_63d - market_beta * observation.market_return_63d,
            observation.stock_return_126d - market_beta * observation.market_return_126d,
        )
        joint_residuals = (
            observation.stock_return_20d
            - joint_market_beta * observation.market_return_20d
            - joint_sector_beta * observation.sector_return_20d,
            observation.stock_return_63d
            - joint_market_beta * observation.market_return_63d
            - joint_sector_beta * observation.sector_return_63d,
            observation.stock_return_126d
            - joint_market_beta * observation.market_return_126d
            - joint_sector_beta * observation.sector_return_126d,
        )

        return ResidualRegressionState(
            security_id=observation.security_id,
            ticker=observation.ticker,
            sector=observation.sector,
            sector_proxy=observation.sector_proxy,
            decision_at=decision_at_utc,
            calibration_count=len(observation.calibration_points),
            market_beta=market_beta,
            joint_market_beta=joint_market_beta,
            joint_sector_beta=joint_sector_beta,
            market_residual_20d=market_residuals[0],
            market_residual_63d=market_residuals[1],
            market_residual_126d=market_residuals[2],
            joint_residual_20d=joint_residuals[0],
            joint_residual_63d=joint_residuals[1],
            joint_residual_126d=joint_residuals[2],
            market_residual_positive_fraction=(
                sum(value > 0.0 for value in market_weekly_residuals)
                / len(market_weekly_residuals)
            ),
            joint_residual_positive_fraction=(
                sum(value > 0.0 for value in joint_weekly_residuals)
                / len(joint_weekly_residuals)
            ),
        )
