"""Leakage-resistant quantitative strategy validation and promotion gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from itertools import pairwise
from statistics import fmean


class Sample(StrEnum):
    TRAIN = "TRAIN"
    TEST = "TEST"


class PromotionDecision(StrEnum):
    HOLD_RESEARCH = "HOLD_RESEARCH"
    ELIGIBLE_FOR_PAPER = "ELIGIBLE_FOR_PAPER"


@dataclass(frozen=True)
class ReturnObservation:
    period: str
    strategy_return: float
    benchmark_return: float
    regime: str
    sample: Sample

    def __post_init__(self) -> None:
        date.fromisoformat(self.period)
        if not self.regime:
            raise ValueError("regime is required")

    @property
    def excess_return(self) -> float:
        return self.strategy_return - self.benchmark_return


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str

    def __post_init__(self) -> None:
        points = tuple(
            date.fromisoformat(value)
            for value in (
                self.train_start,
                self.train_end,
                self.test_start,
                self.test_end,
            )
        )
        if not self.fold_id:
            raise ValueError("fold_id is required")
        if not points[0] <= points[1] < points[2] <= points[3]:
            raise ValueError("walk-forward windows overlap or are out of order")


@dataclass(frozen=True)
class ValidationPolicy:
    minimum_test_observations: int = 30
    minimum_test_excess_return: float = 0.0
    maximum_test_drawdown: float = 0.10
    minimum_positive_regime_share: float = 0.50

    def __post_init__(self) -> None:
        if self.minimum_test_observations <= 0:
            raise ValueError("minimum_test_observations must be positive")
        if self.maximum_test_drawdown <= 0:
            raise ValueError("maximum_test_drawdown must be positive")
        if not 0 <= self.minimum_positive_regime_share <= 1:
            raise ValueError("regime share must be between zero and one")


@dataclass(frozen=True)
class ValidationReport:
    strategy_version: str
    train_observations: int
    test_observations: int
    train_mean_excess_return: float
    test_mean_excess_return: float
    test_max_drawdown: float
    regime_mean_excess: tuple[tuple[str, float], ...]
    decision: PromotionDecision
    reasons: tuple[str, ...]


def validate_strategy(
    *,
    strategy_version: str,
    observations: tuple[ReturnObservation, ...],
    folds: tuple[WalkForwardFold, ...],
    policy: ValidationPolicy | None = None,
) -> ValidationReport:
    policy = policy or ValidationPolicy()
    if not strategy_version:
        raise ValueError("strategy_version is required")
    if not folds:
        raise ValueError("at least one walk-forward fold is required")
    _validate_fold_order(folds)

    train = tuple(item for item in observations if item.sample == Sample.TRAIN)
    test = tuple(item for item in observations if item.sample == Sample.TEST)
    regime_names = sorted({item.regime for item in test})
    regime_means = tuple(
        (
            regime,
            fmean(item.excess_return for item in test if item.regime == regime),
        )
        for regime in regime_names
    )
    test_excess = tuple(item.excess_return for item in test)

    reasons: list[str] = []
    if len(test) < policy.minimum_test_observations:
        reasons.append("INSUFFICIENT_OUT_OF_SAMPLE_HISTORY")
    test_mean = fmean(test_excess) if test_excess else 0.0
    if test_mean <= policy.minimum_test_excess_return:
        reasons.append("OUT_OF_SAMPLE_EXCESS_RETURN_NOT_POSITIVE")
    drawdown = _max_drawdown(tuple(item.strategy_return for item in test))
    if drawdown > policy.maximum_test_drawdown:
        reasons.append("OUT_OF_SAMPLE_DRAWDOWN_LIMIT")
    positive_share = (
        sum(value > 0 for _, value in regime_means) / len(regime_means)
        if regime_means
        else 0.0
    )
    if positive_share < policy.minimum_positive_regime_share:
        reasons.append("REGIME_ROBUSTNESS_NOT_ESTABLISHED")

    decision = (
        PromotionDecision.HOLD_RESEARCH
        if reasons
        else PromotionDecision.ELIGIBLE_FOR_PAPER
    )
    return ValidationReport(
        strategy_version=strategy_version,
        train_observations=len(train),
        test_observations=len(test),
        train_mean_excess_return=(
            fmean(item.excess_return for item in train) if train else 0.0
        ),
        test_mean_excess_return=test_mean,
        test_max_drawdown=drawdown,
        regime_mean_excess=regime_means,
        decision=decision,
        reasons=tuple(reasons or ("OUT_OF_SAMPLE_THRESHOLDS_MET",)),
    )


def _validate_fold_order(folds: tuple[WalkForwardFold, ...]) -> None:
    ordered = sorted(folds, key=lambda fold: fold.test_start)
    for previous, current in pairwise(ordered):
        if date.fromisoformat(previous.test_end) >= date.fromisoformat(
            current.test_start
        ):
            raise ValueError("walk-forward test windows overlap")


def _max_drawdown(returns: tuple[float, ...]) -> float:
    equity = peak = 1.0
    maximum = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    return maximum
