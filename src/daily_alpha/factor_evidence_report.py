"""Research-only factor decay and regime/sector evidence reporting.

This module groups already point-in-time ``FactorReturnObservation`` records into
explicit horizon and cross-sectional slices. It never changes factor weights or
candidate ranking from observed returns.
"""

from __future__ import annotations

from collections import defaultdict
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
