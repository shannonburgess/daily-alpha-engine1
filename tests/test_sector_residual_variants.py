from datetime import UTC, datetime

from daily_alpha.sector_residual_research import (
    ResidualMomentumClass,
    SectorResidualMomentumState,
)
from daily_alpha.sector_residual_variants import (
    ResidualResearchVariant,
    evaluate_all_pre_registered_variants,
    evaluate_residual_variant,
)


def _state(
    *,
    residual_score: float = 0.04,
    sector_percentile: float = 0.70,
) -> SectorResidualMomentumState:
    return SectorResidualMomentumState(
        security_id="sec-1",
        ticker="TEST",
        sector="Energy",
        industry="Oil & Gas E&P",
        sector_proxy="XLE",
        decision_at=datetime(2026, 8, 21, 20, 0, tzinfo=UTC),
        residual_20d=0.03,
        residual_63d=0.04,
        residual_126d=0.06,
        residual_score=residual_score,
        sector_score=0.05,
        positive_residual_horizons=3,
        within_sector_percentile=sector_percentile,
        within_industry_percentile=0.75,
        classification=ResidualMomentumClass.STOCK_SPECIFIC_LEADER,
    )


def test_control_and_ranking_only_never_exclude_qualified_control_candidate() -> None:
    weak = _state(residual_score=-0.02, sector_percentile=0.10)

    control = evaluate_residual_variant(weak, ResidualResearchVariant.CONTROL)
    ranking = evaluate_residual_variant(weak, ResidualResearchVariant.RANKING_ONLY)

    assert control.included is True
    assert control.ranking_score is None
    assert ranking.included is True
    assert ranking.ranking_score == -0.02


def test_positive_residual_rule_is_independent_of_percentile_rules() -> None:
    positive_but_low_percentile = _state(residual_score=0.01, sector_percentile=0.20)

    positive = evaluate_residual_variant(
        positive_but_low_percentile,
        ResidualResearchVariant.RESIDUAL_POSITIVE,
    )
    p50 = evaluate_residual_variant(
        positive_but_low_percentile,
        ResidualResearchVariant.WITHIN_SECTOR_P50,
    )

    assert positive.included is True
    assert p50.included is False


def test_percentile_challengers_do_not_silently_add_positive_residual_requirement() -> None:
    high_percentile_negative_residual = _state(
        residual_score=-0.01,
        sector_percentile=0.80,
    )

    p50 = evaluate_residual_variant(
        high_percentile_negative_residual,
        ResidualResearchVariant.WITHIN_SECTOR_P50,
    )
    p65 = evaluate_residual_variant(
        high_percentile_negative_residual,
        ResidualResearchVariant.WITHIN_SECTOR_P65,
    )

    assert p50.included is True
    assert p65.included is True


def test_p50_and_p65_use_frozen_thresholds() -> None:
    at_p50 = _state(sector_percentile=0.50)
    below_p65 = _state(sector_percentile=0.649999)
    at_p65 = _state(sector_percentile=0.65)

    assert evaluate_residual_variant(
        at_p50, ResidualResearchVariant.WITHIN_SECTOR_P50
    ).included is True
    assert evaluate_residual_variant(
        below_p65, ResidualResearchVariant.WITHIN_SECTOR_P65
    ).included is False
    assert evaluate_residual_variant(
        at_p65, ResidualResearchVariant.WITHIN_SECTOR_P65
    ).included is True


def test_all_variants_are_deterministic_and_preserve_zero_authority() -> None:
    decisions = evaluate_all_pre_registered_variants(_state())

    assert [decision.variant for decision in decisions] == list(ResidualResearchVariant)
    assert all(decision.research_only is True for decision in decisions)
    assert all(decision.paper_entry_authorized is False for decision in decisions)
    assert all(decision.portfolio_mutation_authorized is False for decision in decisions)
    assert all(decision.trading_authorized is False for decision in decisions)
    assert all(decision.live_trading_enabled is False for decision in decisions)
