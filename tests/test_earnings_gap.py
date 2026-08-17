import pytest

from daily_alpha.earnings_gap import (
    EarningsGapClass,
    EarningsGapObservation,
    classify_earnings_gap,
)


def _observation(**overrides):
    values = {
        "earnings_event": True,
        "previous_close": 75.0,
        "open": 86.0,
        "high": 92.0,
        "low": 84.0,
        "close": 90.0,
        "previous_atr": 5.0,
        "volume": 30_000_000,
        "average_volume_20": 12_000_000,
        "prior_20_day_high": 84.0,
        "rsi": 67.0,
        "bullish_trend_state": True,
    }
    values.update(overrides)
    return EarningsGapObservation(**values)


def test_gap_and_go_is_separate_eligible_event_entry():
    result = classify_earnings_gap(_observation())

    assert result.classification == EarningsGapClass.EARNINGS_GAP_GO
    assert result.eligible_entry is True
    assert result.gap_pct > 5.0
    assert result.gap_atr > 1.5
    assert result.relative_volume >= 1.5
    assert result.breakout is True


def test_gap_and_crap_is_rejected():
    result = classify_earnings_gap(
        _observation(open=90.0, high=92.0, low=77.0, close=78.0)
    )

    assert result.classification == EarningsGapClass.EARNINGS_GAP_CRAP
    assert result.eligible_entry is False


def test_ambiguous_earnings_gap_waits_for_confirmation():
    # Holds the gap and closes in the upper half of the range, but finishes below
    # the open, so it is neither a qualified Gap & Go nor an obvious Gap & Crap.
    result = classify_earnings_gap(
        _observation(open=86.0, high=91.0, low=83.0, close=87.5)
    )

    assert result.classification == EarningsGapClass.EARNINGS_WAIT
    assert result.eligible_entry is False


def test_non_earnings_gap_does_not_enter_event_sleeve():
    result = classify_earnings_gap(_observation(earnings_event=False))

    assert result.classification == EarningsGapClass.NONE
    assert result.eligible_entry is False


def test_gap_go_requires_prior_20_day_breakout():
    result = classify_earnings_gap(_observation(prior_20_day_high=91.0))

    assert result.classification == EarningsGapClass.EARNINGS_WAIT
    assert result.eligible_entry is False


def test_invalid_observation_fails_closed():
    with pytest.raises(ValueError):
        classify_earnings_gap(_observation(previous_atr=0.0))
