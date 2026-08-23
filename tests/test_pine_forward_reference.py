from datetime import UTC, datetime

import pytest

from daily_alpha.pine_forward_reference import parse_shadow_book_reference_snapshot
from daily_alpha.pine_v24_parity import PINE_V24_MODEL_ID, PINE_V24_STRATEGY_VERSION


def _event(**overrides):
    event = {
        "source": "TRADINGVIEW_PINE",
        "signal_id": "DINO-20260821-ENTRY_LONG",
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "model_id": PINE_V24_MODEL_ID,
        "timeframe": "1D",
        "price": 95.25,
        "bar_time": datetime(2026, 8, 21, 20, tzinfo=UTC).isoformat(),
        "entry_type": "NORMAL_BREAKOUT",
        "runner_stage": None,
        "disposition": "NO_TRADE",
        "reason": "PORTFOLIO_CONTEXT_REQUIRED",
        "paper_execution_triggered": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    event.update(overrides)
    return event


def _book(events):
    return {
        "events": events,
        "event_count_visible": len(events),
        "event_limit": 100,
        "scan_items_evaluated": len(events) + 3,
        "scan_truncated": False,
    }


def _parse(book):
    return parse_shadow_book_reference_snapshot(
        book,
        expected_model_id=PINE_V24_MODEL_ID,
        expected_strategy_version=PINE_V24_STRATEGY_VERSION,
    )


def test_genuine_pine_event_remains_reference_even_when_paper_layer_says_no_trade():
    snapshot = _parse(_book([_event()]))

    assert snapshot.complete is True
    assert snapshot.event_count_visible == 1
    assert snapshot.signals[0].action == "ENTRY_LONG"
    assert snapshot.signals[0].price == pytest.approx(95.25)
    assert snapshot.signals[0].source_id == "DINO-20260821-ENTRY_LONG"
    assert snapshot.signals[0].entry_type == "NORMAL_BREAKOUT"


def test_runner_stage_is_preserved_without_inventing_unpersisted_quantity():
    snapshot = _parse(
        _book(
            [
                _event(
                    signal_id="DINO-20260822-ADD_1_ATR",
                    action="ADD",
                    runner_stage="ADD_1_ATR",
                    entry_type="NORMAL_BREAKOUT",
                )
            ]
        )
    )

    signal = snapshot.signals[0]
    assert signal.runner_stage == "ADD_1_ATR"
    assert signal.quantity_units is None


def test_cross_book_event_fails_closed_instead_of_contaminating_sh24_reference():
    with pytest.raises(ValueError, match="crossed the requested model book"):
        _parse(_book([_event(model_id="PAPER_SHADOW_V25", strategy_version="2.5")]))


def test_incomplete_or_internally_inconsistent_monitor_evidence_fails_closed():
    truncated = _book([_event()])
    truncated["scan_truncated"] = True
    with pytest.raises(ValueError, match="scan is truncated"):
        _parse(truncated)

    wrong_count = _book([_event()])
    wrong_count["event_count_visible"] = 2
    with pytest.raises(ValueError, match="does not match returned events"):
        _parse(wrong_count)


def test_naive_bar_time_and_unsupported_action_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        _parse(_book([_event(bar_time="2026-08-21T20:00:00")]))

    with pytest.raises(ValueError, match="unsupported persisted Pine action"):
        _parse(_book([_event(action="ARMED")]))


def test_duplicate_signal_id_is_rejected_and_complete_empty_capture_is_explicit():
    duplicate = _event()
    with pytest.raises(ValueError, match="duplicate persisted Pine signal_id"):
        _parse(_book([duplicate, dict(duplicate)]))

    empty = _parse(_book([]))
    assert empty.complete is True
    assert empty.signals == ()
    assert empty.event_count_visible == 0
