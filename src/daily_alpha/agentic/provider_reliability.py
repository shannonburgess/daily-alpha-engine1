"""Point-in-time provider reliability and data-quality incident attribution.

Stage 9D provides runtime readiness snapshots and Stage 9E records exactly which
observations were eligible for canonical reconciliation. This module turns that immutable
history into domain/provider scorecards and command-center incidents without calling a
vendor, deploying infrastructure, or creating any trading authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus
from .data_plane_readiness import (
    DataPlaneReadinessSnapshot,
    ProviderRuntimeAssessment,
    ProviderRuntimeStatus,
)
from .data_plane_reconciliation import CanonicalReconciliationResult
from .data_providers import DataDomain, ProviderRegistry, ProviderRole


class ProviderReliabilityError(ValueError):
    """Provider reliability inputs violate deterministic point-in-time contracts."""


class DataQualityIncidentKind(StrEnum):
    RUNTIME_DEGRADED = "RUNTIME_DEGRADED"
    RUNTIME_STALE = "RUNTIME_STALE"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    RUNTIME_CONFLICT = "RUNTIME_CONFLICT"
    RUNTIME_DATA_ERROR = "RUNTIME_DATA_ERROR"
    RUNTIME_MISSING = "RUNTIME_MISSING"
    OBSERVATION_EXCLUDED = "OBSERVATION_EXCLUDED"
    UNASSESSED_PROVIDER = "UNASSESSED_PROVIDER"


class IncidentSeverity(StrEnum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderReliabilityError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise ProviderReliabilityError("PROVIDER_RELIABILITY_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


@dataclass(frozen=True)
class ProviderReliabilityPolicy:
    domain: DataDomain
    window_seconds: int = 604_800
    min_runtime_samples: int = 3
    min_healthy_ratio: float = 0.95
    max_observation_exclusion_ratio: float = 0.10
    blocking_roles: tuple[ProviderRole, ...] = (ProviderRole.PRIMARY, ProviderRole.SECONDARY)

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ProviderReliabilityError("RELIABILITY_WINDOW_MUST_BE_POSITIVE")
        if self.min_runtime_samples <= 0:
            raise ProviderReliabilityError("RELIABILITY_MIN_RUNTIME_SAMPLES_MUST_BE_POSITIVE")
        values = (self.min_healthy_ratio, self.max_observation_exclusion_ratio)
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
            raise ProviderReliabilityError("RELIABILITY_RATIO_POLICY_OUT_OF_RANGE")
        object.__setattr__(self, "blocking_roles", tuple(sorted(set(self.blocking_roles))))

    @property
    def policy_id(self) -> str:
        return _digest(
            {
                "domain": self.domain.value,
                "window_seconds": self.window_seconds,
                "min_runtime_samples": self.min_runtime_samples,
                "min_healthy_ratio": self.min_healthy_ratio,
                "max_observation_exclusion_ratio": self.max_observation_exclusion_ratio,
                "blocking_roles": [role.value for role in self.blocking_roles],
            }
        )


@dataclass(frozen=True)
class DataQualityIncident:
    provider_id: str
    domain: DataDomain
    occurred_at: datetime
    kind: DataQualityIncidentKind
    severity: IncidentSeverity
    source_id: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        provider = self.provider_id.strip().upper()
        source_id = self.source_id.strip().lower()
        if not provider or not source_id:
            raise ProviderReliabilityError("DATA_QUALITY_INCIDENT_IDENTITY_REQUIRED")
        reasons = tuple(sorted({reason.strip().upper() for reason in self.reasons if reason}))
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "occurred_at", _aware_utc(self.occurred_at, "INCIDENT_OCCURRED_AT"))
        object.__setattr__(self, "reasons", reasons)

    @property
    def incident_id(self) -> str:
        return _digest(
            {
                "provider_id": self.provider_id,
                "domain": self.domain.value,
                "occurred_at": self.occurred_at.isoformat(),
                "kind": self.kind.value,
                "severity": self.severity.value,
                "source_id": self.source_id,
                "reasons": list(self.reasons),
            }
        )


@dataclass(frozen=True)
class ProviderReliabilityAssessment:
    provider_id: str
    independence_group: str
    role: ProviderRole
    status: ReadinessStatus
    runtime_sample_count: int
    healthy_runtime_count: int
    healthy_ratio: float | None
    observation_count: int
    eligible_observation_count: int
    excluded_observation_count: int
    exclusion_ratio: float | None
    incident_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        provider = self.provider_id.strip().upper()
        group = self.independence_group.strip().upper()
        if not provider or not group:
            raise ProviderReliabilityError("PROVIDER_RELIABILITY_IDENTITY_REQUIRED")
        counts = (
            self.runtime_sample_count,
            self.healthy_runtime_count,
            self.observation_count,
            self.eligible_observation_count,
            self.excluded_observation_count,
        )
        if any(count < 0 for count in counts):
            raise ProviderReliabilityError("PROVIDER_RELIABILITY_COUNTS_NONNEGATIVE")
        if self.healthy_runtime_count > self.runtime_sample_count:
            raise ProviderReliabilityError("HEALTHY_RUNTIME_COUNT_EXCEEDS_SAMPLES")
        if self.eligible_observation_count + self.excluded_observation_count != self.observation_count:
            raise ProviderReliabilityError("OBSERVATION_RELIABILITY_PARTITION_INVALID")
        for value in (self.healthy_ratio, self.exclusion_ratio):
            if value is not None and (not math.isfinite(value) or not 0.0 <= value <= 1.0):
                raise ProviderReliabilityError("PROVIDER_RELIABILITY_RATIO_OUT_OF_RANGE")
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ProviderReliabilityError("PASS_PROVIDER_RELIABILITY_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ProviderReliabilityError("WARNING_PROVIDER_RELIABILITY_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "independence_group", group)
        object.__setattr__(self, "incident_ids", tuple(sorted(set(self.incident_ids))))
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def assessment_id(self) -> str:
        return _digest(
            {
                "provider_id": self.provider_id,
                "independence_group": self.independence_group,
                "role": self.role.value,
                "status": self.status.value,
                "runtime_sample_count": self.runtime_sample_count,
                "healthy_runtime_count": self.healthy_runtime_count,
                "healthy_ratio": self.healthy_ratio,
                "observation_count": self.observation_count,
                "eligible_observation_count": self.eligible_observation_count,
                "excluded_observation_count": self.excluded_observation_count,
                "exclusion_ratio": self.exclusion_ratio,
                "incident_ids": list(self.incident_ids),
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
            }
        )


@dataclass(frozen=True)
class ProviderReliabilityReport:
    domain: DataDomain
    as_of: datetime
    window_start: datetime
    policy_id: str
    status: ReadinessStatus
    provider_assessments: tuple[ProviderReliabilityAssessment, ...]
    incidents: tuple[DataQualityIncident, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ProviderReliabilityError("PROVIDER_RELIABILITY_POLICY_ID_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ProviderReliabilityError("PROVIDER_RELIABILITY_MUST_REMAIN_RESEARCH_ONLY")
        boundary = _aware_utc(self.as_of, "PROVIDER_RELIABILITY_AS_OF")
        window_start = _aware_utc(self.window_start, "PROVIDER_RELIABILITY_WINDOW_START")
        if window_start >= boundary:
            raise ProviderReliabilityError("PROVIDER_RELIABILITY_WINDOW_INVALID")
        assessments = tuple(sorted(self.provider_assessments, key=lambda item: item.provider_id))
        incidents = tuple(sorted(self.incidents, key=lambda item: item.incident_id))
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ProviderReliabilityError("PASS_RELIABILITY_REPORT_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ProviderReliabilityError("WARNING_RELIABILITY_REPORT_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "window_start", window_start)
        object.__setattr__(self, "provider_assessments", assessments)
        object.__setattr__(self, "incidents", incidents)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def report_id(self) -> str:
        return _digest(
            {
                "domain": self.domain.value,
                "as_of": self.as_of.isoformat(),
                "window_start": self.window_start.isoformat(),
                "policy_id": self.policy_id,
                "status": self.status.value,
                "provider_assessment_ids": [item.assessment_id for item in self.provider_assessments],
                "incident_ids": [item.incident_id for item in self.incidents],
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


_RUNTIME_INCIDENTS = {
    ProviderRuntimeStatus.DEGRADED: (DataQualityIncidentKind.RUNTIME_DEGRADED, IncidentSeverity.WARNING),
    ProviderRuntimeStatus.STALE: (DataQualityIncidentKind.RUNTIME_STALE, IncidentSeverity.WARNING),
    ProviderRuntimeStatus.UNAVAILABLE: (
        DataQualityIncidentKind.RUNTIME_UNAVAILABLE,
        IncidentSeverity.CRITICAL,
    ),
    ProviderRuntimeStatus.CONFLICT: (DataQualityIncidentKind.RUNTIME_CONFLICT, IncidentSeverity.CRITICAL),
    ProviderRuntimeStatus.DATA_ERROR: (
        DataQualityIncidentKind.RUNTIME_DATA_ERROR,
        IncidentSeverity.CRITICAL,
    ),
    ProviderRuntimeStatus.MISSING: (DataQualityIncidentKind.RUNTIME_MISSING, IncidentSeverity.WARNING),
}


class ProviderReliabilityEngine:
    """Build domain reliability scorecards from immutable readiness/reconciliation history."""

    def __init__(self, *, registry: ProviderRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _in_window(value: datetime, *, start: datetime, end: datetime) -> bool:
        boundary = _aware_utc(value, "RELIABILITY_HISTORY_AS_OF")
        return start <= boundary <= end

    @staticmethod
    def _unique_readiness(
        snapshots: tuple[DataPlaneReadinessSnapshot, ...],
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[DataPlaneReadinessSnapshot, ...]:
        unique = {
            snapshot.snapshot_id: snapshot
            for snapshot in snapshots
            if ProviderReliabilityEngine._in_window(snapshot.as_of, start=start, end=end)
        }
        return tuple(sorted(unique.values(), key=lambda item: (item.as_of, item.snapshot_id)))

    @staticmethod
    def _unique_reconciliation(
        results: tuple[CanonicalReconciliationResult, ...],
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[CanonicalReconciliationResult, ...]:
        unique = {
            result.result_id: result
            for result in results
            if ProviderReliabilityEngine._in_window(result.as_of, start=start, end=end)
        }
        return tuple(sorted(unique.values(), key=lambda item: (item.as_of, item.result_id)))

    @staticmethod
    def _runtime_incident(
        *,
        domain: DataDomain,
        occurred_at: datetime,
        assessment: ProviderRuntimeAssessment,
    ) -> DataQualityIncident | None:
        mapping = _RUNTIME_INCIDENTS.get(assessment.status)
        if mapping is None:
            return None
        kind, severity = mapping
        return DataQualityIncident(
            provider_id=assessment.provider_id,
            domain=domain,
            occurred_at=occurred_at,
            kind=kind,
            severity=severity,
            source_id=assessment.assessment_id,
            reasons=assessment.reasons,
        )

    def evaluate(
        self,
        *,
        policy: ProviderReliabilityPolicy,
        readiness_history: tuple[DataPlaneReadinessSnapshot, ...],
        reconciliation_history: tuple[CanonicalReconciliationResult, ...],
        as_of: datetime,
    ) -> ProviderReliabilityReport:
        boundary = _aware_utc(as_of, "PROVIDER_RELIABILITY_AS_OF")
        start = boundary - timedelta(seconds=policy.window_seconds)
        snapshots = self._unique_readiness(readiness_history, start=start, end=boundary)
        results = self._unique_reconciliation(reconciliation_history, start=start, end=boundary)

        runtime_by_provider: dict[str, list[ProviderRuntimeAssessment]] = {}
        incidents: dict[str, DataQualityIncident] = {}
        for snapshot in snapshots:
            for domain_readiness in snapshot.domains:
                if domain_readiness.domain is not policy.domain:
                    continue
                for assessment in domain_readiness.provider_assessments:
                    runtime_by_provider.setdefault(assessment.provider_id, []).append(assessment)
                    incident = self._runtime_incident(
                        domain=policy.domain,
                        occurred_at=snapshot.as_of,
                        assessment=assessment,
                    )
                    if incident is not None:
                        incidents.setdefault(incident.incident_id, incident)

        eligibility_by_provider: dict[str, list[bool]] = {}
        for result in results:
            if result.domain is not policy.domain:
                continue
            for assessment in result.eligibility:
                eligibility_by_provider.setdefault(assessment.provider_id, []).append(assessment.eligible)
                if assessment.eligible:
                    continue
                if assessment.runtime_status is None:
                    incident = DataQualityIncident(
                        provider_id=assessment.provider_id,
                        domain=policy.domain,
                        occurred_at=result.as_of,
                        kind=DataQualityIncidentKind.UNASSESSED_PROVIDER,
                        severity=IncidentSeverity.CRITICAL,
                        source_id=assessment.assessment_id,
                        reasons=assessment.reasons,
                    )
                else:
                    incident = DataQualityIncident(
                        provider_id=assessment.provider_id,
                        domain=policy.domain,
                        occurred_at=result.as_of,
                        kind=DataQualityIncidentKind.OBSERVATION_EXCLUDED,
                        severity=(
                            IncidentSeverity.CRITICAL
                            if assessment.runtime_status
                            in {
                                ProviderRuntimeStatus.UNAVAILABLE,
                                ProviderRuntimeStatus.CONFLICT,
                                ProviderRuntimeStatus.DATA_ERROR,
                            }
                            else IncidentSeverity.WARNING
                        ),
                        source_id=assessment.assessment_id,
                        reasons=assessment.reasons,
                    )
                incidents.setdefault(incident.incident_id, incident)

        assessments: list[ProviderReliabilityAssessment] = []
        report_blockers: list[str] = []
        report_warnings: list[str] = []
        incident_values = tuple(incidents.values())

        for definition in self.registry.providers_for(policy.domain):
            capability = definition.capability_for(policy.domain)
            if capability is None:
                continue
            runtime_samples = runtime_by_provider.get(definition.provider_id, [])
            runtime_count = len(runtime_samples)
            healthy_count = sum(
                item.status is ProviderRuntimeStatus.HEALTHY for item in runtime_samples
            )
            healthy_ratio = _ratio(healthy_count, runtime_count)
            observation_flags = eligibility_by_provider.get(definition.provider_id, [])
            observation_count = len(observation_flags)
            eligible_count = sum(observation_flags)
            excluded_count = observation_count - eligible_count
            exclusion_ratio = _ratio(excluded_count, observation_count)
            provider_incidents = tuple(
                item.incident_id
                for item in incident_values
                if item.provider_id == definition.provider_id
            )

            blockers: list[str] = []
            warnings: list[str] = []
            blocking_role = capability.role in policy.blocking_roles
            if runtime_count < policy.min_runtime_samples:
                warnings.append(
                    f"INSUFFICIENT_RUNTIME_HISTORY:{runtime_count}<"
                    f"{policy.min_runtime_samples}"
                )
            elif healthy_ratio is not None and healthy_ratio < policy.min_healthy_ratio:
                message = (
                    f"HEALTHY_RATIO_BELOW_POLICY:{healthy_ratio:.6f}<"
                    f"{policy.min_healthy_ratio:.6f}"
                )
                (blockers if blocking_role else warnings).append(message)
            if (
                exclusion_ratio is not None
                and exclusion_ratio > policy.max_observation_exclusion_ratio
            ):
                message = (
                    f"EXCLUSION_RATIO_ABOVE_POLICY:{exclusion_ratio:.6f}>"
                    f"{policy.max_observation_exclusion_ratio:.6f}"
                )
                (blockers if blocking_role else warnings).append(message)
            if provider_incidents:
                warnings.append(f"DATA_QUALITY_INCIDENTS:{len(provider_incidents)}")

            if blockers:
                status = ReadinessStatus.BLOCKED
                report_blockers.extend(
                    f"PROVIDER_RELIABILITY:{definition.provider_id}:{item}" for item in blockers
                )
            elif warnings:
                status = ReadinessStatus.WARNING
                report_warnings.extend(
                    f"PROVIDER_RELIABILITY:{definition.provider_id}:{item}" for item in warnings
                )
            else:
                status = ReadinessStatus.PASS

            assessments.append(
                ProviderReliabilityAssessment(
                    provider_id=definition.provider_id,
                    independence_group=definition.independence_group,
                    role=capability.role,
                    status=status,
                    runtime_sample_count=runtime_count,
                    healthy_runtime_count=healthy_count,
                    healthy_ratio=healthy_ratio,
                    observation_count=observation_count,
                    eligible_observation_count=eligible_count,
                    excluded_observation_count=excluded_count,
                    exclusion_ratio=exclusion_ratio,
                    incident_ids=provider_incidents,
                    blockers=tuple(blockers),
                    warnings=tuple(warnings),
                )
            )

        registered_provider_ids = {item.provider_id for item in assessments}
        unexpected_incidents = [
            item
            for item in incident_values
            if item.provider_id not in registered_provider_ids
        ]
        for incident in unexpected_incidents:
            message = f"UNEXPECTED_PROVIDER_INCIDENT:{incident.provider_id}:{incident.kind.value}"
            if incident.severity is IncidentSeverity.CRITICAL:
                report_blockers.append(message)
            else:
                report_warnings.append(message)

        if report_blockers:
            status = ReadinessStatus.BLOCKED
        elif report_warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS

        return ProviderReliabilityReport(
            domain=policy.domain,
            as_of=boundary,
            window_start=start,
            policy_id=policy.policy_id,
            status=status,
            provider_assessments=tuple(assessments),
            incidents=incident_values,
            blockers=tuple(report_blockers),
            warnings=tuple(report_warnings),
        )
