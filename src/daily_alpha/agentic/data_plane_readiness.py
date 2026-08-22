"""Operational readiness for the institutional data plane.

Configured provider coverage is not the same thing as healthy runtime coverage. This module
combines provider capabilities with Stage 9B transport telemetry at an exact as-of boundary
and produces deterministic command-center readiness. It is observability/research only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .aws_transport import SourceTransportTelemetry
from .contracts import ReadinessStatus
from .data_providers import DataDomain, ProviderRegistry, ProviderRole
from .durable_evidence import SourceHealthStatus


class DataPlaneReadinessError(ValueError):
    """Operational data-plane readiness inputs violate deterministic contracts."""


class ProviderRuntimeStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICT = "CONFLICT"
    DATA_ERROR = "DATA_ERROR"
    MISSING = "MISSING"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataPlaneReadinessError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise DataPlaneReadinessError("DATA_PLANE_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DomainReadinessPolicy:
    domain: DataDomain
    min_independent_groups: int
    required_roles: tuple[ProviderRole, ...] = field(default_factory=tuple)
    max_latency_ms: float | None = None
    max_freshness_seconds: int | None = None
    required: bool = True

    def __post_init__(self) -> None:
        if self.min_independent_groups <= 0:
            raise DataPlaneReadinessError("DOMAIN_MIN_INDEPENDENT_GROUPS_MUST_BE_POSITIVE")
        if self.max_latency_ms is not None and (
            not math.isfinite(self.max_latency_ms) or self.max_latency_ms <= 0
        ):
            raise DataPlaneReadinessError("DOMAIN_MAX_LATENCY_MUST_BE_POSITIVE")
        if self.max_freshness_seconds is not None and self.max_freshness_seconds <= 0:
            raise DataPlaneReadinessError("DOMAIN_MAX_FRESHNESS_MUST_BE_POSITIVE")
        object.__setattr__(self, "required_roles", tuple(sorted(set(self.required_roles))))

    @property
    def policy_id(self) -> str:
        return _digest(
            {
                "domain": self.domain.value,
                "min_independent_groups": self.min_independent_groups,
                "required_roles": [role.value for role in self.required_roles],
                "max_latency_ms": self.max_latency_ms,
                "max_freshness_seconds": self.max_freshness_seconds,
                "required": self.required,
            }
        )


@dataclass(frozen=True)
class ProviderRuntimeAssessment:
    provider_id: str
    independence_group: str
    role: ProviderRole
    status: ProviderRuntimeStatus
    telemetry_id: str | None
    latency_ms: float | None
    effective_freshness_seconds: float | None
    allowed_freshness_seconds: int
    last_success_at: datetime | None
    reasons: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return self.status is ProviderRuntimeStatus.HEALTHY

    @property
    def assessment_id(self) -> str:
        return _digest(
            {
                "provider_id": self.provider_id,
                "independence_group": self.independence_group,
                "role": self.role.value,
                "status": self.status.value,
                "telemetry_id": self.telemetry_id,
                "latency_ms": self.latency_ms,
                "effective_freshness_seconds": self.effective_freshness_seconds,
                "allowed_freshness_seconds": self.allowed_freshness_seconds,
                "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
                "reasons": list(self.reasons),
            }
        )


@dataclass(frozen=True)
class DomainOperationalReadiness:
    domain: DataDomain
    as_of: datetime
    status: ReadinessStatus
    required: bool
    policy_id: str
    provider_assessments: tuple[ProviderRuntimeAssessment, ...]
    healthy_provider_ids: tuple[str, ...]
    healthy_independence_groups: tuple[str, ...]
    healthy_roles: tuple[ProviderRole, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "DOMAIN_READINESS_AS_OF"))
        object.__setattr__(self, "provider_assessments", tuple(self.provider_assessments))
        object.__setattr__(self, "healthy_provider_ids", tuple(sorted(set(self.healthy_provider_ids))))
        object.__setattr__(
            self,
            "healthy_independence_groups",
            tuple(sorted(set(self.healthy_independence_groups))),
        )
        object.__setattr__(self, "healthy_roles", tuple(sorted(set(self.healthy_roles))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        if self.status is ReadinessStatus.PASS and (self.blockers or self.warnings):
            raise DataPlaneReadinessError("PASS_DOMAIN_READINESS_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and self.blockers:
            raise DataPlaneReadinessError("WARNING_DOMAIN_READINESS_CANNOT_HAVE_BLOCKERS")

    @property
    def readiness_id(self) -> str:
        return _digest(
            {
                "domain": self.domain.value,
                "as_of": self.as_of.isoformat(),
                "status": self.status.value,
                "required": self.required,
                "policy_id": self.policy_id,
                "provider_assessment_ids": [item.assessment_id for item in self.provider_assessments],
                "healthy_provider_ids": list(self.healthy_provider_ids),
                "healthy_independence_groups": list(self.healthy_independence_groups),
                "healthy_roles": [role.value for role in self.healthy_roles],
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
            }
        )


@dataclass(frozen=True)
class DataPlaneReadinessSnapshot:
    as_of: datetime
    status: ReadinessStatus
    domains: tuple[DomainOperationalReadiness, ...]
    healthy_provider_count: int
    degraded_provider_count: int
    stale_provider_count: int
    unavailable_provider_count: int
    blocked_domains: tuple[DataDomain, ...]
    warning_domains: tuple[DataDomain, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DataPlaneReadinessError("DATA_PLANE_READINESS_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "DATA_PLANE_AS_OF"))
        object.__setattr__(self, "domains", tuple(self.domains))
        object.__setattr__(self, "blocked_domains", tuple(sorted(set(self.blocked_domains))))
        object.__setattr__(self, "warning_domains", tuple(sorted(set(self.warning_domains))))
        counts = (
            self.healthy_provider_count,
            self.degraded_provider_count,
            self.stale_provider_count,
            self.unavailable_provider_count,
        )
        if any(count < 0 for count in counts):
            raise DataPlaneReadinessError("DATA_PLANE_PROVIDER_COUNTS_MUST_BE_NONNEGATIVE")

    @property
    def snapshot_id(self) -> str:
        return _digest(
            {
                "as_of": self.as_of.isoformat(),
                "status": self.status.value,
                "domain_readiness_ids": [item.readiness_id for item in self.domains],
                "healthy_provider_count": self.healthy_provider_count,
                "degraded_provider_count": self.degraded_provider_count,
                "stale_provider_count": self.stale_provider_count,
                "unavailable_provider_count": self.unavailable_provider_count,
                "blocked_domains": [item.value for item in self.blocked_domains],
                "warning_domains": [item.value for item in self.warning_domains],
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


class InstitutionalDataPlaneReadinessEngine:
    """Evaluate actual healthy provider redundancy at an exact point in time."""

    def __init__(self, *, registry: ProviderRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _latest_telemetry(
        telemetry: tuple[SourceTransportTelemetry, ...],
        as_of: datetime,
    ) -> dict[str, SourceTransportTelemetry]:
        latest: dict[str, SourceTransportTelemetry] = {}
        for item in telemetry:
            if item.observed_at > as_of:
                continue
            current = latest.get(item.provider_id)
            if current is None or (item.observed_at, item.telemetry_id) > (
                current.observed_at,
                current.telemetry_id,
            ):
                latest[item.provider_id] = item
        return latest

    @staticmethod
    def _runtime_status(
        *,
        telemetry: SourceTransportTelemetry,
        as_of: datetime,
        allowed_freshness_seconds: int,
        max_latency_ms: float | None,
    ) -> tuple[ProviderRuntimeStatus, float, tuple[str, ...]]:
        elapsed = max(0.0, (as_of - telemetry.observed_at).total_seconds())
        base_freshness = telemetry.freshness_seconds or 0.0
        effective_freshness = base_freshness + elapsed
        reasons: list[str] = []

        status_map = {
            SourceHealthStatus.HEALTHY: ProviderRuntimeStatus.HEALTHY,
            SourceHealthStatus.DEGRADED: ProviderRuntimeStatus.DEGRADED,
            SourceHealthStatus.UNAVAILABLE: ProviderRuntimeStatus.UNAVAILABLE,
            SourceHealthStatus.CONFLICT: ProviderRuntimeStatus.CONFLICT,
            SourceHealthStatus.DATA_ERROR: ProviderRuntimeStatus.DATA_ERROR,
        }
        status = status_map[telemetry.status]
        if status is ProviderRuntimeStatus.HEALTHY and effective_freshness > allowed_freshness_seconds:
            status = ProviderRuntimeStatus.STALE
            reasons.append("FRESHNESS_SLA_EXCEEDED")
        if (
            status is ProviderRuntimeStatus.HEALTHY
            and max_latency_ms is not None
            and telemetry.latency_ms is not None
            and telemetry.latency_ms > max_latency_ms
        ):
            status = ProviderRuntimeStatus.DEGRADED
            reasons.append("LATENCY_BUDGET_EXCEEDED")
        if status is not ProviderRuntimeStatus.HEALTHY and not reasons:
            reasons.append(f"SOURCE_HEALTH_{telemetry.status.value}")
        return status, effective_freshness, tuple(reasons)

    def evaluate_domain(
        self,
        *,
        policy: DomainReadinessPolicy,
        telemetry: tuple[SourceTransportTelemetry, ...],
        as_of: datetime,
    ) -> DomainOperationalReadiness:
        boundary = _aware_utc(as_of, "DOMAIN_READINESS_AS_OF")
        latest = self._latest_telemetry(telemetry, boundary)
        assessments: list[ProviderRuntimeAssessment] = []

        for definition in self.registry.providers_for(policy.domain):
            capability = definition.capability_for(policy.domain)
            if capability is None:
                continue
            allowed_freshness = capability.max_freshness_seconds
            if policy.max_freshness_seconds is not None:
                allowed_freshness = min(allowed_freshness, policy.max_freshness_seconds)
            item = latest.get(definition.provider_id)
            if item is None:
                assessments.append(
                    ProviderRuntimeAssessment(
                        provider_id=definition.provider_id,
                        independence_group=definition.independence_group,
                        role=capability.role,
                        status=ProviderRuntimeStatus.MISSING,
                        telemetry_id=None,
                        latency_ms=None,
                        effective_freshness_seconds=None,
                        allowed_freshness_seconds=allowed_freshness,
                        last_success_at=None,
                        reasons=("TELEMETRY_MISSING",),
                    )
                )
                continue
            status, freshness, reasons = self._runtime_status(
                telemetry=item,
                as_of=boundary,
                allowed_freshness_seconds=allowed_freshness,
                max_latency_ms=policy.max_latency_ms,
            )
            assessments.append(
                ProviderRuntimeAssessment(
                    provider_id=definition.provider_id,
                    independence_group=definition.independence_group,
                    role=capability.role,
                    status=status,
                    telemetry_id=item.telemetry_id,
                    latency_ms=item.latency_ms,
                    effective_freshness_seconds=round(freshness, 6),
                    allowed_freshness_seconds=allowed_freshness,
                    last_success_at=item.last_success_at,
                    reasons=reasons,
                )
            )

        assessments.sort(key=lambda item: item.provider_id)
        healthy = [item for item in assessments if item.usable]
        groups = tuple(sorted({item.independence_group for item in healthy}))
        roles = tuple(sorted({item.role for item in healthy}))
        blockers: list[str] = []
        warnings: list[str] = []

        if len(groups) < policy.min_independent_groups:
            message = (
                f"INSUFFICIENT_HEALTHY_INDEPENDENT_GROUPS:{len(groups)}:"
                f"REQUIRED:{policy.min_independent_groups}"
            )
            (blockers if policy.required else warnings).append(message)
        for role in policy.required_roles:
            if role not in roles:
                message = f"HEALTHY_REQUIRED_ROLE_MISSING:{role.value}"
                (blockers if policy.required else warnings).append(message)
        for item in assessments:
            if not item.usable:
                warnings.append(f"PROVIDER_{item.status.value}:{item.provider_id}")

        if blockers:
            status = ReadinessStatus.BLOCKED
        elif warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return DomainOperationalReadiness(
            domain=policy.domain,
            as_of=boundary,
            status=status,
            required=policy.required,
            policy_id=policy.policy_id,
            provider_assessments=tuple(assessments),
            healthy_provider_ids=tuple(item.provider_id for item in healthy),
            healthy_independence_groups=groups,
            healthy_roles=roles,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def evaluate(
        self,
        *,
        policies: tuple[DomainReadinessPolicy, ...],
        telemetry: tuple[SourceTransportTelemetry, ...],
        as_of: datetime,
    ) -> DataPlaneReadinessSnapshot:
        boundary = _aware_utc(as_of, "DATA_PLANE_AS_OF")
        if len({policy.domain for policy in policies}) != len(policies):
            raise DataPlaneReadinessError("DATA_PLANE_DOMAIN_POLICY_DUPLICATE")
        domains = tuple(
            sorted(
                (
                    self.evaluate_domain(policy=policy, telemetry=telemetry, as_of=boundary)
                    for policy in policies
                ),
                key=lambda item: item.domain.value,
            )
        )
        blocked = tuple(item.domain for item in domains if item.status is ReadinessStatus.BLOCKED)
        warnings = tuple(item.domain for item in domains if item.status is ReadinessStatus.WARNING)
        required_blocked = any(
            item.status is ReadinessStatus.BLOCKED and item.required for item in domains
        )
        if required_blocked:
            status = ReadinessStatus.BLOCKED
        elif blocked or warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS

        unique_assessments: dict[str, ProviderRuntimeAssessment] = {}
        for domain in domains:
            for item in domain.provider_assessments:
                existing = unique_assessments.get(item.provider_id)
                if existing is None or item.status is not ProviderRuntimeStatus.HEALTHY:
                    unique_assessments[item.provider_id] = item
        provider_statuses = tuple(item.status for item in unique_assessments.values())
        return DataPlaneReadinessSnapshot(
            as_of=boundary,
            status=status,
            domains=domains,
            healthy_provider_count=sum(
                status is ProviderRuntimeStatus.HEALTHY for status in provider_statuses
            ),
            degraded_provider_count=sum(
                status in {
                    ProviderRuntimeStatus.DEGRADED,
                    ProviderRuntimeStatus.CONFLICT,
                    ProviderRuntimeStatus.DATA_ERROR,
                }
                for status in provider_statuses
            ),
            stale_provider_count=sum(
                status is ProviderRuntimeStatus.STALE for status in provider_statuses
            ),
            unavailable_provider_count=sum(
                status in {ProviderRuntimeStatus.UNAVAILABLE, ProviderRuntimeStatus.MISSING}
                for status in provider_statuses
            ),
            blocked_domains=blocked,
            warning_domains=warnings,
        )
