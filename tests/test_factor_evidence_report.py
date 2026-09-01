from daily_alpha.factor_attribution import FactorReturnObservation
from daily_alpha.factor_evidence_report import build_factor_evidence_report


def _observations(horizon):
    rows = []
    for index in range(40):
        factor_value = -1.0 + index * (2.0 / 39.0)
        forward_return = factor_value * (0.04 if horizon == 5 else 0.02)
        rows.append(
            FactorReturnObservation(
                symbol=f"S{horizon}_{index:02d}",
                factor="momentum",
                factor_value=factor_value,
                forward_return=forward_return,
                as_of="2026-08-19",
                horizon_bars=horizon,
                regime="TREND" if index < 20 else "CHOP",
                sector="Technology" if index % 2 == 0 else "Industrials",
            )
        )
    return rows


def test_factor_report_surfaces_horizon_decay_and_cross_sectional_slices():
    report = build_factor_evidence_report(
        _observations(5) + _observations(20),
        minimum_sample=10,
    )

    assert report["factor"] == "momentum"
    assert report["observations"] == 80
    assert [row["horizon_bars"] for row in report["horizon_decay"]] == [5, 20]
    assert all(row["sufficient_sample"] for row in report["horizon_decay"])
    assert report["horizon_decay"][0]["rank_ic"] == 1.0
    assert report["horizon_decay"][1]["rank_ic"] == 1.0
    assert report["rank_ic_sign_consistent_across_sufficient_horizons"] is True
    assert len(report["by_regime"]) == 4
    assert len(report["by_sector"]) == 4
    assert all(row["sufficient_sample"] for row in report["by_regime"])
    assert all(row["sufficient_sample"] for row in report["by_sector"])
    assert [row["horizon_bars"] for row in report["outlier_sensitivity"]] == [5, 20]
    assert all(
        row["interpretation"] == "OUTLIER_SENSITIVITY_ONLY"
        for row in report["outlier_sensitivity"]
    )
    assert all(
        row["without_largest_absolute_return"] is not None
        for row in report["outlier_sensitivity"]
    )
    assert report["research_only"] is True
    assert report["trading_authorized"] is False
    assert report["live_trading_enabled"] is False


def test_factor_report_exposes_dependence_on_largest_absolute_return():
    rows = _observations(5)
    rows.append(
        FactorReturnObservation(
            symbol="OUTLIER",
            factor="momentum",
            factor_value=-0.95,
            forward_return=1.25,
            as_of="2026-08-19",
            horizon_bars=5,
            regime="TREND",
            sector="Technology",
        )
    )

    report = build_factor_evidence_report(rows, minimum_sample=10)
    sensitivity = report["outlier_sensitivity"][0]

    assert sensitivity["excluded_symbol"] == "OUTLIER"
    assert sensitivity["excluded_forward_return"] == 1.25
    assert sensitivity["excluded_absolute_return"] == 1.25
    assert sensitivity["full_sample"]["observations"] == 41
    assert sensitivity["without_largest_absolute_return"]["observations"] == 40
    assert sensitivity["without_largest_absolute_return"]["rank_ic"] == 1.0
