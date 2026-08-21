from datetime import UTC, datetime

import pytest

from daily_alpha.agentic_intraday import IntradayPortfolioState, IntradayState
from daily_alpha.agentic_intraday_controller import (
    IntradayAgentOperation,
    IntradayAgentSnapshot,
    acknowledge_exit,
    acknowledge_paper_open,
    complete_forensics,
    evaluate_agent_clock,
    evaluate_agent_observation,
)
from daily_alpha.agentic_intraday_momentum import IntradayMomentumObservation

OPENING_TIME = datetime(2026, 8, 21, 13, 45, tzinfo=UTC)
FIVE_MINUTE_TIME = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
MANAGEMENT_TIME = datetime(2026, 8, 21, 19, 35, tzinfo=UTC)
FLATTEN_TIME = datetime(2026, 8, 21, 19, 50, tzinfo=UTC)


def opening_observation(**overrides):
    payload = {
        "observation_id": "MU-AGENT-OPEN-1",
        "timeframe": "2M",
        "observed_at": OPENING_TIME,
        "close": 130.0,
        "high": 130.1,
        "low": 129.0,
        "vwap": 129.2,
        "relative_volume": 1.8,
        "relative_strength_pct": 0.30,
        "daily_context_approved": True,
        "context_15m_approved": True,
        "sector_context_approved": True,
        "average_daily_share_volume": 25_000_000.0,
        "opening_range_established": True,
        "opening_range_high": 129.8,
    }
    payload.update(overrides)
    return IntradayMomentumObservation(**payload)


def portfolio(**overrides):
    payload = {
        "nav": 1_000_000.0,
        "trades_opened_today": 0,
        "daily_new_risk_dollars": 0.0,
        "open_symbols": (),
    }
    payload.update(overrides)
    return IntradayPortfolioState(**payload)


def test_agent_moves_valid_opening_setup_to_paper_entry_ready():
    result = evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(),
        portfolio(),
    )

    assert result.operation == IntradayAgentOperation.PAPER_ENTRY_READY
    assert result.reason == "SIGNAL_AND_RISK_APPROVED"
    assert result.snapshot.state == IntradayState.RISK_APPROVED
    assert result.snapshot.manager_timeframe == "2M"
    assert result.snapshot.entry_price == 130.0
    assert result.snapshot.stock_stop_price == 129.2
    assert result.share_quantity > 0
    assert result.snapshot.trading_authorized is False
    assert result.snapshot.live_trading_enabled is False


def test_final_two_minute_bar_closing_at_ten_et_remains_opening_entry():
    result = evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(
            observation_id="MU-AGENT-OPEN-1000",
            observed_at=FIVE_MINUTE_TIME,
        ),
        portfolio(),
    )

    assert result.operation == IntradayAgentOperation.PAPER_ENTRY_READY
    assert result.snapshot.state == IntradayState.RISK_APPROVED
    assert result.snapshot.manager_timeframe == "2M"
    assert result.entry_event is not None
    assert result.entry_event.timeframe == "2M"


def test_duplicate_observation_is_idempotent():
    first = evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(),
        portfolio(),
    )
    duplicate = evaluate_agent_observation(
        first.snapshot,
        opening_observation(),
        portfolio(),
    )

    assert duplicate.operation == IntradayAgentOperation.NO_ACTION
    assert duplicate.reason == "DUPLICATE_OBSERVATION"
    assert duplicate.idempotent is True
    assert duplicate.snapshot == first.snapshot


def test_risk_rejection_enters_rejected_state_without_entry_instruction():
    result = evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(),
        portfolio(trades_opened_today=2),
    )

    assert result.operation == IntradayAgentOperation.NO_ACTION
    assert result.reason == "INTRADAY_RISK_REJECTED"
    assert result.snapshot.state == IntradayState.REJECTED
    assert "INTRADAY_DAILY_TRADE_LIMIT" in result.risk_reasons
    assert result.share_quantity == 0


