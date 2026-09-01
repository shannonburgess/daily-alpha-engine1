from daily_alpha.factor_attribution import FactorReturnObservation
from daily_alpha.factor_evidence_report import build_factor_ic_history_report


def _dated_observations(observation_date, *, count=12, horizon=5, inverted=False):
    rows = []
    for index in range(count):
        factor_value = -1.0 + index * (2.0 / max(count - 1, 1))
        direction = -1.0 if inverted else 1.0
        rows.append(
            FactorReturnObservation(
                symbol=f"D{observation_date}_{index:02d}",
                factor="momentum",
                factor_value=factor_value,
                forward_return=factor_value * 0.03 * direction,
                as_of=f"{observation_date}T16:00:00-04:00",
                horizon_bars=horizon,
                regime="TREND",
                sector="Technology",
            )
        )
    return rows


def test_factor_ic_history_uses_independent_dated_cross_sections_and_rolling_history():
    rows = []
    for day in range(1, 7):
        rows.extend(_dated_observations(f"2026-08-{day:02d}"))

    report = build_factor_ic_history_report(
        rows,
        minimum_cross_section=10,
        minimum_dates=4,
        rolling_dates=3,
    )

    assert report["factor"] == "momentum"
    assert report["observations"] == 72
    assert report["interpretation"] == "RETROSPECTIVE_FACTOR_STABILITY_EVIDENCE_ONLY"
    horizon = report["horizons"][0]
    assert horizon["horizon_bars"] == 5
    assert horizon["distinct_observation_dates"] == 6
    assert horizon["sufficient_date_count"] == 6
    assert horizon["sufficient_history"] is True
    assert horizon["mean_rank_ic"] == 1.0
    assert horizon["median_rank_ic"] == 1.0
    assert horizon["positive_rank_ic_share"] == 1.0
    assert [row["rank_ic"] for row in horizon["daily_rank_ic"]] == [1.0] * 6
    assert [row["rolling_mean_rank_ic"] for row in horizon["daily_rank_ic"]] == [
        None,
        None,
        1.0,
        1.0,
        1.0,
        1.0,
    ]
    assert report["research_only"] is True
    assert report["trading_authorized"] is False
    assert report["live_trading_enabled"] is False


def test_factor_ic_history_excludes_insufficient_cross_sections_from_stability_summary():
    rows = []
    rows.extend(_dated_observations("2026-08-01", count=12))
    rows.extend(_dated_observations("2026-08-02", count=4, inverted=True))
    rows.extend(_dated_observations("2026-08-03", count=12))

    report = build_factor_ic_history_report(
        rows,
        minimum_cross_section=10,
        minimum_dates=3,
        rolling_dates=2,
    )

    horizon = report["horizons"][0]
    assert horizon["distinct_observation_dates"] == 3
    assert horizon["sufficient_date_count"] == 2
    assert horizon["sufficient_history"] is False
    assert horizon["mean_rank_ic"] == 1.0
    assert horizon["positive_rank_ic_share"] == 1.0
    assert horizon["daily_rank_ic"][1]["sufficient_cross_section"] is False
    assert horizon["daily_rank_ic"][2]["rolling_mean_rank_ic"] == 1.0
