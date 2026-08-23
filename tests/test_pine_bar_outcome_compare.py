from datetime import UTC, datetime

import pytest

from daily_alpha.pine_bar_outcome_compare import (
    BarOutcomeKind,
    BarOutcomeMismatchKind,
    ReferenceBarOutcome,
    compare_v24_bar_outcomes,
)
from daily_alpha.pine_v24_parity import DailyBar, V24Parameters, run_v24_parity


def _bars() -> tuple[DailyBar, ...]:
    return (
        DailyBar(
            time=datetime(2026, 1, 2, 21, tzinfo=UTC),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=2_000_000.0,
        ),
        DailyBar(
            time=datetime(2026, 1, 5, 21, tzinfo=UTC),
            open=100.5,
            high=102.0,
            low=100.0,
            close=101.5,
            volume=2_100_000.0,
        ),
    )


def test_explicit_no_trade_outcomes_match_python_bars() -> None:
    bars = _bars()
    results = run_v24_parity("ABC", bars, V24Parameters())
    reference = tuple(
        ReferenceBarOutcome(
            symbol="ABC",
            bar_time=bar.time,
            outcome_kind=BarOutcomeKind.NO_TRADE,
            source_id=f"tv-{index}",
        )
        for index, bar in enumerate(bars)
    )

    report = compare_v24_bar_outcomes(reference, results)

    assert report.exact is True
    assert report.reference_count == 2
    assert report.python_count == 2
    assert report.exact_bar_count == 2
    assert report.mismatch_count == 0


def test_no_trade_is_not_inferred_from_missing_reference_bar() -> None:
    bars = _bars()
    results = run_v24_parity("ABC", bars, V24Parameters())
    reference = (
        ReferenceBarOutcome(
            symbol="ABC",
            bar_time=bars[0].time,
            outcome_kind=BarOutcomeKind.NO_TRADE,
            source_id="tv-0",
        ),
    )

    report = compare_v24_bar_outcomes(reference, results)

    assert report.exact is False
    assert report.mismatch_count == 1
    assert report.mismatches[0].kind is BarOutcomeMismatchKind.EXTRA_PYTHON_BAR
    assert report.mismatches[0].bar_time == bars[1].time


def test_rejection_reason_difference_is_explicit() -> None:
    bars = _bars()
    results = run_v24_parity("ABC", bars, V24Parameters())
    reference = (
        ReferenceBarOutcome(
            symbol="ABC",
            bar_time=bars[0].time,
            outcome_kind=BarOutcomeKind.REJECTED,
            rejection_reasons=("ADX_TOO_LOW",),
            source_id="tv-reject",
        ),
        ReferenceBarOutcome(
            symbol="ABC",
            bar_time=bars[1].time,
            outcome_kind=BarOutcomeKind.NO_TRADE,
            source_id="tv-1",
        ),
    )

    report = compare_v24_bar_outcomes(reference, results)

    kinds = {item.kind for item in report.mismatches}
    assert BarOutcomeMismatchKind.OUTCOME_KIND_MISMATCH in kinds
    assert BarOutcomeMismatchKind.REJECTION_REASONS_MISMATCH in kinds


def test_signal_outcome_requires_explicit_signal_actions() -> None:
    with pytest.raises(ValueError, match="SIGNAL outcome requires signal_actions"):
        ReferenceBarOutcome(
            symbol="ABC",
            bar_time=datetime(2026, 1, 2, 21, tzinfo=UTC),
            outcome_kind=BarOutcomeKind.SIGNAL,
        )


def test_no_trade_cannot_hide_rejection_reason() -> None:
    with pytest.raises(
        ValueError,
        match="NO_TRADE outcome cannot carry signals or rejection reasons",
    ):
        ReferenceBarOutcome(
            symbol="ABC",
            bar_time=datetime(2026, 1, 2, 21, tzinfo=UTC),
            outcome_kind=BarOutcomeKind.NO_TRADE,
            rejection_reasons=("ADX_TOO_LOW",),
        )
