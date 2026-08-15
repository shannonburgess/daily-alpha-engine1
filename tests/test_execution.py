import pytest

from daily_alpha.execution import ExecutionIntent, ExecutionResult, FillStatus
from daily_alpha.models import InstrumentSelected


def intent(instrument=InstrumentSelected.OPTION, quantity=10):
    return ExecutionIntent(
        execution_id="exec-1",
        trade_id="trade-1",
        symbol="AAPL",
        instrument=instrument,
        requested_quantity=quantity,
        signal_price=5.00,
        bid=4.90,
        ask=5.10,
        intended_limit=5.05,
        signal_time="2026-08-15T12:00:00+00:00",
    )


def test_option_fill_calculates_spread_slippage_latency_and_net_pnl():
    result = ExecutionResult(
        intent(),
        FillStatus.FILLED,
        10,
        5.08,
        10,
        "2026-08-15T12:00:30+00:00",
    )
    assert result.intent.quoted_spread == pytest.approx(0.20)
    assert result.slippage_per_unit == pytest.approx(0.03)
    assert result.slippage_cost == pytest.approx(30)
    assert result.latency_seconds == 30
    assert result.net_pnl(exit_price=6, exit_commission=10) == pytest.approx(900)


def test_stock_uses_one_share_multiplier():
    result = ExecutionResult(
        intent(InstrumentSelected.STOCK, 10),
        FillStatus.FILLED,
        10,
        5.08,
        1,
        "2026-08-15T12:00:10+00:00",
    )
    assert result.slippage_cost == pytest.approx(0.30)


def test_partial_fill_is_explicit_and_measured():
    result = ExecutionResult(
        intent(quantity=10),
        FillStatus.PARTIAL,
        4,
        5.05,
        4,
        "2026-08-15T12:00:15+00:00",
    )
    assert result.fill_rate == 0.4


def test_missed_fill_does_not_fabricate_price_or_pnl():
    result = ExecutionResult(intent(), FillStatus.MISSED, 0, None, 0, None)
    assert result.slippage_per_unit is None
    assert result.latency_seconds is None
    assert result.net_pnl(exit_price=6) is None


def test_fill_status_and_quantity_must_agree():
    with pytest.raises(ValueError, match="complete requested quantity"):
        ExecutionResult(
            intent(),
            FillStatus.FILLED,
            5,
            5.05,
            5,
            "2026-08-15T12:00:10+00:00",
        )


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutionIntent("x", "t", "SPY", InstrumentSelected.STOCK, 1, 1, 1, 1, 1, "2026-08-15")
