from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.paper_model_performance import (
    observation_from_closed_paper_trade,
    summarize_model_performance,
)

BASE = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def test_zero_price_closed_stock_loss_remains_in_performance_evidence() -> None:
    record = observation_from_closed_paper_trade(
        "PAPER_SHADOW_V24",
        {
            "trade_id": "catastrophic-zero-exit",
            "symbol": "DINO",
            "instrument": "STOCK",
            "quantity": 10,
            "entry_price": 100.0,
            "entry_time": BASE.isoformat(),
            "state": "CLOSED",
            "exit_price": 0.0,
            "exit_time": (BASE + timedelta(hours=1)).isoformat(),
            "realized_pnl": -1000.0,
            "sector": "Energy",
            "initial_risk_basis": 100.0,
        },
        setup_type="entry_long",
        lifecycle_stage="leader",
        industry="oil_gas",
        exit_reason="catastrophic_loss",
    )

    summary = summarize_model_performance("PAPER_SHADOW_V24", [record])

    assert record.exit_price == 0.0
    assert record.model_pnl == pytest.approx(-1000.0)
    assert record.r_multiple == pytest.approx(-10.0)
    assert summary.n == 1
    assert summary.losses == 1
    assert summary.cumulative_model_pnl == pytest.approx(-1000.0)
    assert summary.cumulative_r == pytest.approx(-10.0)
    assert summary.expectancy_r == pytest.approx(-10.0)
    assert summary.max_drawdown_pnl == pytest.approx(1000.0)
    assert summary.max_drawdown_r == pytest.approx(10.0)


def test_negative_exit_price_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="EXIT_PRICE_MUST_BE_NONNEGATIVE"):
        observation_from_closed_paper_trade(
            "PAPER_SHADOW_V24",
            {
                "trade_id": "invalid-negative-exit",
                "symbol": "DINO",
                "instrument": "STOCK",
                "quantity": 10,
                "entry_price": 100.0,
                "entry_time": BASE.isoformat(),
                "state": "CLOSED",
                "exit_price": -0.01,
                "exit_time": (BASE + timedelta(hours=1)).isoformat(),
                "realized_pnl": -1000.1,
                "sector": "Energy",
                "initial_risk_basis": 100.0,
            },
        )
