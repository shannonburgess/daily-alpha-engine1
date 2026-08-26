from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.sector_residual_research import (
    ResidualMomentumClass,
    ResidualMomentumPolicy,
    SectorResidualMomentumAnalyzer,
    SectorResidualObservation,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _observation(
    security_id: str,
    ticker: str,
    *,
    sector: str = "Energy",
    industry: str = "Oil & Gas E&P",
    stock: tuple[float, float, float] = (0.12, 0.20, 0.30),
    sector_returns: tuple[float, float, float] = (0.04, 0.08, 0.10),
    known_at: datetime | None = None,
    leverage: float = 1.0,
) -> SectorResidualObservation:
    return SectorResidualObservation(
        security_id=security_id,
        ticker=ticker,
        sector=sector,
        industry=industry,
        sector_proxy="XLE",
        as_of=NOW - timedelta(minutes=10),
        known_at=known_at or NOW - timedelta(minutes=5),
        stock_return_20d=stock[0],
        stock_return_63d=stock[1],
        stock_return_126d=stock[2],
        sector_return_20d=sector_returns[0],
        sector_return_63d=sector_returns[1],
        sector_return_126d=sector_returns[2],
        sector_proxy_leverage=leverage,
    )


def test_residual_momentum_decomposes_stock_minus_sector_and_ranks_within_sector() -> None:
    analyzer = SectorResidualMomentumAnalyzer()
    weak = _observation(
        "weak",
        "WEAK",
        stock=(0.06, 0.10, 0.14),
        sector_returns=(0.04, 0.08, 0.10),
    )
    strong = _observation(
        "strong",
        "STRONG",
        stock=(0.14, 0.24, 0.38),
        sector_returns=(0.04, 0.08, 0.10),
    )

    states = analyzer.evaluate([weak, strong], decision_at=NOW)
    by_ticker = {state.ticker: state for state in states}

    assert by_ticker["STRONG"].residual_20d == pytest.approx(0.10)
    assert by_ticker["STRONG"].residual_63d == pytest.approx(0.16)
    assert by_ticker["STRONG"].residual_126d == pytest.approx(0.28)
    assert by_ticker["STRONG"].residual_score == pytest.approx(0.154)
    assert by_ticker["STRONG"].within_sector_percentile == 1.0
    assert by_ticker["WEAK"].within_sector_percentile == 0.0
    assert by_ticker["STRONG"].classification == ResidualMomentumClass.STOCK_SPECIFIC_LEADER
    assert by_ticker["WEAK"].classification == ResidualMomentumClass.MIXED


def test_sector_beta_dominant_when_sector_is_positive_but_residual_is_not() -> None:
    observation = _observation(
        "beta",
        "BETA",
        stock=(0.03, 0.06, 0.09),
        sector_returns=(0.05, 0.10, 0.14),
    )

    (state,) = SectorResidualMomentumAnalyzer().evaluate([observation], decision_at=NOW)

    assert state.residual_score < 0
    assert state.sector_score > 0
    assert state.classification == ResidualMomentumClass.SECTOR_BETA_DOMINANT


def test_negative_residual_class_when_stock_and_sector_composites_are_weak() -> None:
    observation = _observation(
        "negative",
        "NEG",
        stock=(-0.08, -0.12, -0.15),
        sector_returns=(-0.02, -0.03, -0.04),
    )

    (state,) = SectorResidualMomentumAnalyzer().evaluate([observation], decision_at=NOW)

    assert state.residual_score < 0
    assert state.sector_score < 0
    assert state.classification == ResidualMomentumClass.NEGATIVE_RESIDUAL


def test_tied_residual_scores_receive_equal_average_rank_percentiles() -> None:
    first = _observation("a", "AAA")
    second = _observation("b", "BBB")
    third = _observation(
        "c",
        "CCC",
        stock=(0.20, 0.30, 0.40),
        sector_returns=(0.04, 0.08, 0.10),
    )

    states = SectorResidualMomentumAnalyzer().evaluate([third, second, first], decision_at=NOW)
    by_id = {state.security_id: state for state in states}

    assert by_id["a"].within_sector_percentile == pytest.approx(0.25)
    assert by_id["b"].within_sector_percentile == pytest.approx(0.25)
    assert by_id["c"].within_sector_percentile == 1.0


def test_industry_percentile_is_independent_of_sector_percentile() -> None:
    industry_a = _observation("a", "AAA", industry="Integrated Energy")
    industry_b = _observation(
        "b",
        "BBB",
        industry="Integrated Energy",
        stock=(0.18, 0.28, 0.40),
    )
    other_industry = _observation(
        "c",
        "CCC",
        industry="Oilfield Services",
        stock=(0.07, 0.11, 0.15),
    )

    states = SectorResidualMomentumAnalyzer().evaluate(
        [industry_a, industry_b, other_industry], decision_at=NOW
    )
    by_id = {state.security_id: state for state in states}

    assert by_id["b"].within_industry_percentile == 1.0
    assert by_id["a"].within_industry_percentile == 0.0
    assert by_id["c"].within_industry_percentile == 1.0
    assert by_id["c"].within_sector_percentile == 0.0


def test_future_known_input_fails_closed() -> None:
    observation = _observation("future", "FUT", known_at=NOW + timedelta(seconds=1))

    with pytest.raises(ValueError, match="future residual-momentum input"):
        SectorResidualMomentumAnalyzer().evaluate([observation], decision_at=NOW)


def test_signal_decomposition_rejects_leveraged_sector_proxy() -> None:
    with pytest.raises(ValueError, match="unlevered 1x sector proxy"):
        _observation("leveraged", "LEV", leverage=2.0)


def test_conflicting_duplicate_security_fails_closed() -> None:
    first = _observation("same", "AAA")
    second = _observation("same", "AAA", stock=(0.20, 0.30, 0.40))

    with pytest.raises(ValueError, match="conflicting residual-momentum input"):
        SectorResidualMomentumAnalyzer().evaluate([first, second], decision_at=NOW)


def test_identical_duplicate_is_idempotent_and_input_order_is_deterministic() -> None:
    first = _observation("a", "AAA")
    second = _observation("b", "BBB", stock=(0.18, 0.28, 0.40))
    analyzer = SectorResidualMomentumAnalyzer()

    left = analyzer.evaluate([first, second, first], decision_at=NOW)
    right = analyzer.evaluate([second, first], decision_at=NOW)

    assert left == right
    assert len(left) == 2


def test_research_state_has_no_paper_portfolio_or_live_authority() -> None:
    (state,) = SectorResidualMomentumAnalyzer().evaluate(
        [_observation("safe", "SAFE")], decision_at=NOW
    )

    assert state.research_only is True
    assert state.paper_entry_authorized is False
    assert state.portfolio_mutation_authorized is False
    assert state.trading_authorized is False
    assert state.live_trading_enabled is False


def test_invalid_policy_weights_and_thresholds_fail_closed() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        ResidualMomentumPolicy(weight_20d=0.5, weight_63d=0.5, weight_126d=0.5)
    with pytest.raises(ValueError, match="leader_percentile"):
        ResidualMomentumPolicy(leader_percentile=0.40, confirmation_percentile=0.50)


def test_known_at_cannot_precede_as_of() -> None:
    with pytest.raises(ValueError, match="known_at cannot precede as_of"):
        SectorResidualObservation(
            security_id="bad-time",
            ticker="BAD",
            sector="Energy",
            industry="Oil & Gas E&P",
            sector_proxy="XLE",
            as_of=NOW,
            known_at=NOW - timedelta(seconds=1),
            stock_return_20d=0.1,
            stock_return_63d=0.2,
            stock_return_126d=0.3,
            sector_return_20d=0.05,
            sector_return_63d=0.1,
            sector_return_126d=0.15,
        )
