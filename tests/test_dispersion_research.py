import pytest

from daily_alpha.dispersion_research import (
    DispersionStateThresholds,
    build_dispersion_snapshot,
    classify_dispersion_correlation_state,
    trailing_zscore,
)


def sample_returns(count=20):
    return {f"SYM{i:02d}": i / 100 for i in range(count)}


def test_build_dispersion_snapshot_uses_robust_cross_sectional_measures():
    snapshot = build_dispersion_snapshot(
        as_of="2026-08-14",
        returns_by_symbol=sample_returns(),
        market_return=0.01,
    )

    assert snapshot.symbol_count == 20
    assert snapshot.median_return == pytest.approx(0.095)
    assert snapshot.iqr == pytest.approx(0.095)
    assert snapshot.mad == pytest.approx(0.05)
    assert snapshot.winner_loser_spread == pytest.approx(0.152)
    assert snapshot.market_return == pytest.approx(0.01)


def test_dispersion_snapshot_fails_closed_on_too_small_or_invalid_universe():
    with pytest.raises(ValueError, match="insufficient symbols"):
        build_dispersion_snapshot(
            as_of="2026-08-14",
            returns_by_symbol=sample_returns(10),
        )

    values = sample_returns()
    values["BAD"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        build_dispersion_snapshot(
            as_of="2026-08-14",
            returns_by_symbol=values,
        )


def test_trailing_zscore_requires_point_in_time_history():
    assert trailing_zscore(current_value=2.0, trailing_values=(1.0,) * 10) is None
    assert trailing_zscore(current_value=2.0, trailing_values=(1.0,) * 20) == 0.0

    score = trailing_zscore(
        current_value=2.0,
        trailing_values=tuple(float(value) for value in range(20)),
    )
    assert score is not None
    assert score < 0


def test_thresholds_must_be_ordered_and_bounded():
    with pytest.raises(ValueError, match="ordered"):
        DispersionStateThresholds(
            high_dispersion_z=1.5,
            high_correlation=0.2,
            low_correlation=0.5,
        )


def test_classify_dispersion_correlation_state():
    thresholds = DispersionStateThresholds(
        high_dispersion_z=1.5,
        high_correlation=0.65,
        low_correlation=0.25,
    )

    assert (
        classify_dispersion_correlation_state(
            dispersion_z=1.2,
            average_correlation=0.80,
            thresholds=thresholds,
        )
        == "NORMAL_DISPERSION"
    )
    assert (
        classify_dispersion_correlation_state(
            dispersion_z=2.0,
            average_correlation=0.75,
            thresholds=thresholds,
        )
        == "HIGH_DISPERSION_HIGH_CORRELATION"
    )
    assert (
        classify_dispersion_correlation_state(
            dispersion_z=2.0,
            average_correlation=0.15,
            thresholds=thresholds,
        )
        == "HIGH_DISPERSION_LOW_CORRELATION"
    )
    assert (
        classify_dispersion_correlation_state(
            dispersion_z=2.0,
            average_correlation=0.45,
            thresholds=thresholds,
        )
        == "HIGH_DISPERSION_MIXED_CORRELATION"
    )
