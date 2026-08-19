from datetime import UTC, datetime

from daily_alpha.execution_receipts import build_paper_execution_receipt

NOW = datetime(2026, 8, 19, 14, 5, tzinfo=UTC)


def _option_trade(**overrides):
    trade = {
        "trade_id": "trade-1",
        "signal_id": "entry-1",
        "symbol": "AMD",
        "instrument": "OPTION",
        "quantity": 2,
        "entry_price": 5.0,
        "entry_time": "2026-08-19T14:00:00+00:00",
        "state": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "realized_pnl": None,
        "fallback_reason": "QUALIFIED_OPTION_FOUND",
        "option_expiration": "2026-10-16",
        "option_strike": 250.0,
        "option_type": "CALL",
        "target_quantity": 4,
        "runner_stage": "STARTER",
        "add1_signal_id": None,
        "add2_signal_id": None,
        "harvest_signal_id": None,
        "sector": "Information Technology",
    }
    trade.update(overrides)
    return trade


def test_option_entry_receipt_uses_contract_multiplier_and_actual_entry_price():
    receipt = build_paper_execution_receipt(
        action="ENTRY_LONG",
        paper={"trade": _option_trade(), "account_id": "paper-shadow-v24"},
        fill_price=5.0,
        initial_risk_basis=1_000.0,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["instrument"] == "OPTION"
    assert receipt["option_expiration"] == "2026-10-16"
    assert receipt["option_strike"] == 250.0
    assert receipt["option_type"] == "CALL"
    assert receipt["fill_price"] == 5.0
    assert receipt["fill_quantity"] == 2
    assert receipt["fill_notional"] == 1_000.0
    assert receipt["remaining_quantity"] == 2
    assert receipt["remaining_cost_basis"] == 1_000.0
    assert receipt["r_basis_status"] == "NO_REALIZED_PNL_YET"
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False


def test_option_add_receipt_reports_increment_and_weighted_remaining_cost_basis():
    before = _option_trade(quantity=2, entry_price=5.0)
    after = _option_trade(
        quantity=3,
        entry_price=5.16666667,
        runner_stage="ADD_1_ATR",
        add1_signal_id="add-1",
    )
    receipt = build_paper_execution_receipt(
        action="ADD",
        paper={
            "updated_trades": [after],
            "runner_stage": "ADD_1_ATR",
            "account_id": "paper-shadow-v24",
        },
        fill_price=5.5,
        before_trade=before,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["signal_id"] == "add-1"
    assert receipt["fill_quantity"] == 1
    assert receipt["fill_notional"] == 550.0
    assert receipt["remaining_quantity"] == 3
    assert receipt["remaining_cost_basis"] == 1_550.0
    assert receipt["average_entry_after"] == 5.16666667
    assert receipt["runner_stage_after"] == "ADD_1_ATR"


def test_option_partial_receipt_reports_realized_pnl_and_r_when_basis_is_known():
    before = _option_trade(
        quantity=4,
        entry_price=5.0,
        runner_stage="ADD_2_ATR",
        add1_signal_id="add-1",
        add2_signal_id="add-2",
        realized_pnl=0.0,
    )
    after = _option_trade(
        quantity=3,
        entry_price=5.0,
        runner_stage="HARVEST_3_ATR",
        add1_signal_id="add-1",
        add2_signal_id="add-2",
        harvest_signal_id="partial-1",
        realized_pnl=200.0,
    )
    receipt = build_paper_execution_receipt(
        action="PARTIAL",
        paper={
            "updated_trades": [after],
            "runner_stage": "HARVEST_3_ATR",
            "account_id": "paper-shadow-v24",
        },
        fill_price=7.0,
        before_trade=before,
        initial_risk_basis=1_000.0,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["signal_id"] == "partial-1"
    assert receipt["fill_quantity"] == 1
    assert receipt["fill_notional"] == 700.0
    assert receipt["remaining_quantity"] == 3
    assert receipt["realized_pnl_this_event"] == 200.0
    assert receipt["cumulative_realized_pnl"] == 200.0
    assert receipt["realized_r_this_event"] == 0.2
    assert receipt["r_basis_status"] == "AVAILABLE"


def test_option_exit_receipt_is_explicit_when_initial_risk_was_not_persisted():
    before = _option_trade(
        quantity=3,
        entry_price=5.0,
        runner_stage="HARVEST_3_ATR",
        realized_pnl=200.0,
    )
    closed = _option_trade(
        quantity=3,
        entry_price=5.0,
        runner_stage="HARVEST_3_ATR",
        state="CLOSED",
        exit_price=6.0,
        exit_time=NOW.isoformat(),
        realized_pnl=500.0,
    )
    receipt = build_paper_execution_receipt(
        action="EXIT",
        paper={
            "closed_trades": [closed],
            "signal_id": "exit-1",
            "account_id": "paper-shadow-v24",
        },
        fill_price=6.0,
        before_trade=before,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["signal_id"] == "exit-1"
    assert receipt["fill_quantity"] == 3
    assert receipt["fill_notional"] == 1_800.0
    assert receipt["remaining_quantity"] == 0
    assert receipt["remaining_cost_basis"] == 0.0
    assert receipt["realized_pnl_this_event"] == 300.0
    assert receipt["cumulative_realized_pnl"] == 500.0
    assert receipt["realized_r_this_event"] is None
    assert receipt["r_basis_status"] == "INITIAL_RISK_NOT_PERSISTED"


def test_stock_entry_receipt_does_not_apply_option_multiplier():
    stock = _option_trade(
        trade_id="stock-trade-1",
        symbol="CAT",
        instrument="STOCK",
        quantity=10,
        entry_price=300.0,
        option_expiration=None,
        option_strike=None,
        option_type=None,
        target_quantity=10,
    )
    receipt = build_paper_execution_receipt(
        action="ENTRY_LONG",
        paper={"trade": stock, "account_id": "paper-shadow-v25"},
        fill_price=300.0,
        occurred_at=NOW,
    ).to_dict()

    assert receipt["instrument"] == "STOCK"
    assert receipt["fill_quantity"] == 10
    assert receipt["fill_notional"] == 3_000.0
    assert receipt["remaining_cost_basis"] == 3_000.0
