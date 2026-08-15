from datetime import UTC, datetime

import pytest

from daily_alpha.signals import SignalAction, SignalError, parse_pine_signal


def test_parse_entry_signal():
    signal = parse_pine_signal(
        {
            "signal_id": "abc-123",
            "symbol": "rdw",
            "action": "entry_long",
            "strategy": "QARS Turtle",
            "strategy_version": "1.0.0",
            "timeframe": "1D",
            "price": 15.25,
            "bar_time": "2026-08-15T16:00:00Z",
        },
        received_at=datetime(2026, 8, 15, 16, 5, tzinfo=UTC),
    )

    assert signal.symbol == "RDW"
    assert signal.action == SignalAction.ENTRY_LONG
    assert signal.is_entry


def test_stale_signal_is_rejected():
    with pytest.raises(SignalError, match="stale"):
        parse_pine_signal(
            {
                "symbol": "RDW",
                "action": "EXIT",
                "strategy": "QARS Turtle",
                "strategy_version": "1.0.0",
                "timeframe": "1D",
                "price": 15.25,
                "bar_time": "2026-08-15T15:00:00Z",
            },
            received_at=datetime(2026, 8, 15, 16, 0, tzinfo=UTC),
        )
