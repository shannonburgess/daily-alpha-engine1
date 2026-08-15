import pytest

from daily_alpha.lifecycle import (
    ExitReason,
    ManagementAction,
    MarketObservation,
    TradeLifecycleEngine,
    TradePlan,
    TradeState,
)
from daily_alpha.models import InstrumentSelected


def plan(**overrides):
    values = {
        "trade_id": "trade-controls",
        "symbol": "AAPL",
        "instrument": InstrumentSelected.OPTION,
        "entry_price": 10,
        "stop_price": 8,
        "target_price": 14,
        "max_holding_days": 20,
        "option_expiration": "2026-10-16",
        "scale_out_price": 12,
        "trailing_stop_percent": 0.10,
    }
    values.update(overrides)
    return TradePlan(**values)


def open_trade(**overrides):
    engine = TradeLifecycleEngine()
    record = engine.create(plan(**overrides))
    record = engine.transition(
        record,
        new_state=TradeState.APPROVED,
        reason="RISK_APPROVED",
        actor="risk-engine",
        idempotency_key="approve-1",
    )
    record = engine.transition(
        record,
        new_state=TradeState.ENTERED,
        reason="PAPER_FILL",
        actor="paper-broker",
        idempotency_key="fill-1",
    )
    return engine, record


def test_transition_is_attributable_and_idempotent():
    engine, record = open_trade()
    repeated = engine.transition(
        record,
        new_state=TradeState.MANAGED,
        reason="DAILY_REVIEW",
        actor="position-manager",
        idempotency_key="review-1",
    )
    duplicate = engine.transition(
        repeated,
        new_state=TradeState.MANAGED,
        reason="DAILY_REVIEW",
        actor="position-manager",
        idempotency_key="review-1",
    )
    assert duplicate == repeated
    assert repeated.events[-1].actor == "position-manager"


@pytest.mark.parametrize(
    ("observation", "action", "reason"),
    [
        (MarketObservation(price=7, days_held=1, gap_below_stop=True), ManagementAction.EXIT, ExitReason.GAP_STOP),
        (MarketObservation(price=10, days_held=1, halted=True), ManagementAction.ALERT, None),
        (MarketObservation(price=10, days_held=1, stale_quote=True), ManagementAction.DATA_ERROR, None),
        (MarketObservation(price=10, days_held=1, exercise_risk=True), ManagementAction.EXIT, ExitReason.EXERCISE_RISK),
        (MarketObservation(price=10, days_held=1, attempted_add_below_entry=True), ManagementAction.ALERT, None),
    ],
)
def test_gap_halt_stale_exercise_and_averaging_controls(observation, action, reason):
    engine, record = open_trade()
    decision = engine.evaluate_management(record, observation)
    assert decision.action == action
    assert decision.exit_reason == reason


def test_scale_out_and_trailing_stop_rules():
    engine, record = open_trade()
    scale = engine.evaluate_management(record, MarketObservation(price=12, days_held=5))
    trail = engine.evaluate_management(
        record, MarketObservation(price=10.7, days_held=6, high_water_mark=12)
    )
    assert scale.action == ManagementAction.SCALE_OUT
    assert scale.size_fraction == 0.5
    assert trail.exit_reason == ExitReason.TRAILING_STOP


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ({"earnings_within_days": 2}, "EARNINGS_REVIEW"),
        ({"ex_dividend_within_days": 2}, "DIVIDEND_REVIEW"),
        ({"corporate_action": True}, "CORPORATE_ACTION_REVIEW"),
    ],
)
def test_event_controls_require_review(field, reason):
    engine, record = open_trade()
    decision = engine.evaluate_management(
        record, MarketObservation(price=10, days_held=1, **field)
    )
    assert decision.action == ManagementAction.ALERT
    assert decision.reason == reason


def test_cancelled_signal_is_terminal_before_entry():
    engine = TradeLifecycleEngine()
    record = engine.create(plan())
    record = engine.transition(
        record,
        new_state=TradeState.CANCELLED,
        reason="SIGNAL_CANCELLED",
        actor="signal-engine",
        idempotency_key="cancel-1",
    )
    assert record.state == TradeState.CANCELLED
    with pytest.raises(ValueError, match="invalid transition"):
        engine.transition(
            record,
            new_state=TradeState.ENTERED,
            reason="LATE_FILL",
            actor="paper-broker",
        )


def test_averaging_down_cannot_be_enabled_silently():
    with pytest.raises(ValueError, match="separately approved strategy"):
        plan(allow_averaging_down=True)
