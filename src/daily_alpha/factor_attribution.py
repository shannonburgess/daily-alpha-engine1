"""Research-only factor attribution primitives for Daily Alpha.

The engine makes factor evidence explicit without turning factor scores into trade
authorization. It supports deterministic weighted contributions, cross-sectional
rank information coefficients, and simple ablation evidence for champion/challenger
research.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

FACTOR_NAMES = (
    "momentum",
    "relative_strength",
    "trendability",
    "liquidity_capacity",
    "sector_industry_leadership",
    "volatility_quality",
    "options_confirmation",
    "catalyst_state",
    "breadth_regime",
)


@dataclass(frozen=True)
class FactorVector:
    symbol: str
    as_of: str
    factors: dict[str, float]
    regime: str = "UNSPECIFIED"
    sector: str = "Unknown"
    industry: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.as_of.strip():
            raise ValueError("FACTOR_VECTOR_IDENTITY_REQUIRED")
        unknown = set(self.factors) - set(FACTOR_NAMES)
        if unknown:
            raise ValueError(f"FACTOR_VECTOR_UNKNOWN_FACTORS:{sorted(unknown)}")
        for name, value in self.factors.items():
            if not isfinite(value) or value < -1.0 or value > 1.0:
                raise ValueError(f"FACTOR_VALUE_OUT_OF_RANGE:{name}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FactorContribution:
    factor: str
    value: float
    weight: float
    contribution: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FactorScore:
    symbol: str
    as_of: str
    score: float
    contributions: tuple[FactorContribution, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contributions"] = [item.to_dict() for item in self.contributions]
        return payload


@dataclass(frozen=True)
class FactorReturnObservation:
    symbol: str
    factor: str
    factor_value: float
    forward_return: float
    as_of: str
    horizon_bars: int
    regime: str = "UNSPECIFIED"
    sector: str = "Unknown"

    def __post_init__(self) -> None:
        if self.factor not in FACTOR_NAMES:
            raise ValueError("FACTOR_OBSERVATION_FACTOR_INVALID")
        if not self.symbol.strip() or not self.as_of.strip():
            raise ValueError("FACTOR_OBSERVATION_IDENTITY_REQUIRED")
        if not isfinite(self.factor_value) or not -1.0 <= self.factor_value <= 1.0:
            raise ValueError("FACTOR_OBSERVATION_VALUE_INVALID")
        if not isfinite(self.forward_return):
            raise ValueError("FACTOR_OBSERVATION_RETURN_INVALID")
        if self.horizon_bars <= 0:
            raise ValueError("FACTOR_OBSERVATION_HORIZON_INVALID")


@dataclass(frozen=True)
class FactorEvidence:
    factor: str
    observations: int
    rank_ic: float | None
    hit_rate: float | None
    mean_forward_return_high_half: float | None
    mean_forward_return_low_half: float | None
    high_minus_low_return: float | None
    sufficient_sample: bool
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_factor_vector(
    vector: FactorVector,
    *,
    weights: dict[str, float],
) -> FactorScore:
    """Return explicit weighted contributions using only predeclared weights."""
    unknown = set(weights) - set(FACTOR_NAMES)
    if unknown:
        raise ValueError(f"FACTOR_WEIGHT_UNKNOWN:{sorted(unknown)}")
    if not weights:
        raise ValueError("FACTOR_WEIGHTS_REQUIRED")
    if any(not isfinite(value) or value < 0 for value in weights.values()):
        raise ValueError("FACTOR_WEIGHTS_INVALID")
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("FACTOR_WEIGHT_SUM_MUST_BE_POSITIVE")

    rows = []
    for factor in FACTOR_NAMES:
        weight = weights.get(factor, 0.0) / total_weight
        value = vector.factors.get(factor, 0.0)
        contribution = value * weight
        rows.append(
            FactorContribution(
                factor=factor,
                value=round(value, 8),
                weight=round(weight, 8),
                contribution=round(contribution, 8),
            )
        )
    score = sum(item.contribution for item in rows)
    return FactorScore(
        symbol=vector.symbol.upper(),
        as_of=vector.as_of,
        score=round(score, 8),
        contributions=tuple(rows),
    )


def evaluate_factor(
    observations: list[FactorReturnObservation],
    *,
    minimum_sample: int = 30,
) -> FactorEvidence:
    """Measure one factor's cross-sectional monotonicity and simple spread edge."""
    if minimum_sample <= 1:
        raise ValueError("FACTOR_MINIMUM_SAMPLE_INVALID")
    if not observations:
        raise ValueError("FACTOR_OBSERVATIONS_REQUIRED")
    factors = {item.factor for item in observations}
    horizons = {item.horizon_bars for item in observations}
    if len(factors) != 1:
        raise ValueError("FACTOR_EVIDENCE_REQUIRES_ONE_FACTOR")
    if len(horizons) != 1:
        raise ValueError("FACTOR_EVIDENCE_REQUIRES_ONE_HORIZON")

    ordered = sorted(observations, key=lambda item: (item.factor_value, item.symbol))
    values = [item.factor_value for item in ordered]
    returns = [item.forward_return for item in ordered]
    rank_ic = _spearman(values, returns)
    hit_rate = sum(item.forward_return > 0 for item in ordered) / len(ordered)

    midpoint = len(ordered) // 2
    low = ordered[:midpoint]
    high = ordered[midpoint:]
    low_return = _mean([item.forward_return for item in low])
    high_return = _mean([item.forward_return for item in high])
    spread = (
        None
        if low_return is None or high_return is None
        else high_return - low_return
    )
    return FactorEvidence(
        factor=next(iter(factors)),
        observations=len(ordered),
        rank_ic=None if rank_ic is None else round(rank_ic, 6),
        hit_rate=round(hit_rate, 6),
        mean_forward_return_high_half=(
            None if high_return is None else round(high_return, 8)
        ),
        mean_forward_return_low_half=(
            None if low_return is None else round(low_return, 8)
        ),
        high_minus_low_return=None if spread is None else round(spread, 8),
        sufficient_sample=len(ordered) >= minimum_sample,
    )


def ablation_delta(
    *,
    full_metric: float,
    without_factor_metric: float,
    factor: str,
) -> dict[str, Any]:
    """Record incremental evidence without declaring causal alpha from one metric."""
    if factor not in FACTOR_NAMES:
        raise ValueError("FACTOR_ABLATION_FACTOR_INVALID")
    if not isfinite(full_metric) or not isfinite(without_factor_metric):
        raise ValueError("FACTOR_ABLATION_METRIC_INVALID")
    return {
        "factor": factor,
        "full_metric": round(full_metric, 8),
        "without_factor_metric": round(without_factor_metric, 8),
        "delta": round(full_metric - without_factor_metric, 8),
        "interpretation": "INCREMENTAL_EVIDENCE_ONLY",
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_rank = _average_ranks(left)
    right_rank = _average_ranks(right)
    return _pearson(left_rank, right_rank)


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            original_index = indexed[position][0]
            ranks[original_index] = average_rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = (left_variance * right_variance) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
