"""Research-only sector/industry residual-momentum diagnostics.

This module is intentionally disconnected from PAPER/live execution. It decomposes a
pre-qualified stock candidate's raw momentum into sector/common and stock-specific
components so research can test whether a setup is primarily stock alpha or sector beta.

The first version deliberately uses a transparent stock-minus-sector residual rather than
fitting a rolling regression. Regression-based residuals remain a separate hypothesis and
must earn their own point-in-time validation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite


class ResidualMomentumClass(StrEnum):
    """Research classification only; never an execution instruction."""

    STOCK_SPECIFIC_LEADER = "STOCK_SPECIFIC_LEADER"
    POSITIVE_RESIDUAL = "POSITIVE_RESIDUAL"
    MIXED = "MIXED"
    SECTOR_BETA_DOMINANT = "SECTOR_BETA_DOMINANT"
    NEGATIVE_RESIDUAL = "NEGATIVE_RESIDUAL"


@dataclass(frozen=True, slots=True)
class ResidualMomentumPolicy:
    """Frozen first-pass policy from quant challenger #156."""

    weight_20d: float = 0.50
    weight_63d: float = 0.30
    weight_126d: float = 0.20
    positive_residual_floor: float = 0.0
    leader_percentile: float = 0.65
    confirmation_percentile: float = 0.50

    def __post_init__(self) -> None:
        weights = (self.weight_20d, self.weight_63d, self.weight_126d)
        if any(not isfinite(value) or value < 0 for value in weights):
            raise ValueError("residual-momentum weights must be finite and non-negative")
        if abs(sum(weights) - 1.0) > 1e-12:
            raise ValueError("residual-momentum weights must sum to 1.0")
        for name, value in (
            ("leader_percentile", self.leader_percentile),
            ("confirmation_percentile", self.confirmation_percentile),
        ):
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.leader_percentile < self.confirmation_percentile:
            raise ValueError("leader_percentile cannot be below confirmation_percentile")


@dataclass(frozen=True, slots=True)
class SectorResidualObservation:
    """Point-in-time momentum inputs for one already-qualified stock candidate."""

    security_id: str
    ticker: str
    sector: str
    industry: str
    sector_proxy: str
    as_of: datetime
    known_at: datetime
    stock_return_20d: float
    stock_return_63d: float
    stock_return_126d: float
    sector_return_20d: float
    sector_return_63d: float
    sector_return_126d: float
    sector_proxy_leverage: float = 1.0

    def __post_init__(self) -> None:
        for name in ("security_id", "ticker", "sector", "industry", "sector_proxy"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} cannot be blank")
        if self.as_of.tzinfo is None or self.known_at.tzinfo is None:
            raise ValueError("as_of and known_at must be timezone-aware")
        if self.known_at < self.as_of:
            raise ValueError("known_at cannot precede as_of")
        if self.sector_proxy_leverage != 1.0:
            raise ValueError("signal decomposition requires an unlevered 1x sector proxy")
        values = (
            self.stock_return_20d,
            self.stock_return_63d,
            self.stock_return_126d,
            self.sector_return_20d,
            self.sector_return_63d,
            self.sector_return_126d,
        )
        if any(not isfinite(value) for value in values):
            raise ValueError("momentum returns must be finite")


@dataclass(frozen=True, slots=True)
class SectorResidualMomentumState:
    """Deterministic research state produced from one observation."""

    security_id: str
    ticker: str
    sector: str
    industry: str
    sector_proxy: str
    decision_at: datetime
    residual_20d: float
    residual_63d: float
    residual_126d: float
    residual_score: float
    sector_score: float
    positive_residual_horizons: int
    within_sector_percentile: float
    within_industry_percentile: float
    classification: ResidualMomentumClass
    research_only: bool = True
    paper_entry_authorized: bool = False
    portfolio_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True, slots=True)
class _RawResidualState:
    observation: SectorResidualObservation
    residual_20d: float
    residual_63d: float
    residual_126d: float
    residual_score: float
    sector_score: float
    positive_residual_horizons: int


def _normalized_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("decision_at must be timezone-aware")
    return value.astimezone(UTC)


def _average_rank_percentiles(values: dict[str, float]) -> dict[str, float]:
    """Return deterministic [0,1] percentiles with average ranks for ties."""

    if not values:
        return {}
    if len(values) == 1:
        only = next(iter(values))
        return {only: 1.0}

    sorted_items = sorted(values.items(), key=lambda item: (item[1], item[0]))
    result: dict[str, float] = {}
    index = 0
    denominator = len(sorted_items) - 1
    while index < len(sorted_items):
        end = index
        score = sorted_items[index][1]
        while end + 1 < len(sorted_items) and sorted_items[end + 1][1] == score:
            end += 1
        average_rank = (index + end) / 2.0
        percentile = average_rank / denominator
        for position in range(index, end + 1):
            result[sorted_items[position][0]] = percentile
        index = end + 1
    return result


