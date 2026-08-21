from dataclasses import replace
from datetime import UTC, datetime

import pytest

from daily_alpha.agentic_intraday import (
    AGENTIC_INTRADAY_ACCOUNT,
    IntradayPortfolioState,
    IntradayState,
)
from daily_alpha.agentic_intraday_controller import (
    IntradayAgentOperation,
    IntradayAgentSnapshot,
    evaluate_agent_clock,
    evaluate_agent_observation,
)
from daily_alpha.agentic_intraday_execution import (
    AgenticIntradayPaperExecutor,
    IntradayPaperExecutionError,
)
from daily_alpha.agentic_intraday_momentum import IntradayMomentumObservation
from daily_alpha.ledger import PaperLedger, TradeState
from daily_alpha.models import InstrumentSelected

OPENING_TIME = datetime(2026, 8, 21, 13, 45, tzinfo=UTC)
FIVE_MINUTE_TIME = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
MANAGEMENT_TIME = datetime(2026, 8, 21, 19, 35, tzinfo=UTC)
FLATTEN_TIME = datetime(2026, 8, 21, 19, 50, tzinfo=UTC)


class AccountPaperLedger(PaperLedger):
    def __init__(self, root, account_id=AGENTIC_INTRADAY_ACCOUNT):
        super().__init__(root)
        self.account_id = account_id


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


def portfolio():
    return IntradayPortfolioState(nav=1_000_000.0)


def entry_decision():
    return evaluate_agent_observation(
        IntradayAgentSnapshot(),
        opening_observation(),
        portfolio(),
    )


def test_entry_writes_isolated_stock_paper_trade_and_exact_model_fill(tmp_path):
    decision = entry_decision()
    executor = AgenticIntradayPaperExecutor(AccountPaperLedger(tmp_path))

    result = executor.execute_entry(decision)

    assert decision.operation == IntradayAgentOperation.PAPER_ENTRY_READY
    assert result.snapshot.state == IntradayState.PAPER_OPEN
    assert result.trade.instrument == InstrumentSelected.STOCK
    assert result.trade.symbol == "MU"
    assert result.trade.entry_price == 130.0
    assert result.trade.quantity == decision.share_quantity
    assert result.trade.initial_risk_basis == pytest.approx(
        (130.0 - 129.2) * decision.share_quantity
    )
    assert result.receipt.action == "ENTRY_LONG"
    assert result.receipt.account_id == AGENTIC_INTRADAY_ACCOUNT
    assert result.receipt.instrument == "STOCK"
    assert result.receipt.timeframe == "2M"
    assert result.receipt.fill_price == 130.0
    assert result.receipt.fill_quantity == decision.share_quantity
    assert result.receipt.stock_stop_price == 129.2
    assert result.receipt.model_validation_fill is True
    assert result.receipt.paper_only is True
    assert result.receipt.trading_authorized is False
    assert result.receipt.live_trading_enabled is False


def test_duplicate_entry_instruction_is_idempotent_and_does_not_double_open(tmp_path):
    decision = entry_decision()
    ledger = AccountPaperLedger(tmp_path)
    executor = AgenticIntradayPaperExecutor(ledger)

    first = executor.execute_entry(decision)
    duplicate = executor.execute_entry(decision)

    assert first.idempotent is False
    assert duplicate.idempotent is True
    assert duplicate.trade.trade_id == first.trade.trade_id
    assert len(ledger.find_open("MU", InstrumentSelected.STOCK)) == 1
    assert duplicate.receipt.reason == "IDEMPOTENT_ENTRY_REPLAY"


def test_executor_refuses_swing_account_and_non_stock_entry(tmp_path):
    with pytest.raises(IntradayPaperExecutionError, match="INTRADAY_LEDGER_ACCOUNT_INVALID"):
        AgenticIntradayPaperExecutor(AccountPaperLedger(tmp_path, account_id="PAPER_SHADOW_V24"))

    decision = entry_decision()
    assert decision.entry_event is not None
    option_event = replace(decision.entry_event, instrument="OPTION")
    forged = replace(decision, entry_event=option_event)
    executor = AgenticIntradayPaperExecutor(AccountPaperLedger(tmp_path / "stock"))

    with pytest.raises(ValueError, match="INTRADAY_SHARES_ONLY"):
        executor.execute_entry(forged)


