from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.strategy_forensics import diagnose_opportunity
from daily_alpha.strategy_forensics_observations import (
    DecisionObservation,
    PriceBarObservation,
    build_forensics_path,
)


DECISION_TIME = datetime(2026, 8, 18, 20, 0, tzinfo=UTC)


def _decision(**overrides):
    values = {
        "decision_id": "decision-1",
        "symbol": "AAA",
        "strategy_version": "v2.4",
        "decision": "WAIT",
        "reason": "ADX_BELOW_GATE",
        "observed_at": DECISION_TIME,
        "reference_price": 100.0,
        "stop_price": 95.0,
        "executed": False,
        "exit_price": None,
    }
    values.update(overrides)
    return DecisionObservation(**values)


def _bar(hours, high, low, close):
    return PriceBarObservation(
        observed_at=DECISION_TIME + timedelta(hours=hours),
        high=high,
        low=low,
        close=close,
    )


def test_point_in_time_adapter_uses_only_post_decision_bars_inside_cutoff():
    evidence = build_forensics_path(
        _decision(),
        (
            _bar(-1, 101.0, 99.0, 100.0),
            _bar(1, 104.0, 99.0, 103.0),
            _bar(2, 112.0, 102.0, 110.0),
            _bar(3, 120.0, 108.0, 118.0),
        ),
        evaluation_cutoff=DECISION_TIME + timedelta(hours=2),
    )

    assert evidence.decision_id == "decision-1"
    assert evidence.bars_used == 2
    assert evidence.ignored_predecision_bars == 1
    assert evidence.ignored_after_cutoff_bars == 1
    assert evidence.path.max_price_after == 112.0
    assert evidence.path.min_price_after == 99.0
    assert evidence.path.terminal_price == 110.0
    assert evidence.trading_authorized is False
    assert evidence.live_trading_enabled is False

    diagnostic = diagnose_opportunity(evidence.path)
    assert diagnostic.classification == "MISSED_WINNER"
    assert diagnostic.mfe_r == 2.4


def test_point_in_time_adapter_caps_horizon_without_using_later_bars():
    evidence = build_forensics_path(
        _decision(),
        (
            _bar(1, 103.0, 99.0, 102.0),
            _bar(2, 105.0, 100.0, 104.0),
            _bar(3, 130.0, 101.0, 125.0),
        ),
        evaluation_cutoff=DECISION_TIME + timedelta(hours=3),
        max_bars=2,
    )

    assert evidence.bars_used == 2
    assert evidence.path.max_price_after == 105.0
    assert evidence.path.terminal_price == 104.0


def test_point_in_time_adapter_rejects_naive_cutoff_and_duplicate_bars():
    with pytest.raises(ValueError, match="CUTOFF_MUST_BE_TIMEZONE_AWARE"):
        build_forensics_path(
            _decision(),
            (_bar(1, 103.0, 99.0, 102.0),),
            evaluation_cutoff=(DECISION_TIME + timedelta(hours=2)).replace(tzinfo=None),
        )

    duplicate = _bar(1, 103.0, 99.0, 102.0)
    with pytest.raises(ValueError, match="DUPLICATE_BAR_TIMESTAMP"):
        build_forensics_path(
            _decision(),
            (duplicate, duplicate),
            evaluation_cutoff=DECISION_TIME + timedelta(hours=2),
        )


def test_point_in_time_adapter_requires_post_decision_evidence():
    with pytest.raises(ValueError, match="NO_POST_DECISION_BARS_IN_CUTOFF"):
        build_forensics_path(
            _decision(),
            (_bar(-1, 101.0, 99.0, 100.0),),
            evaluation_cutoff=DECISION_TIME + timedelta(hours=2),
        )
