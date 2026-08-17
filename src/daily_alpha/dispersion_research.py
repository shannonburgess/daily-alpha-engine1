"""Research-only cross-sectional dispersion diagnostics.

These functions calculate point-in-time market diagnostics from returns already
known at the observation date. They do not authorize trades or change risk limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import fmean, median, pstdev


@dataclass(frozen=True)
class DispersionSnapshot:
    as_of: str
    symbol_count: int
    median_return: float
    iqr: float
    mad: float
    winner_loser_spread: float
    market_return: float | None = None


@dataclass(frozen=True)
class DispersionStateThresholds:
    high_dispersion_z: float
    high_correlation: float
    low_correlation: float

    def __post_init__(self) -> None:
        if self.high_dispersion_z <= 0:
            raise ValueError("high_dispersion_z must be positive")
        if not -1 <= self.low_correlation <= self.high_correlation <= 1:
            raise ValueError("correlation thresholds must be ordered inside [-1, 1]")


def _quantile(values: list[float], probability: float) -> float:
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between zero and one")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_dispersion_snapshot(
    *,
    as_of: str,
    returns_by_symbol: dict[str, float],
    market_return: float | None = None,
    min_symbols: int = 20,
) -> DispersionSnapshot:
    """Build robust cross-sectional return-dispersion measures for one date."""

    date.fromisoformat(as_of)
    if min_symbols < 5:
        raise ValueError("min_symbols must be at least 5")
    if len(returns_by_symbol) < min_symbols:
        raise ValueError("insufficient symbols for dispersion snapshot")
    if any(not symbol for symbol in returns_by_symbol):
        raise ValueError("symbols must be non-empty")

    values = list(returns_by_symbol.values())
    if any(not math.isfinite(value) for value in values):
        raise ValueError("returns must be finite")
    if market_return is not None and not math.isfinite(market_return):
        raise ValueError("market_return must be finite when supplied")

    center = median(values)
    q25 = _quantile(values, 0.25)
    q75 = _quantile(values, 0.75)
    q10 = _quantile(values, 0.10)
    q90 = _quantile(values, 0.90)
    deviations = [abs(value - center) for value in values]

    return DispersionSnapshot(
        as_of=as_of,
        symbol_count=len(values),
        median_return=center,
        iqr=q75 - q25,
        mad=median(deviations),
        winner_loser_spread=q90 - q10,
        market_return=market_return,
    )


def trailing_zscore(
    *,
    current_value: float,
    trailing_values: tuple[float, ...],
    min_observations: int = 20,
) -> float | None:
    """Return a point-in-time z-score using only supplied trailing observations."""

    if min_observations < 2:
        raise ValueError("min_observations must be at least 2")
    if len(trailing_values) < min_observations:
        return None
    values = list(trailing_values)
    if not math.isfinite(current_value) or any(not math.isfinite(value) for value in values):
        raise ValueError("z-score inputs must be finite")

    sigma = pstdev(values)
    if sigma == 0:
        return 0.0
    return (current_value - fmean(values)) / sigma


def classify_dispersion_correlation_state(
    *,
    dispersion_z: float,
    average_correlation: float,
    thresholds: DispersionStateThresholds,
) -> str:
    """Classify an experimental dispersion/correlation state for research segmentation."""

    if not math.isfinite(dispersion_z) or not math.isfinite(average_correlation):
        raise ValueError("state inputs must be finite")
    if not -1 <= average_correlation <= 1:
        raise ValueError("average_correlation must be inside [-1, 1]")

    if dispersion_z < thresholds.high_dispersion_z:
        return "NORMAL_DISPERSION"
    if average_correlation >= thresholds.high_correlation:
        return "HIGH_DISPERSION_HIGH_CORRELATION"
    if average_correlation <= thresholds.low_correlation:
        return "HIGH_DISPERSION_LOW_CORRELATION"
    return "HIGH_DISPERSION_MIXED_CORRELATION"
