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
    assert report["research_only"] is True
    assert report["trading_authorized"] is False
    assert report["live_trading_enabled"] is False
