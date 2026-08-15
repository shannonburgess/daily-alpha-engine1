from daily_alpha.fallback import InstrumentFallbackEngine
from daily_alpha.models import (
    DecisionStatus,
    InstrumentSelected,
    OptionCandidate,
    StockCandidate,
)


def option(**overrides):
    values = {
        "symbol": "TEST",
        "expiration": "2026-10-16",
        "strike": 100.0,
        "option_type": "CALL",
        "dte": 60,
        "bid": 4.80,
        "ask": 5.20,
        "open_interest": 500,
        "volume": 80,
    }
    values.update(overrides)
    return OptionCandidate(**values)


def stock(**overrides):
    values = {
        "symbol": "TEST",
        "price": 100.0,
        "average_daily_dollar_volume": 100_000_000.0,
        "eligible": True,
    }
    values.update(overrides)
    return StockCandidate(**values)


def test_qualified_option_has_priority():
    decision = InstrumentFallbackEngine().select(
        symbol="TEST",
        signal_active=True,
        risk_gate_passed=True,
        option_data_fresh=True,
        option_data_available=True,
        options=[option()],
        stock=stock(),
    )
    assert decision.instrument_selected == InstrumentSelected.OPTION
    assert decision.status == DecisionStatus.SELECTED


def test_stock_fallback_when_contracts_fail_quality():
    decision = InstrumentFallbackEngine().select(
        symbol="TEST",
        signal_active=True,
        risk_gate_passed=True,
        option_data_fresh=True,
        option_data_available=True,
        options=[option(open_interest=1)],
        stock=stock(),
    )
    assert decision.instrument_selected == InstrumentSelected.STOCK
    assert "NO_OPTION_PASSED" in decision.fallback_reason


def test_stale_orats_data_never_substitutes_stock():
    decision = InstrumentFallbackEngine().select(
        symbol="TEST",
        signal_active=True,
        risk_gate_passed=True,
        option_data_fresh=False,
        option_data_available=True,
        options=[],
        stock=stock(),
    )
    assert decision.status == DecisionStatus.DATA_ERROR
    assert decision.instrument_selected == InstrumentSelected.NONE


def test_risk_gate_blocks_all_instruments():
    decision = InstrumentFallbackEngine().select(
        symbol="TEST",
        signal_active=True,
        risk_gate_passed=False,
        option_data_fresh=True,
        option_data_available=True,
        options=[option()],
        stock=stock(),
    )
    assert decision.status == DecisionStatus.NO_TRADE
    assert decision.instrument_selected == InstrumentSelected.NONE
