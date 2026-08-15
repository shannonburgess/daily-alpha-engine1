import pytest

from daily_alpha.models import OptionCandidate
from daily_alpha.orats_intelligence import (
    FlowClassification,
    OratsIntelligenceEngine,
    OratsMetrics,
)


def metrics(*, volume=1000, open_interest=1000, average_volume=250, sweeps=20, trades=100):
    return OratsMetrics(
        candidate=OptionCandidate(
            "AAPL", "2026-10-16", 250, "CALL", 60, 5, 5.2, open_interest, volume, 0.5
        ),
        implied_volatility=0.40,
        historical_volatility=0.30,
        iv_percentile=70,
        expected_move_pct=0.08,
        skew=-0.03,
        term_slope=0.02,
        average_contract_volume=average_volume,
        sweep_count=sweeps,
        trade_count=trades,
    )


def test_unusual_flow_is_confirmation_not_standalone_signal():
    result = OratsIntelligenceEngine().analyze(metrics())
    assert result.classification == FlowClassification.UNUSUAL_CONFIRMATION
    assert result.standalone_trade_signal is False
    assert "RELATIVE_VOLUME_ELEVATED" in result.reasons


def test_volatility_and_expected_move_are_exposed():
    result = OratsIntelligenceEngine().analyze(metrics())
    assert result.iv_rv_spread == pytest.approx(0.10)
    assert result.expected_move_pct == 0.08
    assert result.iv_percentile == 70


def test_capacity_is_limited_by_volume_and_open_interest():
    result = OratsIntelligenceEngine().analyze(metrics(volume=1000, open_interest=1000))
    assert result.capacity_contracts == 20


def test_missing_average_volume_is_insufficient_not_unusual():
    result = OratsIntelligenceEngine().analyze(metrics(average_volume=0))
    assert result.classification == FlowClassification.INSUFFICIENT_DATA
    assert result.relative_volume is None


def test_single_elevated_dimension_is_caution():
    result = OratsIntelligenceEngine().analyze(
        metrics(volume=300, open_interest=5000, average_volume=100, sweeps=0)
    )
    assert result.classification == FlowClassification.UNUSUAL_CAUTION


def test_invalid_percentages_are_rejected():
    with pytest.raises(ValueError, match="iv_percentile"):
        bad = metrics()
        OratsMetrics(
            bad.candidate,
            bad.implied_volatility,
            bad.historical_volatility,
            101,
            bad.expected_move_pct,
            bad.skew,
            bad.term_slope,
            bad.average_contract_volume,
        )