def test_paper_open_ack_requires_matching_approved_event():
    decision = evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(),
        portfolio(),
    )

    with pytest.raises(ValueError, match="INTRADAY_PAPER_OPEN_ACK_EVENT_MISMATCH"):
        acknowledge_paper_open(decision.snapshot, event_id="WRONG")

    opened = acknowledge_paper_open(
        decision.snapshot,
        event_id="MU-AGENT-OPEN-1",
    )
    assert opened.state == IntradayState.PAPER_OPEN
    assert opened.manager_timeframe == "2M"


def test_opening_position_transfers_to_five_minute_manager_at_ten_et():
    decision = evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(),
        portfolio(),
    )
    opened = acknowledge_paper_open(decision.snapshot, event_id="MU-AGENT-OPEN-1")

    handoff = evaluate_agent_clock(opened, now=FIVE_MINUTE_TIME)

    assert handoff.operation == IntradayAgentOperation.TRANSFER_TO_5M
    assert handoff.snapshot.state == IntradayState.MANAGED_5M
    assert handoff.snapshot.manager_timeframe == "5M"
    assert handoff.snapshot.entry_price == opened.entry_price
    assert handoff.snapshot.stock_stop_price == opened.stock_stop_price
    assert handoff.snapshot.share_quantity == opened.share_quantity


def test_late_session_disables_entries_then_requires_flatten():
    open_snapshot = IntradayAgentSnapshot(
        state=IntradayState.MANAGED_5M,
        manager_timeframe="5M",
        entry_price=130.0,
        stock_stop_price=129.2,
        share_quantity=100,
    )

    management = evaluate_agent_clock(open_snapshot, now=MANAGEMENT_TIME)
    flatten = evaluate_agent_clock(open_snapshot, now=FLATTEN_TIME)

    assert management.operation == IntradayAgentOperation.MANAGEMENT_ONLY
    assert management.reason == "NEW_ENTRIES_DISABLED_MANAGEMENT_ONLY"
    assert flatten.operation == IntradayAgentOperation.FLATTEN_REQUIRED
    assert flatten.reason == "MANDATORY_INTRADAY_FLATTEN"


def test_exit_then_forensics_completes_agent_lifecycle():
    open_snapshot = IntradayAgentSnapshot(
        state=IntradayState.MANAGED_5M,
        manager_timeframe="5M",
        entry_price=130.0,
        stock_stop_price=129.2,
        share_quantity=100,
    )

    exited = acknowledge_exit(open_snapshot)
    complete = complete_forensics(exited)

    assert exited.state == IntradayState.EXITED
    assert exited.share_quantity == 0
    assert complete.state == IntradayState.FORENSICS_COMPLETE


def test_open_position_does_not_accept_new_setup_observations():
    open_snapshot = IntradayAgentSnapshot(
        state=IntradayState.PAPER_OPEN,
        manager_timeframe="2M",
        entry_price=130.0,
        stock_stop_price=129.2,
        share_quantity=100,
    )

    result = evaluate_agent_observation(
        open_snapshot,
        opening_observation(observation_id="MU-SECOND-SETUP"),
        portfolio(open_symbols=("MU",)),
    )

    assert result.operation == IntradayAgentOperation.NO_ACTION
    assert result.reason == "OBSERVATION_NOT_ACCEPTED_IN_PAPER_OPEN"


def test_agent_snapshot_cannot_point_to_swing_or_live_account():
    with pytest.raises(ValueError, match="INTRADAY_AGENT_ACCOUNT_INVALID"):
        evaluate_agent_clock(
            IntradayAgentSnapshot(account_id="PAPER_SHADOW_V24"),
            now=FIVE_MINUTE_TIME,
        )

    with pytest.raises(ValueError, match="INTRADAY_AGENT_LIVE_TRADING_FORBIDDEN"):
        evaluate_agent_clock(
            IntradayAgentSnapshot(live_trading_enabled=True),
            now=FIVE_MINUTE_TIME,
        )