def test_mandatory_flatten_closes_position_and_preserves_r_receipt(tmp_path):
    ledger = AccountPaperLedger(tmp_path)
    executor = AgenticIntradayPaperExecutor(ledger)
    opened = executor.execute_entry(entry_decision())

    handoff = evaluate_agent_clock(opened.snapshot, now=FIVE_MINUTE_TIME)
    assert handoff.operation == IntradayAgentOperation.TRANSFER_TO_5M
    flatten = evaluate_agent_clock(handoff.snapshot, now=FLATTEN_TIME)
    assert flatten.operation == IntradayAgentOperation.FLATTEN_REQUIRED

    result = executor.execute_mandatory_flatten(
        flatten,
        fill_price=132.0,
        occurred_at=FLATTEN_TIME,
        signal_id="MU-MANDATORY-FLAT-1",
    )

    assert result.snapshot.state == IntradayState.EXITED
    assert result.snapshot.share_quantity == 0
    assert result.trade.state == TradeState.CLOSED
    assert result.trade.exit_price == 132.0
    assert result.receipt.action == "EXIT"
    assert result.receipt.reason == "MANDATORY_INTRADAY_FLATTEN"
    assert result.receipt.remaining_quantity == 0
    assert result.receipt.realized_pnl_this_event == pytest.approx(
        (132.0 - 130.0) * opened.trade.quantity
    )
    assert result.receipt.realized_r_this_event == pytest.approx(2.5)
    assert ledger.find_open("MU", InstrumentSelected.STOCK) == []


def test_flatten_cannot_be_forced_before_clock_governor_requires_it(tmp_path):
    executor = AgenticIntradayPaperExecutor(AccountPaperLedger(tmp_path))
    opened = executor.execute_entry(entry_decision())
    handoff = evaluate_agent_clock(opened.snapshot, now=FIVE_MINUTE_TIME)
    management = evaluate_agent_clock(handoff.snapshot, now=MANAGEMENT_TIME)
    forged = replace(management, operation=IntradayAgentOperation.FLATTEN_REQUIRED)

    with pytest.raises(IntradayPaperExecutionError, match="INTRADAY_FLATTEN_NOT_DUE"):
        executor.execute_mandatory_flatten(
            forged,
            fill_price=131.0,
            occurred_at=MANAGEMENT_TIME,
            signal_id="MU-EARLY-FLAT",
        )


def test_deterministic_model_exit_can_close_before_mandatory_flatten(tmp_path):
    ledger = AccountPaperLedger(tmp_path)
    executor = AgenticIntradayPaperExecutor(ledger)
    opened = executor.execute_entry(entry_decision())
    handoff = evaluate_agent_clock(opened.snapshot, now=FIVE_MINUTE_TIME)

    result = executor.execute_exit(
        handoff.snapshot,
        fill_price=128.8,
        occurred_at=datetime(2026, 8, 21, 18, 0, tzinfo=UTC),
        signal_id="MU-5M-MODEL-EXIT-1",
        reason="DETERMINISTIC_5M_EXIT",
    )

    assert result.snapshot.state == IntradayState.EXITED
    assert result.receipt.reason == "DETERMINISTIC_5M_EXIT"
    assert result.receipt.realized_pnl_this_event < 0
    assert result.receipt.realized_r_this_event < 0
    assert ledger.find_open("MU", InstrumentSelected.STOCK) == []


def test_add_and_partial_are_fail_closed_until_management_rules_are_frozen(tmp_path):
    executor = AgenticIntradayPaperExecutor(AccountPaperLedger(tmp_path))

    with pytest.raises(IntradayPaperExecutionError, match="INTRADAY_ADD_NOT_ENABLED_V1"):
        executor.execute_add()
    with pytest.raises(IntradayPaperExecutionError, match="INTRADAY_PARTIAL_NOT_ENABLED_V1"):
        executor.execute_partial()
