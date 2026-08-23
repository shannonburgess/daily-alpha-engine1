from datetime import UTC, datetime

from daily_alpha.pine_parity_compare import ReferenceSignal, compare_pine_signals
from daily_alpha.pine_v24_parity import ParitySignal

NOW = datetime(2026, 8, 21, 20, tzinfo=UTC)


def _python_signal(**overrides) -> ParitySignal:
    values = {
        "symbol": "DINO",
        "bar_index": 100,
        "bar_time": NOW,
        "action": "ENTRY_LONG",
        "price": 95.25,
        "entry_type": "NORMAL_BREAKOUT",
        "quantity_units": 2,
    }
    values.update(overrides)
    return ParitySignal(**values)


def _reference(**overrides) -> ReferenceSignal:
    values = {
        "symbol": "DINO",
        "bar_time": NOW,
        "action": "ENTRY_LONG",
        "price": 95.25,
        "entry_type": "NORMAL_BREAKOUT",
        "quantity_units": 2,
        "source_id": "tv-dino-20260821-entry",
    }
    values.update(overrides)
    return ReferenceSignal(**values)


def test_exact_reference_and_python_signal_produce_exact_report():
    report = compare_pine_signals([_reference()], [_python_signal()])

    assert report.exact is True
    assert report.reference_count == 1
    assert report.python_count == 1
    assert report.exact_match_count == 1
    assert report.mismatch_count == 0
    assert report.exact_match_rate == 1.0


def test_missing_and_extra_signals_remain_explicit():
    missing = compare_pine_signals([_reference()], [])
    extra = compare_pine_signals([], [_python_signal()])

    assert missing.mismatches[0].kind == "MISSING_PYTHON_SIGNAL"
    assert missing.mismatches[0].source_id == "tv-dino-20260821-entry"
    assert extra.mismatches[0].kind == "EXTRA_PYTHON_SIGNAL"


def test_semantic_differences_are_not_collapsed_into_one_score():
    reference = _reference(
        price=95.25,
        entry_type="NORMAL_BREAKOUT",
        runner_stage="ADD_1_ATR",
        quantity_units=1,
    )
    python_signal = _python_signal(
        action="ADD",
        price=95.5,
        entry_type="EARNINGS_GAP_GO",
        runner_stage="ADD_2_ATR",
        quantity_units=2,
    )

    report = compare_pine_signals([reference], [python_signal])

    assert report.exact is False
    assert {mismatch.kind for mismatch in report.mismatches} == {
        "ACTION_MISMATCH",
        "PRICE_MISMATCH",
        "ENTRY_TYPE_MISMATCH",
        "RUNNER_STAGE_MISMATCH",
        "QUANTITY_MISMATCH",
    }


def test_price_tolerance_is_explicit_and_configurable():
    reference = _reference(price=95.2500001)
    python_signal = _python_signal(price=95.25)

    strict = compare_pine_signals([reference], [python_signal])
    tolerant = compare_pine_signals(
        [reference],
        [python_signal],
        price_abs_tolerance=0.000001,
    )

    assert strict.exact is False
    assert tolerant.exact is True


def test_empty_reference_and_python_stream_is_exact():
    report = compare_pine_signals([], [])
    assert report.exact is True
    assert report.exact_match_rate == 1.0
