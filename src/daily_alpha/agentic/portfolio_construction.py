"""Institutional portfolio-construction contracts and deterministic V1 allocator.

Portfolio construction answers whether an investment intent is a good use of the next
unit of portfolio risk. It consumes CIO decisions plus point-in-time risk/portfolio data,
then proposes target weights. It cannot authorize capital, override the independent Risk
Governor, place orders, or enable live trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .cio_fusion import CIOInvestmentDecision, InvestmentAction
from .contracts import ReadinessStatus


class PortfolioConstructionError(ValueError):
    """Portfolio construction input, optimization, or authority invariant failed."""


class AllocationDirection(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    UNCHANGED = "UNCHANGED"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioConstructionError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PortfolioConstructionError("PORTFOLIO_VALUE_NOT_CANONICAL_JSON") from exc


def _normalize_map(
    values: tuple[tuple[str, float], ...] | dict[str, float],
) -> tuple[tuple[str, float], ...]:
    items = values.items() if isinstance(values, dict) else values
    normalized = tuple(sorted((str(key).strip().upper(), float(value)) for key, value in items))
    if any(not key for key, _ in normalized):
        raise PortfolioConstructionError("PORTFOLIO_MAP_KEY_REQUIRED")
    if len({key for key, _ in normalized}) != len(normalized):
        raise PortfolioConstructionError("PORTFOLIO_MAP_KEYS_MUST_BE_UNIQUE")
    if any(not math.isfinite(value) for _, value in normalized):
        raise PortfolioConstructionError("PORTFOLIO_MAP_VALUE_MUST_BE_FINITE")
    return normalized


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PortfolioPosition:
    security_id: str
    weight: float
    sector: str
    annualized_volatility: float
    factor_exposures: tuple[tuple[str, float], ...] | dict[str, float] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        sector = self.sector.strip().upper() or "UNKNOWN"
        if not security_id:
            raise PortfolioConstructionError("POSITION_SECURITY_ID_REQUIRED")
        if not math.isfinite(self.weight) or not 0.0 <= self.weight <= 1.0:
            raise PortfolioConstructionError("POSITION_WEIGHT_OUT_OF_RANGE")
        if not math.isfinite(self.annualized_volatility) or self.annualized_volatility < 0.0:
            raise PortfolioConstructionError("POSITION_VOLATILITY_INVALID")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "factor_exposures", _normalize_map(self.factor_exposures))

    @property
    def factor_map(self) -> dict[str, float]:
        return dict(self.factor_exposures)


@dataclass(frozen=True)
class PortfolioSnapshot:
    as_of: datetime
    nav: float
    cash_weight: float
    positions: tuple[PortfolioPosition, ...]
    source_id: str
    research_only: bool = True
    capital_allocation_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "PORTFOLIO_AS_OF")
        source_id = self.source_id.strip().lower()
        if not math.isfinite(self.nav) or self.nav <= 0:
            raise PortfolioConstructionError("PORTFOLIO_NAV_MUST_BE_POSITIVE")
        if not math.isfinite(self.cash_weight) or not 0.0 <= self.cash_weight <= 1.0:
            raise PortfolioConstructionError("PORTFOLIO_CASH_WEIGHT_OUT_OF_RANGE")
        if not source_id:
            raise PortfolioConstructionError("PORTFOLIO_SOURCE_ID_REQUIRED")
        if (
            not self.research_only
            or self.capital_allocation_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise PortfolioConstructionError("PORTFOLIO_SNAPSHOT_MUST_REMAIN_RESEARCH_ONLY")
        security_ids = [item.security_id for item in self.positions]
        if len(set(security_ids)) != len(security_ids):
            raise PortfolioConstructionError("PORTFOLIO_POSITION_SECURITY_DUPLICATE")
        total = self.cash_weight + sum(item.weight for item in self.positions)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-8):
            raise PortfolioConstructionError(f"PORTFOLIO_WEIGHTS_MUST_SUM_TO_ONE:{total}")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "positions", tuple(sorted(self.positions, key=lambda item: item.security_id)))

    @property
    def position_map(self) -> dict[str, PortfolioPosition]:
        return {item.security_id: item for item in self.positions}

    @property
    def snapshot_id(self) -> str:
        payload = {
            "as_of": self.as_of.isoformat(),
            "nav": self.nav,
            "cash_weight": self.cash_weight,
            "source_id": self.source_id,
            "positions": [
                {
                    "security_id": item.security_id,
                    "weight": item.weight,
                    "sector": item.sector,
                    "annualized_volatility": item.annualized_volatility,
                    "factor_exposures": list(item.factor_exposures),
                }
                for item in self.positions
            ],
            "research_only": self.research_only,
            "capital_allocation_authorized": self.capital_allocation_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return _hash_payload(payload)


@dataclass(frozen=True)
class OpportunityEstimate:
    """Portfolio-construction estimate bound to one CIO investment intent."""

    security_id: str
    as_of: datetime
    cio_decision_id: str
    cio_action: InvestmentAction
    expected_return_bps: float
    annualized_volatility: float
    confidence: float
    sector: str
    liquidity_capacity_weight: float
    factor_exposures: tuple[tuple[str, float], ...] | dict[str, float] = field(default_factory=tuple)
    forecast_model_id: str = "UNSPECIFIED"
    forecast_model_version: str = "UNSPECIFIED"
    research_only: bool = True
    capital_allocation_authorized: bool = False
    execution_authorized: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        decision_id = self.cio_decision_id.strip().lower()
        sector = self.sector.strip().upper() or "UNKNOWN"
        model_id = self.forecast_model_id.strip().upper()
        model_version = self.forecast_model_version.strip()
        boundary = _aware_utc(self.as_of, "OPPORTUNITY_AS_OF")
        if not security_id or not decision_id:
            raise PortfolioConstructionError("OPPORTUNITY_IDENTITY_REQUIRED")
        if not math.isfinite(self.expected_return_bps):
            raise PortfolioConstructionError("OPPORTUNITY_EXPECTED_RETURN_INVALID")
        if not math.isfinite(self.annualized_volatility) or self.annualized_volatility < 0.0:
            raise PortfolioConstructionError("OPPORTUNITY_VOLATILITY_INVALID")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise PortfolioConstructionError("OPPORTUNITY_CONFIDENCE_OUT_OF_RANGE")
        if (
            not math.isfinite(self.liquidity_capacity_weight)
            or not 0.0 <= self.liquidity_capacity_weight <= 1.0
        ):
            raise PortfolioConstructionError("OPPORTUNITY_CAPACITY_WEIGHT_OUT_OF_RANGE")
        if not model_id or not model_version:
            raise PortfolioConstructionError("OPPORTUNITY_FORECAST_MODEL_REQUIRED")
        if not self.research_only or self.capital_allocation_authorized or self.execution_authorized:
            raise PortfolioConstructionError("OPPORTUNITY_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "cio_decision_id", decision_id)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "forecast_model_id", model_id)
        object.__setattr__(self, "forecast_model_version", model_version)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "factor_exposures", _normalize_map(self.factor_exposures))

    @property
    def factor_map(self) -> dict[str, float]:
        return dict(self.factor_exposures)

    @property
    def effective_expected_return(self) -> float:
        return (self.expected_return_bps / 10_000.0) * self.confidence

    @property
    def estimate_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "as_of": self.as_of.isoformat(),
            "cio_decision_id": self.cio_decision_id,
            "cio_action": self.cio_action.value,
            "expected_return_bps": self.expected_return_bps,
            "annualized_volatility": self.annualized_volatility,
            "confidence": self.confidence,
            "sector": self.sector,
            "liquidity_capacity_weight": self.liquidity_capacity_weight,
            "factor_exposures": list(self.factor_exposures),
            "forecast_model_id": self.forecast_model_id,
            "forecast_model_version": self.forecast_model_version,
            "research_only": self.research_only,
            "capital_allocation_authorized": self.capital_allocation_authorized,
            "execution_authorized": self.execution_authorized,
        }
        return _hash_payload(payload)


@dataclass(frozen=True)
class CorrelationSurface:
    as_of: datetime
    security_ids: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    source_id: str
    model_version: str
    research_only: bool = True
    risk_authorized: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "CORRELATION_AS_OF")
        ids = tuple(item.strip().upper() for item in self.security_ids)
        source_id = self.source_id.strip().lower()
        version = self.model_version.strip()
        if not ids or len(set(ids)) != len(ids):
            raise PortfolioConstructionError("CORRELATION_SECURITY_IDS_INVALID")
        if not source_id or not version:
            raise PortfolioConstructionError("CORRELATION_SOURCE_AND_VERSION_REQUIRED")
        if not self.research_only or self.risk_authorized:
            raise PortfolioConstructionError("CORRELATION_SURFACE_MUST_REMAIN_RESEARCH_ONLY")
        size = len(ids)
        if len(self.matrix) != size or any(len(row) != size for row in self.matrix):
            raise PortfolioConstructionError("CORRELATION_MATRIX_DIMENSION_MISMATCH")
        normalized = tuple(tuple(float(value) for value in row) for row in self.matrix)
        for i, row in enumerate(normalized):
            for j, value in enumerate(row):
                if not math.isfinite(value) or not -1.0 <= value <= 1.0:
                    raise PortfolioConstructionError("CORRELATION_VALUE_OUT_OF_RANGE")
                if i == j and not math.isclose(value, 1.0, abs_tol=1e-10):
                    raise PortfolioConstructionError("CORRELATION_DIAGONAL_MUST_EQUAL_ONE")
                if not math.isclose(value, normalized[j][i], rel_tol=0.0, abs_tol=1e-10):
                    raise PortfolioConstructionError("CORRELATION_MATRIX_NOT_SYMMETRIC")
        if not _is_positive_semidefinite(normalized):
            raise PortfolioConstructionError("CORRELATION_MATRIX_NOT_POSITIVE_SEMIDEFINITE")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "security_ids", ids)
        object.__setattr__(self, "matrix", normalized)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "model_version", version)

    @property
    def index(self) -> dict[str, int]:
        return {security_id: index for index, security_id in enumerate(self.security_ids)}

    def correlation(self, left: str, right: str) -> float:
        index = self.index
        try:
            return self.matrix[index[left.strip().upper()]][index[right.strip().upper()]]
        except KeyError as exc:
            raise PortfolioConstructionError(f"CORRELATION_SECURITY_MISSING:{exc.args[0]}") from exc

    @property
    def surface_id(self) -> str:
        return _hash_payload(
            {
                "as_of": self.as_of.isoformat(),
                "security_ids": list(self.security_ids),
                "matrix": [list(row) for row in self.matrix],
                "source_id": self.source_id,
                "model_version": self.model_version,
                "research_only": self.research_only,
                "risk_authorized": self.risk_authorized,
            }
        )


def _is_positive_semidefinite(matrix: tuple[tuple[float, ...], ...], tolerance: float = 1e-10) -> bool:
    """LDL-style PSD check that permits singular covariance/correlation surfaces."""
    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    diagonal = [0.0] * size
    for i in range(size):
        for j in range(i):
            value = matrix[i][j]
            for k in range(j):
                value -= lower[i][k] * diagonal[k] * lower[j][k]
            if abs(diagonal[j]) <= tolerance:
                if abs(value) > tolerance:
                    return False
                lower[i][j] = 0.0
            else:
                lower[i][j] = value / diagonal[j]
        value = matrix[i][i]
        for k in range(i):
            value -= lower[i][k] * lower[i][k] * diagonal[k]
        if value < -tolerance:
            return False
        diagonal[i] = max(0.0, value)
        lower[i][i] = 1.0
    return True


@dataclass(frozen=True)
class FactorLimit:
    factor: str
    max_abs_exposure: float

    def __post_init__(self) -> None:
        factor = self.factor.strip().upper()
        if not factor:
            raise PortfolioConstructionError("FACTOR_LIMIT_NAME_REQUIRED")
        if not math.isfinite(self.max_abs_exposure) or self.max_abs_exposure <= 0:
            raise PortfolioConstructionError("FACTOR_LIMIT_INVALID")
        object.__setattr__(self, "factor", factor)


@dataclass(frozen=True)
class PortfolioConstructionPolicy:
    version: str = "PORTFOLIO_CONSTRUCTION_V1"
    risk_aversion: float = 3.0
    turnover_penalty: float = 0.0025
    concentration_penalty: float = 0.001
    max_position_weight: float = 0.10
    max_sector_weight: float = 0.30
    min_cash_weight: float = 0.05
    max_turnover: float = 0.25
    max_single_step_weight: float = 0.02
    trim_min_fraction: float = 0.25
    factor_limits: tuple[FactorLimit, ...] = ()

    def __post_init__(self) -> None:
        version = self.version.strip()
        if not version:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_VERSION_REQUIRED")
        positive_fields = (
            self.risk_aversion,
            self.max_position_weight,
            self.max_sector_weight,
            self.max_turnover,
            self.max_single_step_weight,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive_fields):
            raise PortfolioConstructionError("PORTFOLIO_POLICY_POSITIVE_FIELD_INVALID")
        if not 0.0 <= self.min_cash_weight < 1.0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_MIN_CASH_INVALID")
        if not 0.0 < self.max_position_weight <= 1.0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_MAX_POSITION_INVALID")
        if not 0.0 < self.max_sector_weight <= 1.0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_MAX_SECTOR_INVALID")
        if not 0.0 < self.max_turnover <= 2.0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_MAX_TURNOVER_INVALID")
        if not 0.0 < self.max_single_step_weight <= 1.0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_STEP_INVALID")
        if not 0.0 < self.trim_min_fraction <= 1.0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_TRIM_FRACTION_INVALID")
        if self.turnover_penalty < 0 or self.concentration_penalty < 0:
            raise PortfolioConstructionError("PORTFOLIO_POLICY_PENALTY_INVALID")
        factors = tuple(sorted(self.factor_limits, key=lambda item: item.factor))
        if len({item.factor for item in factors}) != len(factors):
            raise PortfolioConstructionError("PORTFOLIO_POLICY_FACTOR_DUPLICATE")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "factor_limits", factors)

    @property
    def policy_id(self) -> str:
        return _hash_payload(
            {
                "version": self.version,
                "risk_aversion": self.risk_aversion,
                "turnover_penalty": self.turnover_penalty,
                "concentration_penalty": self.concentration_penalty,
                "max_position_weight": self.max_position_weight,
                "max_sector_weight": self.max_sector_weight,
                "min_cash_weight": self.min_cash_weight,
                "max_turnover": self.max_turnover,
                "max_single_step_weight": self.max_single_step_weight,
                "trim_min_fraction": self.trim_min_fraction,
                "factor_limits": [
                    {"factor": item.factor, "max_abs_exposure": item.max_abs_exposure}
                    for item in self.factor_limits
                ],
            }
        )


@dataclass(frozen=True)
class MarginalPortfolioAssessment:
    security_id: str
    action: InvestmentAction
    current_weight: float
    proposed_delta_weight: float
    proposed_weight: float
    expected_return_contribution_bps: float
    portfolio_volatility_before: float
    portfolio_volatility_after: float
    marginal_variance: float
    weighted_correlation_to_portfolio: float
    sector_weight_after: float
    marginal_utility_bps: float
    status: ReadinessStatus
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def assessment_id(self) -> str:
        return _hash_payload(
            {
                "security_id": self.security_id,
                "action": self.action.value,
                "current_weight": self.current_weight,
                "proposed_delta_weight": self.proposed_delta_weight,
                "proposed_weight": self.proposed_weight,
                "expected_return_contribution_bps": self.expected_return_contribution_bps,
                "portfolio_volatility_before": self.portfolio_volatility_before,
                "portfolio_volatility_after": self.portfolio_volatility_after,
                "marginal_variance": self.marginal_variance,
                "weighted_correlation_to_portfolio": self.weighted_correlation_to_portfolio,
                "sector_weight_after": self.sector_weight_after,
                "marginal_utility_bps": self.marginal_utility_bps,
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
            }
        )


@dataclass(frozen=True, order=True)
class TargetAllocation:
    security_id: str
    current_weight: float
    target_weight: float
    delta_weight: float
    direction: AllocationDirection
    cio_decision_id: str | None


@dataclass(frozen=True)
class PortfolioAllocationProposal:
    as_of: datetime
    portfolio_snapshot_id: str
    correlation_surface_id: str
    policy_id: str
    target_allocations: tuple[TargetAllocation, ...]
    target_cash_weight: float
    estimated_portfolio_volatility: float
    estimated_turnover: float
    objective_utility_bps: float
    selected_assessments: tuple[MarginalPortfolioAssessment, ...]
    excluded_opportunity_ids: tuple[str, ...]
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    capital_allocation_authorized: bool = False
    risk_governor_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "ALLOCATION_PROPOSAL_AS_OF")
        if (
            not self.research_only
            or self.capital_allocation_authorized
            or self.risk_governor_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise PortfolioConstructionError("ALLOCATION_PROPOSAL_MUST_REMAIN_BELOW_RISK_GOVERNOR")
        if not 0.0 <= self.target_cash_weight <= 1.0:
            raise PortfolioConstructionError("ALLOCATION_TARGET_CASH_OUT_OF_RANGE")
        total = self.target_cash_weight + sum(item.target_weight for item in self.target_allocations)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-8):
            raise PortfolioConstructionError(f"ALLOCATION_TARGET_WEIGHTS_MUST_SUM_TO_ONE:{total}")
        if self.status is ReadinessStatus.BLOCKED and not self.blockers:
            raise PortfolioConstructionError("BLOCKED_ALLOCATION_REQUIRES_BLOCKER")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "target_allocations",
            tuple(sorted(self.target_allocations, key=lambda item: item.security_id)),
        )
        object.__setattr__(
            self,
            "selected_assessments",
            tuple(sorted(self.selected_assessments, key=lambda item: item.assessment_id)),
        )
        object.__setattr__(self, "excluded_opportunity_ids", tuple(sorted(set(self.excluded_opportunity_ids))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def proposal_id(self) -> str:
        return _hash_payload(
            {
                "as_of": self.as_of.isoformat(),
                "portfolio_snapshot_id": self.portfolio_snapshot_id,
                "correlation_surface_id": self.correlation_surface_id,
                "policy_id": self.policy_id,
                "target_allocations": [
                    {
                        "security_id": item.security_id,
                        "current_weight": item.current_weight,
                        "target_weight": item.target_weight,
                        "delta_weight": item.delta_weight,
                        "direction": item.direction.value,
                        "cio_decision_id": item.cio_decision_id,
                    }
                    for item in self.target_allocations
                ],
                "target_cash_weight": self.target_cash_weight,
                "estimated_portfolio_volatility": self.estimated_portfolio_volatility,
                "estimated_turnover": self.estimated_turnover,
                "objective_utility_bps": self.objective_utility_bps,
                "selected_assessment_ids": [item.assessment_id for item in self.selected_assessments],
                "excluded_opportunity_ids": list(self.excluded_opportunity_ids),
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "research_only": self.research_only,
                "capital_allocation_authorized": self.capital_allocation_authorized,
                "risk_governor_authorized": self.risk_governor_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


class MarginalPortfolioConstructor:
    """Deterministic reference allocator using marginal portfolio utility.

    This is deliberately a transparent V1 reference engine, not a claim of final optimizer
    sophistication. A future convex/QP optimizer can implement the same contracts and be
    compared under the model-governance framework.
    """

    def __init__(self, policy: PortfolioConstructionPolicy | None = None) -> None:
        self.policy = policy or PortfolioConstructionPolicy()

    def propose(
        self,
        *,
        portfolio: PortfolioSnapshot,
        cio_decisions: tuple[CIOInvestmentDecision, ...],
        opportunities: tuple[OpportunityEstimate, ...],
        correlations: CorrelationSurface,
        max_iterations: int = 200,
    ) -> PortfolioAllocationProposal:
        if max_iterations <= 0:
            raise PortfolioConstructionError("PORTFOLIO_MAX_ITERATIONS_MUST_BE_POSITIVE")
        boundary = portfolio.as_of
        if correlations.as_of > boundary:
            raise PortfolioConstructionError("FUTURE_CORRELATION_SURFACE_NOT_ALLOWED")
        decision_map = self._validate_inputs(portfolio, cio_decisions, opportunities)
        opportunity_map = {item.security_id: item for item in opportunities}
        weights = {item.security_id: item.weight for item in portfolio.positions}
        sectors = {item.security_id: item.sector for item in portfolio.positions}
        vols = {item.security_id: item.annualized_volatility for item in portfolio.positions}
        factors = {item.security_id: item.factor_map for item in portfolio.positions}
        cash = portfolio.cash_weight
        turnover = 0.0
        selected: list[MarginalPortfolioAssessment] = []
        excluded: set[str] = set()
        warnings: list[str] = []
        blockers: list[str] = []

        needed_ids = set(weights) | set(opportunity_map)
        missing_corr = sorted(needed_ids - set(correlations.security_ids))
        if len(needed_ids) > 1 and missing_corr:
            blockers.extend(f"CORRELATION_SECURITY_MISSING:{item}" for item in missing_corr)
            return self._blocked_proposal(
                portfolio=portfolio,
                correlations=correlations,
                weights=weights,
                cash=cash,
                blockers=blockers,
                opportunities=opportunities,
            )

        # Respect explicit SELL/TRIM investment intents before considering new risk.
        for security_id in sorted(opportunity_map):
            opportunity = opportunity_map[security_id]
            current = weights.get(security_id, 0.0)
            if opportunity.cio_action is InvestmentAction.SELL and current > 0:
                reduction = current
                weights[security_id] = 0.0
                cash += reduction
                turnover += reduction
            elif opportunity.cio_action is InvestmentAction.TRIM and current > 0:
                minimum_reduction = min(
                    current,
                    max(
                        self.policy.max_single_step_weight,
                        current * self.policy.trim_min_fraction,
                    ),
                )
                weights[security_id] = current - minimum_reduction
                cash += minimum_reduction
                turnover += minimum_reduction
            elif opportunity.cio_action is InvestmentAction.HEDGE:
                warnings.append(f"HEDGE_SLEEVE_NOT_IMPLEMENTED_IN_LONG_ONLY_V1:{security_id}")
                excluded.add(opportunity.estimate_id)

        if turnover > self.policy.max_turnover + 1e-12:
            blockers.append("MANDATORY_RISK_REDUCTION_EXCEEDS_TURNOVER_POLICY")
            return self._blocked_proposal(
                portfolio=portfolio,
                correlations=correlations,
                weights=weights,
                cash=cash,
                blockers=blockers,
                opportunities=opportunities,
                warnings=warnings,
                turnover=turnover,
            )

        for opportunity in opportunities:
            sectors.setdefault(opportunity.security_id, opportunity.sector)
            vols[opportunity.security_id] = opportunity.annualized_volatility
            factors[opportunity.security_id] = opportunity.factor_map

        iterations = 0
        while iterations < max_iterations:
            iterations += 1
            assessments: list[MarginalPortfolioAssessment] = []
            for security_id in sorted(opportunity_map):
                opportunity = opportunity_map[security_id]
                if opportunity.cio_action not in {InvestmentAction.BUY, InvestmentAction.ADD}:
                    continue
                assessment = self._assess_increase(
                    opportunity=opportunity,
                    weights=weights,
                    cash=cash,
                    turnover=turnover,
                    sectors=sectors,
                    vols=vols,
                    factors=factors,
                    correlations=correlations,
                )
                assessments.append(assessment)
            eligible = [
                item
                for item in assessments
                if item.status is not ReadinessStatus.BLOCKED
                and item.proposed_delta_weight > 1e-12
                and item.marginal_utility_bps > 0.0
            ]
            if not eligible:
                for opportunity in opportunities:
                    if opportunity.cio_action in {InvestmentAction.BUY, InvestmentAction.ADD}:
                        if weights.get(opportunity.security_id, 0.0) <= portfolio.position_map.get(
                            opportunity.security_id,
                            PortfolioPosition(
                                security_id=opportunity.security_id,
                                weight=0.0,
                                sector=opportunity.sector,
                                annualized_volatility=opportunity.annualized_volatility,
                            ),
                        ).weight + 1e-12:
                            excluded.add(opportunity.estimate_id)
                break
            best = max(eligible, key=lambda item: (item.marginal_utility_bps, item.security_id))
            weights[best.security_id] = best.proposed_weight
            cash -= best.proposed_delta_weight
            turnover += abs(best.proposed_delta_weight)
            selected.append(best)

        if iterations >= max_iterations:
            warnings.append("PORTFOLIO_CONSTRUCTION_MAX_ITERATIONS_REACHED")

        weights = {security_id: weight for security_id, weight in weights.items() if weight > 1e-12}
        portfolio_vol = self._portfolio_volatility(weights, vols, correlations)
        objective = self._portfolio_utility(weights, opportunity_map, vols, correlations, turnover)
        allocations = self._target_allocations(
            portfolio=portfolio,
            weights=weights,
            decision_map=decision_map,
        )
        status = ReadinessStatus.WARNING if warnings else ReadinessStatus.PASS
        if not selected and not any(
            item.cio_action in {InvestmentAction.SELL, InvestmentAction.TRIM}
            for item in opportunities
        ):
            warnings.append("NO_POSITIVE_MARGINAL_RISK_ALLOCATION_SELECTED")
            status = ReadinessStatus.WARNING
        return PortfolioAllocationProposal(
            as_of=boundary,
            portfolio_snapshot_id=portfolio.snapshot_id,
            correlation_surface_id=correlations.surface_id,
            policy_id=self.policy.policy_id,
            target_allocations=allocations,
            target_cash_weight=cash,
            estimated_portfolio_volatility=portfolio_vol,
            estimated_turnover=turnover,
            objective_utility_bps=objective * 10_000.0,
            selected_assessments=tuple(selected),
            excluded_opportunity_ids=tuple(excluded),
            status=status,
            blockers=(),
            warnings=tuple(warnings),
        )

    def _validate_inputs(
        self,
        portfolio: PortfolioSnapshot,
        decisions: tuple[CIOInvestmentDecision, ...],
        opportunities: tuple[OpportunityEstimate, ...],
    ) -> dict[str, CIOInvestmentDecision]:
        decision_map: dict[str, CIOInvestmentDecision] = {}
        for decision in decisions:
            if decision.as_of != portfolio.as_of:
                raise PortfolioConstructionError("CIO_DECISION_PORTFOLIO_TIME_MISMATCH")
            if decision.security_id in decision_map:
                raise PortfolioConstructionError(f"DUPLICATE_CIO_DECISION:{decision.security_id}")
            decision_map[decision.security_id] = decision
        seen: set[str] = set()
        for opportunity in opportunities:
            if opportunity.security_id in seen:
                raise PortfolioConstructionError(f"DUPLICATE_OPPORTUNITY:{opportunity.security_id}")
            seen.add(opportunity.security_id)
            if opportunity.as_of != portfolio.as_of:
                raise PortfolioConstructionError("OPPORTUNITY_PORTFOLIO_TIME_MISMATCH")
            decision = decision_map.get(opportunity.security_id)
            if decision is None:
                raise PortfolioConstructionError(
                    f"OPPORTUNITY_CIO_DECISION_MISSING:{opportunity.security_id}"
                )
            if opportunity.cio_decision_id != decision.decision_id:
                raise PortfolioConstructionError("OPPORTUNITY_CIO_DECISION_LINEAGE_MISMATCH")
            if opportunity.cio_action is not decision.action:
                raise PortfolioConstructionError("OPPORTUNITY_CIO_ACTION_MISMATCH")
        return decision_map

    def _assess_increase(
        self,
        *,
        opportunity: OpportunityEstimate,
        weights: dict[str, float],
        cash: float,
        turnover: float,
        sectors: dict[str, str],
        vols: dict[str, float],
        factors: dict[str, dict[str, float]],
        correlations: CorrelationSurface,
    ) -> MarginalPortfolioAssessment:
        current = weights.get(opportunity.security_id, 0.0)
        blockers: list[str] = []
        warnings: list[str] = []
        available_cash = max(0.0, cash - self.policy.min_cash_weight)
        turnover_left = max(0.0, self.policy.max_turnover - turnover)
        position_headroom = max(0.0, self.policy.max_position_weight - current)
        capacity_headroom = max(0.0, opportunity.liquidity_capacity_weight - current)
        sector_current = sum(
            weight
            for security_id, weight in weights.items()
            if sectors.get(security_id, "UNKNOWN") == opportunity.sector
        )
        sector_headroom = max(0.0, self.policy.max_sector_weight - sector_current)
        step = min(
            self.policy.max_single_step_weight,
            available_cash,
            turnover_left,
            position_headroom,
            capacity_headroom,
            sector_headroom,
        )
        step = min(step, self._factor_headroom(opportunity, weights, factors))
        if step <= 1e-12:
            blockers.append("NO_PORTFOLIO_CONSTRUCTION_HEADROOM")
        before_variance = self._portfolio_variance(weights, vols, correlations)
        before_vol = math.sqrt(max(0.0, before_variance))
        after_weights = dict(weights)
        if step > 0:
            after_weights[opportunity.security_id] = current + step
        after_variance = self._portfolio_variance(after_weights, vols, correlations)
        after_vol = math.sqrt(max(0.0, after_variance))
        marginal_variance = after_variance - before_variance
        weighted_corr = self._weighted_correlation(
            opportunity.security_id,
            weights,
            correlations,
        )
        expected_contribution = opportunity.effective_expected_return * step
        concentration_delta = (
            sum(weight * weight for weight in after_weights.values())
            - sum(weight * weight for weight in weights.values())
        )
        utility = (
            expected_contribution
            - self.policy.risk_aversion * marginal_variance
            - self.policy.turnover_penalty * step
            - self.policy.concentration_penalty * concentration_delta
        )
        if weighted_corr > 0.8:
            warnings.append("HIGH_CORRELATION_TO_EXISTING_PORTFOLIO")
        status = (
            ReadinessStatus.BLOCKED
            if blockers
            else ReadinessStatus.WARNING
            if warnings
            else ReadinessStatus.PASS
        )
        return MarginalPortfolioAssessment(
            security_id=opportunity.security_id,
            action=opportunity.cio_action,
            current_weight=current,
            proposed_delta_weight=step,
            proposed_weight=current + step,
            expected_return_contribution_bps=expected_contribution * 10_000.0,
            portfolio_volatility_before=before_vol,
            portfolio_volatility_after=after_vol,
            marginal_variance=marginal_variance,
            weighted_correlation_to_portfolio=weighted_corr,
            sector_weight_after=sector_current + step,
            marginal_utility_bps=utility * 10_000.0,
            status=status,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _factor_headroom(
        self,
        opportunity: OpportunityEstimate,
        weights: dict[str, float],
        factors: dict[str, dict[str, float]],
    ) -> float:
        headroom = 1.0
        candidate_factors = opportunity.factor_map
        for limit in self.policy.factor_limits:
            loading = candidate_factors.get(limit.factor, 0.0)
            if abs(loading) <= 1e-15:
                continue
            current = sum(
                weight * factors.get(security_id, {}).get(limit.factor, 0.0)
                for security_id, weight in weights.items()
            )
            if abs(current) > limit.max_abs_exposure + 1e-10:
                return 0.0
            if loading > 0:
                allowed = (limit.max_abs_exposure - current) / loading
            else:
                allowed = (-limit.max_abs_exposure - current) / loading
            headroom = min(headroom, max(0.0, allowed))
        return max(0.0, headroom)

    def _portfolio_variance(
        self,
        weights: dict[str, float],
        vols: dict[str, float],
        correlations: CorrelationSurface,
    ) -> float:
        active = sorted(security_id for security_id, weight in weights.items() if weight > 1e-15)
        if not active:
            return 0.0
        variance = 0.0
        for left in active:
            if left not in correlations.index:
                raise PortfolioConstructionError(f"CORRELATION_SECURITY_MISSING:{left}")
            for right in active:
                if right not in correlations.index:
                    raise PortfolioConstructionError(f"CORRELATION_SECURITY_MISSING:{right}")
                variance += (
                    weights[left]
                    * weights[right]
                    * vols.get(left, 0.0)
                    * vols.get(right, 0.0)
                    * correlations.correlation(left, right)
                )
        return max(0.0, variance)

    def _portfolio_volatility(
        self,
        weights: dict[str, float],
        vols: dict[str, float],
        correlations: CorrelationSurface,
    ) -> float:
        return math.sqrt(self._portfolio_variance(weights, vols, correlations))

    def _weighted_correlation(
        self,
        candidate: str,
        weights: dict[str, float],
        correlations: CorrelationSurface,
    ) -> float:
        denominator = sum(
            weight
            for security_id, weight in weights.items()
            if security_id != candidate and weight > 1e-15
        )
        if denominator <= 1e-15:
            return 0.0
        numerator = sum(
            weight * correlations.correlation(candidate, security_id)
            for security_id, weight in weights.items()
            if security_id != candidate and weight > 1e-15
        )
        return numerator / denominator

    def _portfolio_utility(
        self,
        weights: dict[str, float],
        opportunities: dict[str, OpportunityEstimate],
        vols: dict[str, float],
        correlations: CorrelationSurface,
        turnover: float,
    ) -> float:
        expected_return = sum(
            weight * opportunities[security_id].effective_expected_return
            for security_id, weight in weights.items()
            if security_id in opportunities
        )
        variance = self._portfolio_variance(weights, vols, correlations)
        concentration = sum(weight * weight for weight in weights.values())
        return (
            expected_return
            - self.policy.risk_aversion * variance
            - self.policy.turnover_penalty * turnover
            - self.policy.concentration_penalty * concentration
        )

    def _target_allocations(
        self,
        *,
        portfolio: PortfolioSnapshot,
        weights: dict[str, float],
        decision_map: dict[str, CIOInvestmentDecision],
    ) -> tuple[TargetAllocation, ...]:
        current = {item.security_id: item.weight for item in portfolio.positions}
        security_ids = sorted(set(current) | set(weights))
        allocations: list[TargetAllocation] = []
        for security_id in security_ids:
            before = current.get(security_id, 0.0)
            target = weights.get(security_id, 0.0)
            delta = target - before
            direction = (
                AllocationDirection.INCREASE
                if delta > 1e-12
                else AllocationDirection.DECREASE
                if delta < -1e-12
                else AllocationDirection.UNCHANGED
            )
            decision = decision_map.get(security_id)
            allocations.append(
                TargetAllocation(
                    security_id=security_id,
                    current_weight=before,
                    target_weight=target,
                    delta_weight=delta,
                    direction=direction,
                    cio_decision_id=decision.decision_id if decision else None,
                )
            )
        return tuple(allocations)

    def _blocked_proposal(
        self,
        *,
        portfolio: PortfolioSnapshot,
        correlations: CorrelationSurface,
        weights: dict[str, float],
        cash: float,
        blockers: list[str],
        opportunities: tuple[OpportunityEstimate, ...],
        warnings: list[str] | None = None,
        turnover: float = 0.0,
    ) -> PortfolioAllocationProposal:
        allocations = tuple(
            TargetAllocation(
                security_id=item.security_id,
                current_weight=item.weight,
                target_weight=weights.get(item.security_id, item.weight),
                delta_weight=weights.get(item.security_id, item.weight) - item.weight,
                direction=(
                    AllocationDirection.DECREASE
                    if weights.get(item.security_id, item.weight) < item.weight
                    else AllocationDirection.UNCHANGED
                ),
                cio_decision_id=None,
            )
            for item in portfolio.positions
            if weights.get(item.security_id, item.weight) > 1e-12
        )
        return PortfolioAllocationProposal(
            as_of=portfolio.as_of,
            portfolio_snapshot_id=portfolio.snapshot_id,
            correlation_surface_id=correlations.surface_id,
            policy_id=self.policy.policy_id,
            target_allocations=allocations,
            target_cash_weight=cash,
            estimated_portfolio_volatility=0.0,
            estimated_turnover=turnover,
            objective_utility_bps=0.0,
            selected_assessments=(),
            excluded_opportunity_ids=tuple(item.estimate_id for item in opportunities),
            status=ReadinessStatus.BLOCKED,
            blockers=tuple(blockers),
            warnings=tuple(warnings or ()),
        )
