import pytest

from daily_alpha.models import InstrumentSelected
from daily_alpha.performance import (
    ClosedTrade,
    ScalingDecision,
    ScalingPolicy,
    assess_scaling,
    summarize,
    summarize_by_instrument,
)


def trade(trade_id, pnl, instrument=InstrumentSelected.OPTION, risk=100, capital=1000):
    return ClosedTrade(trade_id, instrument, pnl, risk, capital)


def test_summary_calculates_edge_and_drawdown_metrics():
    result = summarize([trade("1", 200), trade("2", -100), trade("3", 100)])
    assert result.trades == 3
    assert result.win_rate == pytest.approx(2 / 3)
    assert result.expectancy_r == pytest.approx(2 / 3)
    assert result.profit_factor == pytest.approx(3)
    assert result.max_drawdown == pytest.approx(1)


def test_results_are_separated_by_instrument():
    result = summarize_by_instrument(
        [trade("option", 100), trade("stock", -50, InstrumentSelected.STOCK)]
    )
    assert result[InstrumentSelected.OPTION].net_pnl == 100
    assert result[InstrumentSelected.STOCK].net_pnl == -50


def test_scaling_is_blocked_without_sufficient_evidence():
    result = assess_scaling(summarize([trade("1", 100)]))
    assert result.decision == ScalingDecision.HOLD
    assert result.size_multiplier == 1
    assert "INSUFFICIENT_SAMPLE" in result.reasons


def test_scaling_can_increase_only_after_all_thresholds_pass():
    records = [trade(str(i), 100 if i % 3 else -50) for i in range(30)]
    result = assess_scaling(summarize(records))
    assert result.decision == ScalingDecision.ELIGIBLE_TO_INCREASE
    assert result.size_multiplier == 1.25


def test_drawdown_breach_reduces_size():
    summary = summarize([trade(str(i), -100) for i in range(9)])
    result = assess_scaling(summary, ScalingPolicy(maximum_drawdown_r=8))
    assert result.decision == ScalingDecision.REDUCE
    assert result.size_multiplier == 0.75


def test_invalid_trade_inputs_are_rejected():
    with pytest.raises(ValueError, match="positive"):
        trade("bad", 10, risk=0)
