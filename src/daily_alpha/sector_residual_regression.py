"""Point-in-time regression diagnostics for sector-residual momentum research."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime

_RESIDUAL_ZERO_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class ResidualCalibrationPoint:
    """One periodic return observation used only for factor calibration."""

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
        if any(
            not math.isfinite(value)
            for value in (self.stock_return, self.market_return, self.sector_return)
        ):
            raise ValueError("calibration returns must be finite")


@dataclass(frozen=True, slots=True)
class ResidualRegressionObservation:
    """Frozen candidate, horizon factor returns and trailing calibration window."""

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
        horizons = (
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
        if any(not math.isfinite(value) for value in horizons):
            raise ValueError("horizon returns must be finite")
        if len(self.calibration_points) < 3:
            raise ValueError("at least three calibration points are required")
        ordered = tuple(sorted(self.calibration_points, key=lambda point: point.period_end))
        if ordered != self.calibration_points:
            raise ValueError("calibration points must be sorted by period_end")
        period_ends = [point.period_end for point in self.calibration_points]
        if len(set(period_ends)) != len(period_ends):
            raise ValueError("duplicate calibration period_end")


@dataclass(frozen=True, slots=True)
class ResidualRegressionState:
    """Research-only market and sector+market residual diagnostics."""

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
    stock_mean = statistics.fmean(stock)
    factor_mean = statistics.fmean(factor)
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
    stock_mean = statistics.fmean(stock)
    market_mean = statistics.fmean(market)
    sector_mean = statistics.fmean(sector)
    y = [value - stock_mean for value in stock]
    m = [value - market_mean for value in market]
    s = [value - sector_mean for value in sector]
    mm = sum(value * value for value in m)
    ss = sum(value * value for value in s)
    ms = sum(a * b for a, b in zip(m, s, strict=True))
    my = sum(a * b for a, b in zip(m, y, strict=True))
    sy = sum(a * b for a, b in zip(s, y, strict=True))
    determinant = mm * ss - ms * ms
    if determinant <= 1e-18:
        raise ValueError("market/sector calibration matrix is singular")
    return (my * ss - sy * ms) / determinant, (sy * mm - my * ms) / determinant


def _positive_fraction(values: list[float]) -> float:
    return sum(value > _RESIDUAL_ZERO_TOLERANCE for value in values) / len(values)


class ResidualRegressionAnalyzer:
    """Compute point-in-time factor residuals for an already-qualified candidate."""

    def evaluate(
        self,
        observation: ResidualRegressionObservation,
        *,
        decision_at: datetime,
    ) -> ResidualRegressionState:
        decision = _utc(decision_at, name="decision_at")
        if _utc(observation.as_of, name="as_of") > decision:
            raise ValueError("future residual-regression as_of")
        if _utc(observation.known_at, name="known_at") > decision:
            raise ValueError("future residual-regression known_at")
        for point in observation.calibration_points:
            if _utc(point.period_end, name="period_end") > decision:
                raise ValueError("future calibration period")
            if _utc(point.known_at, name="known_at") > decision:
                raise ValueError("future calibration knowledge")

        stock = [point.stock_return for point in observation.calibration_points]
        market = [point.market_return for point in observation.calibration_points]
        sector = [point.sector_return for point in observation.calibration_points]
        market_beta = _sample_beta(stock, market)
        joint_market_beta, joint_sector_beta = _joint_betas(stock, market, sector)

        stock_mean = statistics.fmean(stock)
        market_mean = statistics.fmean(market)
        sector_mean = statistics.fmean(sector)
        market_alpha = stock_mean - market_beta * market_mean
        joint_alpha = stock_mean - joint_market_beta * market_mean - joint_sector_beta * sector_mean
        market_weekly = [
            stock_value - (market_alpha + market_beta * market_value)
            for stock_value, market_value in zip(stock, market, strict=True)
        ]
        joint_weekly = [
            stock_value
            - (joint_alpha + joint_market_beta * market_value + joint_sector_beta * sector_value)
            for stock_value, market_value, sector_value in zip(stock, market, sector, strict=True)
        ]

        market_residuals = tuple(
            stock_return - market_beta * market_return
            for stock_return, market_return in (
                (observation.stock_return_20d, observation.market_return_20d),
                (observation.stock_return_63d, observation.market_return_63d),
                (observation.stock_return_126d, observation.market_return_126d),
            )
        )
        joint_residuals = tuple(
            stock_return - joint_market_beta * market_return - joint_sector_beta * sector_return
            for stock_return, market_return, sector_return in (
                (
                    observation.stock_return_20d,
                    observation.market_return_20d,
                    observation.sector_return_20d,
                ),
                (
                    observation.stock_return_63d,
                    observation.market_return_63d,
                    observation.sector_return_63d,
                ),
                (
                    observation.stock_return_126d,
                    observation.market_return_126d,
                    observation.sector_return_126d,
                ),
            )
        )

        return ResidualRegressionState(
            security_id=observation.security_id,
            ticker=observation.ticker,
            sector=observation.sector,
            sector_proxy=observation.sector_proxy,
            decision_at=decision,
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
            market_residual_positive_fraction=_positive_fraction(market_weekly),
            joint_residual_positive_fraction=_positive_fraction(joint_weekly),
        )
