"""Research-only factor decay and regime/sector evidence reporting.

This module groups already point-in-time ``FactorReturnObservation`` records into
explicit horizon and cross-sectional slices. It never changes factor weights or
candidate ranking from observed returns.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median
from typing import Any

from .factor_attribution import FactorReturnObservation, evaluate_factor


def build_factor_evidence_report(
    observations: list[FactorReturnObservation],
    *,
    minimum_sample: int = 30,
) -> dict[str, Any]:
    """Summarize factor decay plus regime/sector cuts without tuning weights.

    Each horizon also receives a deterministic single-observation outlier test.
    The observation with the largest absolute forward return is removed and the
    factor evidence is recomputed. This is a sensitivity diagnostic only: it
    does not alter factor weights or promote/demote a factor.
    """
    if not observations:
        raise ValueError("FACTOR_EVIDENCE_REPORT_OBSERVATIONS_REQUIRED")
    if minimum_sample <= 1:
        raise ValueError("FACTOR_MINIMUM_SAMPLE_INVALID")

    factors = {item.factor for item in observations}
    if len(factors) != 1:
        raise ValueError("FACTOR_EVIDENCE_REPORT_REQUIRES_ONE_FACTOR")
    factor = next(iter(factors))

    by_horizon: dict[int, list[FactorReturnObservation]] = defaultdict(list)
    for item in observations:
        by_horizon[item.horizon_bars].append(item)

    horizon_rows = []
    regime_rows = []
    sector_rows = []
    outlier_rows = []
    for horizon in sorted(by_horizon):
        horizon_observations = by_horizon[horizon]
        evidence = evaluate_factor(
            horizon_observations,
            minimum_sample=minimum_sample,
        )
        horizon_rows.append({"horizon_bars": horizon, **evidence.to_dict()})

        excluded = max(
            horizon_observations,
            key=lambda item: (abs(item.forward_return), item.symbol),
        )
        without_outlier = [item for item in horizon_observations if item is not excluded]
        outlier_evidence = (
            evaluate_factor(without_outlier, minimum_sample=minimum_sample)
            if without_outlier
            else None
        )
        outlier_rows.append(
            {
                "horizon_bars": horizon,
                "excluded_symbol": excluded.symbol,
                "excluded_forward_return": round(excluded.forward_return, 8),
                "excluded_absolute_return": round(abs(excluded.forward_return), 8),
                "full_sample": evidence.to_dict(),
                "without_largest_absolute_return": (
                    None if outlier_evidence is None else outlier_evidence.to_dict()
                ),
                "interpretation": "OUTLIER_SENSITIVITY_ONLY",
            }
        )

        by_regime: dict[str, list[FactorReturnObservation]] = defaultdict(list)
        by_sector: dict[str, list[FactorReturnObservation]] = defaultdict(list)
        for item in horizon_observations:
            by_regime[item.regime or "UNSPECIFIED"].append(item)
            by_sector[item.sector or "Unknown"].append(item)

        for regime, items in sorted(by_regime.items()):
            sliced = evaluate_factor(items, minimum_sample=minimum_sample)
            regime_rows.append(
                {
                    "horizon_bars": horizon,
                    "regime": regime,
                    **sliced.to_dict(),
                }
            )
        for sector, items in sorted(by_sector.items()):
            sliced = evaluate_factor(items, minimum_sample=minimum_sample)
            sector_rows.append(
                {
                    "horizon_bars": horizon,
                    "sector": sector,
                    **sliced.to_dict(),
                }
            )

    sufficient_horizons = [
        row for row in horizon_rows if row["sufficient_sample"] and row["rank_ic"] is not None
    ]
    signs = {
        1 if row["rank_ic"] > 0 else -1 if row["rank_ic"] < 0 else 0
        for row in sufficient_horizons
    }

    return {
        "factor": factor,
        "observations": len(observations),
        "minimum_sample": minimum_sample,
        "horizon_decay": horizon_rows,
        "by_regime": regime_rows,
        "by_sector": sector_rows,
        "outlier_sensitivity": outlier_rows,
        "sufficient_horizon_count": len(sufficient_horizons),
        "rank_ic_sign_consistent_across_sufficient_horizons": (
            len(signs) == 1 if sufficient_horizons else None
        ),
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def build_factor_ic_history_report(
    observations: list[FactorReturnObservation],
    *,
    minimum_cross_section: int = 20,
    minimum_dates: int = 5,
    rolling_dates: int = 5,
) -> dict[str, Any]:
    """Build point-in-time cross-sectional rank-IC history by forward horizon.

    Unlike pooled evidence across many snapshot dates, this report computes rank IC
    independently for each observation date. Rolling means use only the current and
    earlier dated IC observations in the ordered research history. The output is a
    retrospective evidence diagnostic and cannot change factor weights or authorize
    execution.
    """
    if not observations:
        raise ValueError("FACTOR_IC_HISTORY_OBSERVATIONS_REQUIRED")
    if minimum_cross_section <= 1:
        raise ValueError("FACTOR_IC_MINIMUM_CROSS_SECTION_INVALID")
    if minimum_dates <= 1:
        raise ValueError("FACTOR_IC_MINIMUM_DATES_INVALID")
    if rolling_dates <= 1:
        raise ValueError("FACTOR_IC_ROLLING_DATES_INVALID")

    factors = {item.factor for item in observations}
    if len(factors) != 1:
        raise ValueError("FACTOR_IC_HISTORY_REQUIRES_ONE_FACTOR")
    factor = next(iter(factors))

    by_horizon_and_date: dict[
        int, dict[str, list[FactorReturnObservation]]
    ] = defaultdict(lambda: defaultdict(list))
    for item in observations:
        observation_date = _normalize_observation_date(item.as_of)
        by_horizon_and_date[item.horizon_bars][observation_date].append(item)

    horizon_rows = []
    for horizon in sorted(by_horizon_and_date):
        date_groups = by_horizon_and_date[horizon]
        date_rows = []
        sufficient_rank_ics: list[float] = []
        for observation_date in sorted(date_groups):
            evidence = evaluate_factor(
                date_groups[observation_date],
                minimum_sample=minimum_cross_section,
            )
            rank_ic = evidence.rank_ic
            rolling_mean_rank_ic = None
            if evidence.sufficient_sample and rank_ic is not None:
                sufficient_rank_ics.append(rank_ic)
                if len(sufficient_rank_ics) >= rolling_dates:
                    window = sufficient_rank_ics[-rolling_dates:]
                    rolling_mean_rank_ic = round(sum(window) / len(window), 6)
            date_rows.append(
                {
                    "observation_date": observation_date,
                    "observations": evidence.observations,
                    "rank_ic": rank_ic,
                    "sufficient_cross_section": evidence.sufficient_sample,
                    "rolling_mean_rank_ic": rolling_mean_rank_ic,
                }
            )

        mean_rank_ic = (
            round(sum(sufficient_rank_ics) / len(sufficient_rank_ics), 6)
            if sufficient_rank_ics
            else None
        )
        median_rank_ic = (
            round(median(sufficient_rank_ics), 6) if sufficient_rank_ics else None
        )
        positive_share = (
            round(
                sum(value > 0 for value in sufficient_rank_ics) / len(sufficient_rank_ics),
                6,
            )
            if sufficient_rank_ics
            else None
        )
        horizon_rows.append(
            {
                "horizon_bars": horizon,
                "distinct_observation_dates": len(date_rows),
                "sufficient_date_count": len(sufficient_rank_ics),
                "minimum_dates": minimum_dates,
                "sufficient_history": len(sufficient_rank_ics) >= minimum_dates,
                "mean_rank_ic": mean_rank_ic,
                "median_rank_ic": median_rank_ic,
                "positive_rank_ic_share": positive_share,
                "daily_rank_ic": date_rows,
            }
        )

    return {
        "factor": factor,
        "observations": len(observations),
        "minimum_cross_section": minimum_cross_section,
        "minimum_dates": minimum_dates,
        "rolling_dates": rolling_dates,
        "horizons": horizon_rows,
        "date_normalization": "CALENDAR_DATE_FROM_AS_OF",
        "interpretation": "RETROSPECTIVE_FACTOR_STABILITY_EVIDENCE_ONLY",
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _normalize_observation_date(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("FACTOR_OBSERVATION_AS_OF_INVALID")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("FACTOR_OBSERVATION_AS_OF_INVALID") from exc
    return parsed.date().isoformat()
