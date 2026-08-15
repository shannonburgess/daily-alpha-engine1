import pytest
from daily_alpha.models import InstrumentSelected

from daily_alpha.lifecycle import (
    ExitReason,
    ManagementAction,
    MarketObservation,
    TradeLifecycleEngine,
    TradePlan,
    TradeState,
)


def plan(instrument=InstrumentSelected.OPTION) -> TradePlan:
    return TradePlan(
        trade_id="trade-1",
        symbol="AAPL",
        instrument=instrument,
        entry_price=10,
        stop_price=8,
        target_price=14,
        max_holding_days=20,
        option_expiration="2026-10-16" if instrument == InstrumentSelected.OPTION else None,
    )


def open_trade(instrument=InstrumentSelected.OPTION):
    engine = TradeLifecycleEngine()
    record = engine.create(plan(instrument), occurred_at="2026-08-15T12:00:00+00:00")
    record = engine.transition(record, new_state=TradeState.APPROVED, reason="RISK_APPROVED")
    record = engine.transition(record, new_state=TradeState.ENTERED, reason="PAPER_FILL")
    return engine, record


def test_valid_lifecycle_is_append_only_and_sequenced():
    engine, record = open_trade()
    record = engine.transition(record, new_state=TradeState.MANAGED, reason="DAILY_REVIEW")
    record = engine.transition(
        record,
        new_state=TradeState.EXITED,
        reason=ExitReason.PINE_EXIT.value,
        metadata={"exit_price": 12.5},
    )
    record = engine.transition(record, new_state=TradeState.REVIEWED, reason="POST_TRADE_REVIEW")
    assert [event.sequence for event in record.events] == [1, 2, 3, 4, 5, 6]
    assert record.state == TradeState.REVIEWED
    assert record.events[-2].metadata == {"exit_price": 12.5}


def test_invalid_transition_is_rejected():
    engine = TradeLifecycleEngine()
    record = engine.create(plan())
    with pytest.raises(ValueError, match="invalid transition"):
        engine.transition(record, new_state=TradeState.ENTERED, reason="SKIP_RISK_GATE")


@pytest.mark.parametrize(
    ("observation", "exit_reason"),
    [
        (MarketObservation(price=8, days_held=1), ExitReason.STOP),
        (MarketObservation(price=14, days_held=1), ExitReason.TARGET),
        (MarketObservation(price=10, days_held=1, pine_exit=True), ExitReason.PINE_EXIT),
        (MarketObservation(price=10, days_held=1, turtle_exit=True), ExitReason.TURTLE_EXIT),
        (MarketObservation(price=10, days_held=20), ExitReason.TIME_STOP),
    ],
)
def test_shared_stock_and_option_exit_logic(observation, exit_reason):
    engine, record = open_trade(InstrumentSelected.STOCK)
    decision = engine.evaluate_management(record, observation)
    assert decision.action == ManagementAction.EXIT
    assert decision.exit_reason == exit_reason


def test_option_expiration_and_assignment_controls():
    engine, record = open_trade()
    expiration = engine.evaluate_management(
        record, MarketObservation(price=10, days_held=1, option_dte=7)
    )
    assignment = engine.evaluate_management(
        record, MarketObservation(price=10, days_held=1, assignment_risk=True)
    )
    assert expiration.exit_reason == ExitReason.EXPIRATION_RISK
    assert assignment.exit_reason == ExitReason.ASSIGNMENT_RISK


def test_data_error_does_not_fabricate_an_exit_price():
    engine, record = open_trade()
    decision = engine.evaluate_management(
        record, MarketObservation(price=10, days_held=1, data_error=True)
    )
    assert decision.action == ManagementAction.DATA_ERROR
    assert decision.exit_reason is None


def test_corporate_action_requires_review_without_automatic_exit():
    engine, record = open_trade()
    decision = engine.evaluate_management(
        record, MarketObservation(price=10, days_held=1, corporate_action=True)
    )
    assert decision.action == ManagementAction.ALERT


def test_option_plan_requires_expiration():
    with pytest.raises(ValueError, match="requires expiration"):
        TradePlan("bad", "SPY", InstrumentSelected.OPTION, 10, 8, 14, 20)
