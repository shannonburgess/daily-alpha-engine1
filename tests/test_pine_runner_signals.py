from datetime import UTC, datetime

import pytest

from daily_alpha.signals import SignalAction, SignalError, parse_pine_signal

NOW = datetime(2026, 8, 15, 16, 5, tzinfo=UTC)
BASE = {
    "strategy": "DA_TURTLE_ADAPTIVE_TREND",
    "strategy_version": "1.9",
    "timeframe": "1D",
    "bar_time": "2026-08-15T16:00:00Z",
}


def test_parse_add_signal_with_runner_metadata():
    signal = parse_pine_signal(
        {
            **BASE,
            "signal_id": "mu-add-1",
            "symbol": "MU",
            "action": "ADD",
            "price": 575.0,
            "position_fraction": 0.25,
            "runner_stage": "ADD_1_ATR",
        },
        received_at=NOW,
    )
    assert signal.action == SignalAction.ADD
    assert signal.is_add
    assert signal.position_fraction == 0.25
    assert signal.runner_stage == "ADD_1_ATR"


def test_parse_partial_signal_with_runner_metadata():
    signal = parse_pine_signal(
        {
            **BASE,
            "signal_id": "mu-partial-1",
            "symbol": "MU",
            "action": "PARTIAL",
            "price": 650.0,
            "position_fraction": 0.25,
            "runner_stage": "HARVEST_3_ATR",
        },
        received_at=NOW,
    )
    assert signal.action == SignalAction.PARTIAL
    assert signal.is_partial
    assert signal.position_fraction == 0.25
    assert signal.runner_stage == "HARVEST_3_ATR"


def test_runner_signal_requires_fraction():
    with pytest.raises(SignalError, match="position_fraction"):
        parse_pine_signal(
            {
                **BASE,
                "signal_id": "mu-add-bad",
                "symbol": "MU",
                "action": "ADD",
                "price": 575.0,
                "runner_stage": "ADD_1_ATR",
            },
            received_at=NOW,
        )


def test_runner_signal_rejects_fraction_over_one():
    with pytest.raises(SignalError, match="at most 1"):
        parse_pine_signal(
            {
                **BASE,
                "signal_id": "mu-add-bad",
                "symbol": "MU",
                "action": "ADD",
                "price": 575.0,
                "position_fraction": 1.25,
                "runner_stage": "ADD_1_ATR",
            },
            received_at=NOW,
        )
