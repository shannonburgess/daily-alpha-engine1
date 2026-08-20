from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_orthogonality import (
    BehavioralFactorPoint,
    CoreFactorFamily,
    CoreFactorPoint,
    behavioral_core_orthogonality,
)


def _behavioral(ticker: str, value: float, *, as_of: datetime) -> BehavioralFactorPoint:
    return BehavioralFactorPoint(
        ticker=ticker,
        as_of=as_of,
        source_timestamp=as_of - timedelta(minutes=1),
        behavioral_change_score=value,
        provenance=f"behavioral:{ticker}",
    )


def _core(
    ticker: str,
    value: float,
    *,
    family: CoreFactorFamily,
    as_of: datetime,
) -> CoreFactorPoint:
    return CoreFactorPoint(
        ticker=ticker,
        family=family,
        as_of=as_of,
        source_timestamp=as_of - timedelta(minutes=1),
        value=value,
        provenance=f"core:{family.value}:{ticker}",
    )


def test_flags_rank_redundancy_against_ovtlyr_without_authorizing_promotion() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    tickers = tuple(f"T{index}" for index in range(8))
    behavioral = tuple(
        _behavioral(ticker, float(index), as_of=as_of)
        for index, ticker in enumerate(tickers)
    )
    core = tuple(
        _core(
            ticker,
            float(index * 10),
            family=CoreFactorFamily.OVTLYR,
            as_of=as_of,
        )
        for index, ticker in enumerate(tickers)
    )

    results = behavioral_core_orthogonality(
        behavioral,
        core,
        evaluation_cutoff=as_of,
    )
    ovtlyr = next(result for result in results if result.family == CoreFactorFamily.OVTLYR)

    assert ovtlyr.paired_observations == 8
    assert ovtlyr.spearman_rank_correlation == 1.0
    assert ovtlyr.absolute_rank_correlation == 1.0
    assert ovtlyr.redundancy_risk is True
    assert ovtlyr.status == "REDUNDANCY_RISK"
    assert ovtlyr.promotion_authorized is False
    assert ovtlyr.trading_authorized is False
    assert ovtlyr.live_trading_enabled is False


def test_reports_each_missing_core_family_as_insufficient_overlap() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    behavioral = (_behavioral("NVDA", 70.0, as_of=as_of),)

    results = behavioral_core_orthogonality(
        behavioral,
        (),
        evaluation_cutoff=as_of,
    )

    assert {result.family for result in results} == set(CoreFactorFamily)
    assert all(result.paired_observations == 0 for result in results)
    assert all(result.spearman_rank_correlation is None for result in results)
    assert all(result.redundancy_risk is None for result in results)
    assert all(result.status == "INSUFFICIENT_POINT_IN_TIME_OVERLAP" for result in results)


def test_excludes_future_points_and_requires_exact_point_in_time_join() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    future = as_of + timedelta(days=1)
    behavioral = tuple(
        _behavioral(f"T{index}", float(index), as_of=as_of)
        for index in range(8)
    ) + (_behavioral("FUTURE", 99.0, as_of=future),)
    core = tuple(
        _core(
            f"T{index}",
            float(8 - index),
            family=CoreFactorFamily.RELATIVE_STRENGTH,
            as_of=as_of,
        )
        for index in range(7)
    ) + (
        _core(
            "T7",
            1.0,
            family=CoreFactorFamily.RELATIVE_STRENGTH,
            as_of=as_of + timedelta(seconds=1),
        ),
        _core(
            "FUTURE",
            100.0,
            family=CoreFactorFamily.RELATIVE_STRENGTH,
            as_of=future,
        ),
    )

    result = next(
        item
        for item in behavioral_core_orthogonality(
            behavioral,
            core,
            evaluation_cutoff=as_of,
        )
        if item.family == CoreFactorFamily.RELATIVE_STRENGTH
    )

    assert result.paired_observations == 7
    assert result.status == "INSUFFICIENT_POINT_IN_TIME_OVERLAP"
    assert result.spearman_rank_correlation is None


def test_conflicting_duplicate_factor_evidence_fails_closed() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    behavioral = (_behavioral("NVDA", 70.0, as_of=as_of),)
    first = _core("NVDA", 1.0, family=CoreFactorFamily.OVTLYR, as_of=as_of)
    conflicting = CoreFactorPoint(
        ticker="NVDA",
        family=CoreFactorFamily.OVTLYR,
        as_of=as_of,
        source_timestamp=as_of - timedelta(minutes=1),
        value=2.0,
        provenance="core:conflicting",
    )

    with pytest.raises(ValueError, match="CONFLICTING_DUPLICATE_CORE_FACTOR_POINT"):
        behavioral_core_orthogonality(
            behavioral,
            (first, conflicting),
            evaluation_cutoff=as_of,
        )


def test_rejects_lookahead_source_timestamp() -> None:
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="source_timestamp cannot be after as_of"):
        CoreFactorPoint(
            ticker="NVDA",
            family=CoreFactorFamily.EARNINGS_REVISIONS,
            as_of=as_of,
            source_timestamp=as_of + timedelta(seconds=1),
            value=1.0,
            provenance="future",
        )