class SectorResidualMomentumAnalyzer:
    """Compute research-only sector/industry residual momentum for frozen candidates."""

    def __init__(self, policy: ResidualMomentumPolicy | None = None) -> None:
        self.policy = policy or ResidualMomentumPolicy()

    def evaluate(
        self,
        observations: Iterable[SectorResidualObservation],
        *,
        decision_at: datetime,
    ) -> tuple[SectorResidualMomentumState, ...]:
        decision_at_utc = _normalized_utc(decision_at)
        unique: dict[str, SectorResidualObservation] = {}
        for observation in observations:
            known_at_utc = observation.known_at.astimezone(UTC)
            as_of_utc = observation.as_of.astimezone(UTC)
            if known_at_utc > decision_at_utc or as_of_utc > decision_at_utc:
                raise ValueError(
                    f"future residual-momentum input for {observation.security_id}"
                )
            existing = unique.get(observation.security_id)
            if existing is not None and existing != observation:
                raise ValueError(
                    f"conflicting residual-momentum input for {observation.security_id}"
                )
            unique[observation.security_id] = observation

        raw = {
            security_id: self._raw_state(observation)
            for security_id, observation in unique.items()
        }
        sector_percentiles = self._group_percentiles(raw, key="sector")
        industry_percentiles = self._group_percentiles(raw, key="industry")

        states = [
            self._finalize(
                raw_state,
                decision_at=decision_at_utc,
                sector_percentile=sector_percentiles[security_id],
                industry_percentile=industry_percentiles[security_id],
            )
            for security_id, raw_state in raw.items()
        ]
        return tuple(sorted(states, key=lambda state: (state.sector, state.ticker, state.security_id)))

    def _raw_state(self, observation: SectorResidualObservation) -> _RawResidualState:
        residual_20d = observation.stock_return_20d - observation.sector_return_20d
        residual_63d = observation.stock_return_63d - observation.sector_return_63d
        residual_126d = observation.stock_return_126d - observation.sector_return_126d
        policy = self.policy
        residual_score = (
            residual_20d * policy.weight_20d
            + residual_63d * policy.weight_63d
            + residual_126d * policy.weight_126d
        )
        sector_score = (
            observation.sector_return_20d * policy.weight_20d
            + observation.sector_return_63d * policy.weight_63d
            + observation.sector_return_126d * policy.weight_126d
        )
        positive_horizons = sum(
            value > policy.positive_residual_floor
            for value in (residual_20d, residual_63d, residual_126d)
        )
        return _RawResidualState(
            observation=observation,
            residual_20d=residual_20d,
            residual_63d=residual_63d,
            residual_126d=residual_126d,
            residual_score=residual_score,
            sector_score=sector_score,
            positive_residual_horizons=positive_horizons,
        )

    @staticmethod
    def _group_percentiles(
        raw: dict[str, _RawResidualState], *, key: str
    ) -> dict[str, float]:
        groups: dict[str, dict[str, float]] = {}
        for security_id, state in raw.items():
            group = getattr(state.observation, key)
            groups.setdefault(group, {})[security_id] = state.residual_score
        result: dict[str, float] = {}
        for values in groups.values():
            result.update(_average_rank_percentiles(values))
        return result

    def _finalize(
        self,
        state: _RawResidualState,
        *,
        decision_at: datetime,
        sector_percentile: float,
        industry_percentile: float,
    ) -> SectorResidualMomentumState:
        classification = self._classify(
            residual_score=state.residual_score,
            sector_score=state.sector_score,
            positive_horizons=state.positive_residual_horizons,
            sector_percentile=sector_percentile,
        )
        observation = state.observation
        return SectorResidualMomentumState(
            security_id=observation.security_id,
            ticker=observation.ticker,
            sector=observation.sector,
            industry=observation.industry,
            sector_proxy=observation.sector_proxy,
            decision_at=decision_at,
            residual_20d=state.residual_20d,
            residual_63d=state.residual_63d,
            residual_126d=state.residual_126d,
            residual_score=state.residual_score,
            sector_score=state.sector_score,
            positive_residual_horizons=state.positive_residual_horizons,
            within_sector_percentile=sector_percentile,
            within_industry_percentile=industry_percentile,
            classification=classification,
        )

    def _classify(
        self,
        *,
        residual_score: float,
        sector_score: float,
        positive_horizons: int,
        sector_percentile: float,
    ) -> ResidualMomentumClass:
        policy = self.policy
        if residual_score <= policy.positive_residual_floor:
            if sector_score > 0:
                return ResidualMomentumClass.SECTOR_BETA_DOMINANT
            return ResidualMomentumClass.NEGATIVE_RESIDUAL
        if positive_horizons == 3 and sector_percentile >= policy.leader_percentile:
            return ResidualMomentumClass.STOCK_SPECIFIC_LEADER
        if sector_percentile >= policy.confirmation_percentile:
            return ResidualMomentumClass.POSITIVE_RESIDUAL
        return ResidualMomentumClass.MIXED
