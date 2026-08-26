from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.sector_residual_regression import (
    ResidualCalibrationPoint,
    ResidualRegressionAnalyzer,
    ResidualRegressionObservation,
)


def _calibration_points() -> tuple[ResidualCalibrationPoint, ...]:
    start = datetime(2026, 1, 2, tzinfo=UTC)
    market = (-0.02, -0.01, 0.00, 0.01, 0.02, 0.03)
    sector = (0.01, -0.02, 0.03, -0.01, 0.02, -0.03)
    points: list[ResidualCalibrationPoint] = []
    for index, (market_return, sector_return) in enumerate(
        zip(market, sector, strict=True)
    ):
        period_end = start + timedelta(days=7 * index)
        stock_return = 0.001 + 0.8 * market_return + 1.2 * sector_return
        points.append(
            ResidualCalibrationPoint(
                period_end=period_end,
                known_at=period_end + timedelta(hours=1),
                stock_return=stock_return,
                market_return=market_return,
                sector_return=sector_return,
            )
        )
    return tuple(points)


def _observation() -> ResidualRegressionObservation:
    as_of = datetime(2026, 2, 13, tzinfo=UTC)
    return ResidualRegressionObservation(
        security_id="sec-1",
        ticker="TEST",
        sector="Technology",
        sector_proxy="XLK",
        as_of=as_of,
        known_at=as_of + timedelta(hours=1),
        stock_return_20d=0.05,
        stock_return_63d=0.12,
        stock_return_126d=0.20,
        market_return_20d=0.02,
        market_return_63d=0.05,
        market_return_126d=0.08,
        sector_return_20d=0.01,
        sector_return_63d=0.03,
        sector_return_126d=0.04,
        calibration_points=_calibration_points(),
    )


def test_joint_regression_recovers_factor_betas_and_horizon_residuals() -> None:
    observation = _observation()
    decision_at = observation.known_at + timedelta(minutes=1)

    state = ResidualRegressionAnalyzer().evaluate(
        observation,
        decision_at=decision_at,
    )

    assert state.calibration_count == 6
    assert state.joint_market_beta == pytest.approx(0.8)
    assert state.joint_sector_beta == pytest.approx(1.2)
    assert state.joint_residual_20d == pytest.approx(0.022)
    assert state.joint_residual_63d == pytest.approx(0.044)
    assert state.joint_residual_126d == pytest.approx(0.088)
    assert state.joint_residual_positive_fraction == pytest.approx(0.0)
    assert 0.0 <= state.market_residual_positive_fraction <= 1.0
    assert state.research_only is True
    assert state.paper_entry_authorized is False
    assert state.portfolio_mutation_authorized is False
    assert state.trading_authorized is False
    assert state.live_trading_enabled is False


def test_future_calibration_knowledge_fails_closed() -> None:
    observation = _observation()
    future_point = replace(
        observation.calibration_points[-1],
        known_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    observation = replace(
        observation,
        calibration_points=observation.calibration_points[:-1] + (future_point,),
    )

    with pytest.raises(ValueError, match="future calibration knowledge"):
        ResidualRegressionAnalyzer().evaluate(
            observation,
            decision_at=datetime(2026, 2, 20, tzinfo=UTC),
        )


def test_singular_market_sector_calibration_fails_closed() -> None:
    observation = _observation()
    singular_points = tuple(
        replace(point, sector_return=2.0 * point.market_return)
        for point in observation.calibration_points
    )
    observation = replace(observation, calibration_points=singular_points)

    with pytest.raises(ValueError, match="calibration matrix is singular"):
        ResidualRegressionAnalyzer().evaluate(
            observation,
            decision_at=datetime(2026, 2, 20, tzinfo=UTC),
        )


def test_duplicate_calibration_period_fails_closed() -> None:
    points = _calibration_points()
    duplicate = replace(points[-1], period_end=points[-2].period_end)

    with pytest.raises(ValueError, match="calibration points must be sorted|duplicate"):
        replace(_observation(), calibration_points=points[:-1] + (duplicate,))


def test_leveraged_sector_proxy_is_rejected() -> None:
    with pytest.raises(ValueError, match="1x sector proxy"):
        replace(_observation(), sector_proxy_leverage=2.0)
