"""Independent deterministic Risk Governor for Daily Alpha.

The Risk Governor is a hard capital-protection veto above CIO/Fusion and Portfolio
Construction. It evaluates governed allocation proposals using deterministic limits and
cannot be overridden by an AI agent. Risk approval is not execution or live authorization.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus
from .portfolio_construction import PortfolioAllocationProposal, PortfolioSnapshot, TargetAllocation


class RiskGovernorError(ValueError):
    """Risk-governor contract or evaluation invariant failed."""


class RiskVerdict(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RiskGovernorError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise RiskGovernorError("RISK_VALUE_NOT_CANONICAL_JSON") from exc


def _hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_float_map(
    values: tuple[tuple[str, float], ...] | dict[str, float],
) -> tuple[tuple[str, float], ...]:
    items = values.items() if isinstance(values, dict) else values
    normalized = tuple(sorted((str(key).strip().upper(), float(value)) for key, value in items))
    if any(not key or not math.isfinite(value) for key, value in normalized):
        raise RiskGovernorError("RISK_FLOAT_MAP_INVALID")
    if len({key for key, _ in normalized}) != len(normalized):
        raise RiskGovernorError("RISK_FLOAT_MAP_KEYS_MUST_BE_UNIQUE")
    return normalized


def _normalize_int_map(
    values: tuple[tuple[str, int], ...] | dict[str, int],
) -> tuple[tuple[str, int], ...]:
    items = values.items() if isinstance(values, dict) else values
    normalized = tuple(sorted((str(key).strip().upper(), int(value)) for key, value in items))
    if any(not key for key, _ in normalized):
        raise RiskGovernorError("RISK_INT_MAP_INVALID")
    if len({key for key, _ in normalized}) != len(normalized):
        raise RiskGovernorError("RISK_INT_MAP_KEYS_MUST_BE_UNIQUE")
    return normalized


def _normalize_str_map(
    values: tuple[tuple[str, str], ...] | dict[str, str],
) -> tuple[tuple[str, str], ...]:
    items = values.items() if isinstance(values, dict) else values
    normalized = tuple(
        sorted((str(key).strip().upper(), str(value).strip().upper()) for key, value in items)
    )
    if any(not key or not value for key, value in normalized):
        raise RiskGovernorError("RISK_STRING_MAP_INVALID")
    if len({key for key, _ in normalized}) != len(normalized):
        raise RiskGovernorError("RISK_STRING_MAP_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True)
class GovernanceLockState:
    as_of: datetime
    emergency_stop: bool
    model_stack_approved: bool
    source_id: str
    research_only: bool = True
    execution_globally_enabled: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "GOVERNANCE_AS_OF")
        source_id = self.source_id.strip().lower()
        if not source_id:
            raise RiskGovernorError("GOVERNANCE_SOURCE_ID_REQUIRED")
        if not self.research_only or self.execution_globally_enabled or self.live_trading_enabled:
            raise RiskGovernorError("GOVERNANCE_STATE_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "source_id", source_id)

    @property
    def governance_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "emergency_stop": self.emergency_stop,
                "model_stack_approved": self.model_stack_approved,
                "source_id": self.source_id,
                "research_only": self.research_only,
                "execution_globally_enabled": self.execution_globally_enabled,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "INSTITUTIONAL_RISK_GOVERNOR_V1"
    max_position_weight: float = 0.10
    max_sector_weight: float = 0.30
    max_cluster_weight: float = 0.35
    min_cash_weight: float = 0.05
    max_gross_exposure: float = 0.95
    max_net_exposure: float = 0.95
    max_portfolio_volatility: float = 0.25
    max_turnover: float = 0.30
    max_drawdown: float = 0.15
    max_liquidity_days_to_exit: float = 5.0
    event_blackout_days: int = 2
    max_context_age_seconds: int = 300

    def __post_init__(self) -> None:
        version = self.version.strip()
        if not version:
            raise RiskGovernorError("RISK_POLICY_VERSION_REQUIRED")
        ratios = (
            self.max_position_weight,
            self.max_sector_weight,
            self.max_cluster_weight,
            self.min_cash_weight,
            self.max_gross_exposure,
            self.max_net_exposure,
            self.max_portfolio_volatility,
            self.max_turnover,
            self.max_drawdown,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in ratios):
            raise RiskGovernorError("RISK_POLICY_RATIO_INVALID")
        if not 0.0 < self.max_position_weight <= 1.0:
            raise RiskGovernorError("RISK_POLICY_MAX_POSITION_INVALID")
        if not 0.0 < self.max_sector_weight <= 1.0:
            raise RiskGovernorError("RISK_POLICY_MAX_SECTOR_INVALID")
        if not 0.0 < self.max_cluster_weight <= 1.0:
            raise RiskGovernorError("RISK_POLICY_MAX_CLUSTER_INVALID")
        if not 0.0 <= self.min_cash_weight < 1.0:
            raise RiskGovernorError("RISK_POLICY_MIN_CASH_INVALID")
        if self.max_gross_exposure > 2.0 or self.max_net_exposure > 2.0:
            raise RiskGovernorError("RISK_POLICY_EXPOSURE_INVALID")
        if self.max_portfolio_volatility <= 0.0 or self.max_drawdown <= 0.0:
            raise RiskGovernorError("RISK_POLICY_VOL_DRAWDOWN_INVALID")
        if self.max_turnover <= 0.0 or self.max_turnover > 2.0:
            raise RiskGovernorError("RISK_POLICY_TURNOVER_INVALID")
        if not math.isfinite(self.max_liquidity_days_to_exit) or self.max_liquidity_days_to_exit <= 0:
            raise RiskGovernorError("RISK_POLICY_LIQUIDITY_INVALID")
        if self.event_blackout_days < 0 or self.max_context_age_seconds <= 0:
            raise RiskGovernorError("RISK_POLICY_TIME_LIMIT_INVALID")
        object.__setattr__(self, "version", version)

    @property
    def policy_id(self) -> str:
        return _hash(self.__dict__)


@dataclass(frozen=True)
class RiskContext:
    as_of: datetime
    observed_at: datetime
    current_drawdown: float
    current_portfolio_volatility: float
    sectors: tuple[tuple[str, str], ...] | dict[str, str]
    correlation_clusters: tuple[tuple[str, str], ...] | dict[str, str]
    liquidity_days_to_exit: tuple[tuple[str, float], ...] | dict[str, float]
    days_to_material_event: tuple[tuple[str, int], ...] | dict[str, int]
    status: ReadinessStatus
    source_id: str
    research_only: bool = True
    execution_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "RISK_CONTEXT_AS_OF")
        observed = _aware_utc(self.observed_at, "RISK_CONTEXT_OBSERVED_AT")
        source_id = self.source_id.strip().lower()
        if observed > boundary:
            raise RiskGovernorError("FUTURE_RISK_CONTEXT_NOT_ALLOWED")
        if not source_id:
            raise RiskGovernorError("RISK_CONTEXT_SOURCE_ID_REQUIRED")
        if not math.isfinite(self.current_drawdown) or not 0.0 <= self.current_drawdown <= 1.0:
            raise RiskGovernorError("RISK_CONTEXT_DRAWDOWN_INVALID")
        if not math.isfinite(self.current_portfolio_volatility) or self.current_portfolio_volatility < 0.0:
            raise RiskGovernorError("RISK_CONTEXT_VOLATILITY_INVALID")
        if not self.research_only or self.execution_authorized or self.live_trading_enabled:
            raise RiskGovernorError("RISK_CONTEXT_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "sectors", _normalize_str_map(self.sectors))
        object.__setattr__(self, "correlation_clusters", _normalize_str_map(self.correlation_clusters))
        object.__setattr__(self, "liquidity_days_to_exit", _normalize_float_map(self.liquidity_days_to_exit))
        object.__setattr__(self, "days_to_material_event", _normalize_int_map(self.days_to_material_event))

    @property
    def sector_map(self) -> dict[str, str]:
        return dict(self.sectors)

    @property
    def cluster_map(self) -> dict[str, str]:
        return dict(self.correlation_clusters)

    @property
    def liquidity_map(self) -> dict[str, float]:
        return dict(self.liquidity_days_to_exit)

    @property
    def event_map(self) -> dict[str, int]:
        return dict(self.days_to_material_event)

    @property
    def context_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "observed_at": self.observed_at.isoformat(),
                "current_drawdown": self.current_drawdown,
                "current_portfolio_volatility": self.current_portfolio_volatility,
                "sectors": list(self.sectors),
                "correlation_clusters": list(self.correlation_clusters),
                "liquidity_days_to_exit": list(self.liquidity_days_to_exit),
                "days_to_material_event": list(self.days_to_material_event),
                "status": self.status.value,
                "source_id": self.source_id,
            }
        )


@dataclass(frozen=True)
class RiskGovernorDecision:
    as_of: datetime
    proposal_id: str
    portfolio_snapshot_id: str
    policy_id: str
    risk_context_id: str
    governance_id: str
    verdict: RiskVerdict
    risk_governor_approved: bool
    reviewed_target_allocations: tuple[TargetAllocation, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    capital_allocation_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "RISK_DECISION_AS_OF")
        if self.risk_governor_approved != (self.verdict is RiskVerdict.APPROVED):
            raise RiskGovernorError("RISK_VERDICT_APPROVAL_MISMATCH")
        if self.verdict is RiskVerdict.REJECTED and not self.blockers:
            raise RiskGovernorError("REJECTED_RISK_DECISION_REQUIRES_BLOCKER")
        if (
            not self.research_only
            or self.capital_allocation_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise RiskGovernorError("RISK_DECISION_CANNOT_AUTHORIZE_EXECUTION_OR_LIVE_CAPITAL")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "reviewed_target_allocations",
            tuple(sorted(self.reviewed_target_allocations, key=lambda item: item.security_id)),
        )
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def decision_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "proposal_id": self.proposal_id,
                "portfolio_snapshot_id": self.portfolio_snapshot_id,
                "policy_id": self.policy_id,
                "risk_context_id": self.risk_context_id,
                "governance_id": self.governance_id,
                "verdict": self.verdict.value,
                "risk_governor_approved": self.risk_governor_approved,
                "reviewed_target_allocations": [
                    {
                        "security_id": item.security_id,
                        "current_weight": item.current_weight,
                        "target_weight": item.target_weight,
                        "delta_weight": item.delta_weight,
                        "direction": item.direction.value,
                        "cio_decision_id": item.cio_decision_id,
                    }
                    for item in self.reviewed_target_allocations
                ],
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "research_only": self.research_only,
                "capital_allocation_authorized": self.capital_allocation_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


class DeterministicRiskGovernor:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        *,
        proposal: PortfolioAllocationProposal,
        portfolio: PortfolioSnapshot,
        context: RiskContext,
        governance: GovernanceLockState,
    ) -> RiskGovernorDecision:
        self._validate_lineage(proposal, portfolio, context, governance)
        blockers: list[str] = []
        warnings: list[str] = []
        age = (proposal.as_of - context.observed_at).total_seconds()
        if age > self.policy.max_context_age_seconds:
            blockers.append("RISK_CONTEXT_STALE")
        if context.status is ReadinessStatus.BLOCKED:
            blockers.append("RISK_CONTEXT_BLOCKED")
        elif context.status is ReadinessStatus.WARNING:
            warnings.append("RISK_CONTEXT_WARNING")
        if governance.emergency_stop:
            blockers.append("GOVERNANCE_EMERGENCY_STOP")
        if not governance.model_stack_approved:
            blockers.append("GOVERNANCE_MODEL_STACK_NOT_APPROVED")
        if proposal.status is ReadinessStatus.BLOCKED:
            blockers.append("PORTFOLIO_PROPOSAL_BLOCKED")

        current = portfolio.position_map
        targets = {item.security_id: item for item in proposal.target_allocations}
        sector_map = context.sector_map
        cluster_map = context.cluster_map
        liquidity_map = context.liquidity_map
        event_map = context.event_map
        has_increase = any(item.delta_weight > 1e-12 for item in proposal.target_allocations)

        for allocation in proposal.target_allocations:
            before = current.get(allocation.security_id).weight if allocation.security_id in current else 0.0
            increasing = allocation.target_weight > before + 1e-12
            if allocation.target_weight > self.policy.max_position_weight + 1e-12:
                if increasing:
                    blockers.append(f"MAX_POSITION_WEIGHT:{allocation.security_id}")
                else:
                    warnings.append(f"POSITION_REMAINS_ABOVE_LIMIT_WHILE_DERISKING:{allocation.security_id}")
            if allocation.target_weight > 1e-12 and allocation.security_id not in sector_map:
                blockers.append(f"RISK_SECTOR_MISSING:{allocation.security_id}")
            if allocation.target_weight > 1e-12 and allocation.security_id not in cluster_map:
                blockers.append(f"RISK_CLUSTER_MISSING:{allocation.security_id}")
            if allocation.target_weight > 1e-12 and allocation.security_id not in liquidity_map:
                blockers.append(f"RISK_LIQUIDITY_MISSING:{allocation.security_id}")
            elif allocation.target_weight > 1e-12:
                days = liquidity_map[allocation.security_id]
                if days > self.policy.max_liquidity_days_to_exit:
                    if increasing:
                        blockers.append(f"LIQUIDITY_DAYS_TO_EXIT:{allocation.security_id}")
                    else:
                        warnings.append(f"ILLIQUID_POSITION_DERISKING:{allocation.security_id}")
            if increasing:
                if allocation.security_id not in event_map:
                    blockers.append(f"MATERIAL_EVENT_DISTANCE_MISSING:{allocation.security_id}")
                elif abs(event_map[allocation.security_id]) <= self.policy.event_blackout_days:
                    blockers.append(f"MATERIAL_EVENT_BLACKOUT:{allocation.security_id}")

        self._check_sector_limits(portfolio, proposal, sector_map, blockers, warnings)
        self._check_cluster_limits(portfolio, proposal, cluster_map, blockers, warnings)

        gross = sum(item.target_weight for item in proposal.target_allocations)
        net = gross  # Long-only V1; future short/hedge sleeves will provide signed exposure.
        current_gross = sum(item.weight for item in portfolio.positions)
        if gross > self.policy.max_gross_exposure + 1e-12:
            if gross > current_gross + 1e-12:
                blockers.append("MAX_GROSS_EXPOSURE")
            else:
                warnings.append("GROSS_EXPOSURE_REMAINS_ABOVE_LIMIT_WHILE_DERISKING")
        if net > self.policy.max_net_exposure + 1e-12:
            if net > current_gross + 1e-12:
                blockers.append("MAX_NET_EXPOSURE")
            else:
                warnings.append("NET_EXPOSURE_REMAINS_ABOVE_LIMIT_WHILE_DERISKING")
        if proposal.target_cash_weight < self.policy.min_cash_weight - 1e-12:
            if proposal.target_cash_weight < portfolio.cash_weight - 1e-12:
                blockers.append("MIN_CASH_WEIGHT")
            else:
                warnings.append("CASH_REMAINS_BELOW_LIMIT_WHILE_DERISKING")
        if proposal.estimated_portfolio_volatility > self.policy.max_portfolio_volatility + 1e-12:
            if proposal.estimated_portfolio_volatility >= context.current_portfolio_volatility - 1e-12:
                blockers.append("MAX_PORTFOLIO_VOLATILITY")
            else:
                warnings.append("VOLATILITY_REMAINS_ABOVE_LIMIT_WHILE_DERISKING")
        if proposal.estimated_turnover > self.policy.max_turnover + 1e-12:
            if has_increase:
                blockers.append("MAX_TURNOVER_WITH_RISK_INCREASE")
            else:
                warnings.append("TURNOVER_LIMIT_EXCEEDED_FOR_DERISKING")
        if context.current_drawdown >= self.policy.max_drawdown and has_increase:
            blockers.append("DRAWDOWN_THROTTLE_BLOCKS_NEW_RISK")

        verdict = RiskVerdict.REJECTED if blockers else RiskVerdict.APPROVED
        return RiskGovernorDecision(
            as_of=proposal.as_of,
            proposal_id=proposal.proposal_id,
            portfolio_snapshot_id=portfolio.snapshot_id,
            policy_id=self.policy.policy_id,
            risk_context_id=context.context_id,
            governance_id=governance.governance_id,
            verdict=verdict,
            risk_governor_approved=verdict is RiskVerdict.APPROVED,
            reviewed_target_allocations=proposal.target_allocations,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _validate_lineage(
        proposal: PortfolioAllocationProposal,
        portfolio: PortfolioSnapshot,
        context: RiskContext,
        governance: GovernanceLockState,
    ) -> None:
        if proposal.as_of != portfolio.as_of or context.as_of != portfolio.as_of:
            raise RiskGovernorError("RISK_EVALUATION_TIME_MISMATCH")
        if governance.as_of != portfolio.as_of:
            raise RiskGovernorError("GOVERNANCE_TIME_MISMATCH")
        if proposal.portfolio_snapshot_id != portfolio.snapshot_id:
            raise RiskGovernorError("RISK_PORTFOLIO_LINEAGE_MISMATCH")

    def _check_sector_limits(
        self,
        portfolio: PortfolioSnapshot,
        proposal: PortfolioAllocationProposal,
        sectors: dict[str, str],
        blockers: list[str],
        warnings: list[str],
    ) -> None:
        current_sector: dict[str, float] = {}
        for position in portfolio.positions:
            sector = sectors.get(position.security_id)
            if sector:
                current_sector[sector] = current_sector.get(sector, 0.0) + position.weight
        target_sector: dict[str, float] = {}
        for allocation in proposal.target_allocations:
            if allocation.target_weight <= 1e-12:
                continue
            sector = sectors.get(allocation.security_id)
            if sector:
                target_sector[sector] = target_sector.get(sector, 0.0) + allocation.target_weight
        for sector, target_weight in target_sector.items():
            if target_weight > self.policy.max_sector_weight + 1e-12:
                if target_weight > current_sector.get(sector, 0.0) + 1e-12:
                    blockers.append(f"MAX_SECTOR_WEIGHT:{sector}")
                else:
                    warnings.append(f"SECTOR_REMAINS_ABOVE_LIMIT_WHILE_DERISKING:{sector}")

    def _check_cluster_limits(
        self,
        portfolio: PortfolioSnapshot,
        proposal: PortfolioAllocationProposal,
        clusters: dict[str, str],
        blockers: list[str],
        warnings: list[str],
    ) -> None:
        current_cluster: dict[str, float] = {}
        for position in portfolio.positions:
            cluster = clusters.get(position.security_id)
            if cluster:
                current_cluster[cluster] = current_cluster.get(cluster, 0.0) + position.weight
        target_cluster: dict[str, float] = {}
        for allocation in proposal.target_allocations:
            if allocation.target_weight <= 1e-12:
                continue
            cluster = clusters.get(allocation.security_id)
            if cluster:
                target_cluster[cluster] = target_cluster.get(cluster, 0.0) + allocation.target_weight
        for cluster, target_weight in target_cluster.items():
            if target_weight > self.policy.max_cluster_weight + 1e-12:
                if target_weight > current_cluster.get(cluster, 0.0) + 1e-12:
                    blockers.append(f"MAX_CLUSTER_WEIGHT:{cluster}")
                else:
                    warnings.append(f"CLUSTER_REMAINS_ABOVE_LIMIT_WHILE_DERISKING:{cluster}")
