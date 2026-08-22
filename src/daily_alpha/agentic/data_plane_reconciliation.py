"""Readiness-gated canonical reconciliation for the institutional data plane.

Stage 9D proves which providers are operationally healthy at an exact point in time.
Earlier reconciliation layers prove whether provider observations agree semantically.
This gateway binds those two controls so a payload cannot become canonical merely because
its observation status says COMPLETE while its transport/provider runtime is degraded,
stale, unavailable, conflicting, or otherwise untrusted.

This module is research/data-governance only. It does not deploy AWS, resolve secrets,
call vendors, authorize capital, route orders, or enable live trading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus
from .data_plane_readiness import (
    DataPlaneReadinessSnapshot,
    DomainOperationalReadiness,
    ProviderRuntimeAssessment,
    ProviderRuntimeStatus,
)
from .data_providers import DataDomain, DataRequest, ProviderObservation, ProviderRegistry
from .market_reconciliation import (
    CanonicalMarketState,
    MarketDataReconciler,
    MarketReconciliationPolicy,
)
from .research_facts import (
    CanonicalResearchFactState,
    ResearchFactPolicy,
    ResearchFactReconciler,
)


class DataPlaneReconciliationError(ValueError):
    """Readiness/canonical reconciliation lineage violates deterministic contracts."""


class CanonicalRoute(StrEnum):
    MARKET_BAR = "MARKET_BAR"
    MARKET_QUOTE = "MARKET_QUOTE"
    RESEARCH_FACT = "RESEARCH_FACT"


_RESEARCH_DOMAINS = {
    DataDomain.FUNDAMENTALS,
    DataDomain.ESTIMATES_REVISIONS,
    DataDomain.MACRO,
    DataDomain.NEWS_CATALYSTS,
    DataDomain.INSTITUTIONAL,
    DataDomain.BEHAVIORAL,
}


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataPlaneReconciliationError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise DataPlaneReconciliationError("RECONCILIATION_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ObservationEligibilityAssessment:
    """Why one provider observation was or was not allowed into canonical reconciliation."""

    observation_id: str
    provider_id: str
    independence_group: str
    eligible: bool
    runtime_status: ProviderRuntimeStatus | None
    runtime_assessment_id: str | None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        observation_id = self.observation_id.strip().lower()
        provider_id = self.provider_id.strip().upper()
        independence_group = self.independence_group.strip().upper()
        if not observation_id or not provider_id or not independence_group:
            raise DataPlaneReconciliationError("OBSERVATION_ELIGIBILITY_IDENTITY_REQUIRED")
        reasons = tuple(sorted({reason.strip().upper() for reason in self.reasons if reason}))
        if self.eligible:
            if self.runtime_status is not ProviderRuntimeStatus.HEALTHY:
                raise DataPlaneReconciliationError("ELIGIBLE_OBSERVATION_REQUIRES_HEALTHY_RUNTIME")
            if not self.runtime_assessment_id:
                raise DataPlaneReconciliationError("ELIGIBLE_OBSERVATION_REQUIRES_RUNTIME_ASSESSMENT")
            if reasons:
                raise DataPlaneReconciliationError("ELIGIBLE_OBSERVATION_CANNOT_HAVE_REASONS")
        elif not reasons:
            raise DataPlaneReconciliationError("EXCLUDED_OBSERVATION_REQUIRES_REASON")
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "independence_group", independence_group)
        object.__setattr__(self, "reasons", reasons)

    @property
    def assessment_id(self) -> str:
        return _digest(
            {
                "observation_id": self.observation_id,
                "provider_id": self.provider_id,
                "independence_group": self.independence_group,
                "eligible": self.eligible,
                "runtime_status": self.runtime_status.value if self.runtime_status else None,
                "runtime_assessment_id": self.runtime_assessment_id,
                "reasons": list(self.reasons),
            }
        )


CanonicalState = CanonicalMarketState | CanonicalResearchFactState


@dataclass(frozen=True)
class CanonicalReconciliationResult:
    """Auditable binding of operational readiness to one canonical reconciliation attempt."""

    request_id: str
    domain: DataDomain
    as_of: datetime
    route: CanonicalRoute
    data_plane_snapshot_id: str
    domain_readiness_id: str
    status: ReadinessStatus
    eligibility: tuple[ObservationEligibilityAssessment, ...]
    incoming_observation_ids: tuple[str, ...]
    eligible_observation_ids: tuple[str, ...]
    excluded_observation_ids: tuple[str, ...]
    canonical_state: CanonicalState | None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.data_plane_snapshot_id.strip():
            raise DataPlaneReconciliationError("RECONCILIATION_LINEAGE_ID_REQUIRED")
        if not self.domain_readiness_id.strip():
            raise DataPlaneReconciliationError("DOMAIN_READINESS_ID_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DataPlaneReconciliationError("RECONCILIATION_RESULT_MUST_REMAIN_RESEARCH_ONLY")
        boundary = _aware_utc(self.as_of, "RECONCILIATION_AS_OF")
        eligibility = tuple(sorted(self.eligibility, key=lambda item: item.assessment_id))
        incoming = tuple(sorted(set(self.incoming_observation_ids)))
        eligible = tuple(sorted(set(self.eligible_observation_ids)))
        excluded = tuple(sorted(set(self.excluded_observation_ids)))
        if set(eligible) & set(excluded):
            raise DataPlaneReconciliationError("OBSERVATION_CANNOT_BE_ELIGIBLE_AND_EXCLUDED")
        if set(eligible) | set(excluded) != set(incoming):
            raise DataPlaneReconciliationError("OBSERVATION_ELIGIBILITY_PARTITION_INVALID")
        if self.status is not ReadinessStatus.BLOCKED and self.canonical_state is None:
            raise DataPlaneReconciliationError("NONBLOCKED_RECONCILIATION_REQUIRES_CANONICAL_STATE")
        if self.canonical_state is not None:
            if self.canonical_state.domain is not self.domain:
                raise DataPlaneReconciliationError("CANONICAL_STATE_DOMAIN_MISMATCH")
            if self.canonical_state.as_of != boundary:
                raise DataPlaneReconciliationError("CANONICAL_STATE_AS_OF_MISMATCH")
        blockers = tuple(sorted({item.strip().upper() for item in self.blockers if item}))
        warnings = tuple(sorted({item.strip().upper() for item in self.warnings if item}))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise DataPlaneReconciliationError("PASS_RECONCILIATION_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise DataPlaneReconciliationError("WARNING_RECONCILIATION_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "eligibility", eligibility)
        object.__setattr__(self, "incoming_observation_ids", incoming)
        object.__setattr__(self, "eligible_observation_ids", eligible)
        object.__setattr__(self, "excluded_observation_ids", excluded)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def canonical_state_id(self) -> str | None:
        return self.canonical_state.state_id if self.canonical_state is not None else None

    @property
    def result_id(self) -> str:
        return _digest(
            {
                "request_id": self.request_id,
                "domain": self.domain.value,
                "as_of": self.as_of.isoformat(),
                "route": self.route.value,
                "data_plane_snapshot_id": self.data_plane_snapshot_id,
                "domain_readiness_id": self.domain_readiness_id,
                "status": self.status.value,
                "eligibility_assessment_ids": [item.assessment_id for item in self.eligibility],
                "incoming_observation_ids": list(self.incoming_observation_ids),
                "eligible_observation_ids": list(self.eligible_observation_ids),
                "excluded_observation_ids": list(self.excluded_observation_ids),
                "canonical_state_id": self.canonical_state_id,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


class InstitutionalReconciliationGateway:
    """Allow only runtime-healthy providers to participate in canonical reconciliation."""

    def __init__(self, *, registry: ProviderRegistry) -> None:
        self.registry = registry
        self.market_reconciler = MarketDataReconciler(registry)
        self.research_reconciler = ResearchFactReconciler(registry)

    @staticmethod
    def _domain_readiness(
        snapshot: DataPlaneReadinessSnapshot,
        domain: DataDomain,
    ) -> DomainOperationalReadiness:
        matches = [item for item in snapshot.domains if item.domain is domain]
        if not matches:
            raise DataPlaneReconciliationError(f"DOMAIN_READINESS_MISSING:{domain.value}")
        if len(matches) != 1:
            raise DataPlaneReconciliationError(f"DOMAIN_READINESS_DUPLICATE:{domain.value}")
        return matches[0]

    @staticmethod
    def _route(domain: DataDomain) -> CanonicalRoute:
        if domain is DataDomain.MARKET_BARS:
            return CanonicalRoute.MARKET_BAR
        if domain is DataDomain.MARKET_QUOTES:
            return CanonicalRoute.MARKET_QUOTE
        if domain in _RESEARCH_DOMAINS:
            return CanonicalRoute.RESEARCH_FACT
        raise DataPlaneReconciliationError(f"RECONCILIATION_DOMAIN_UNSUPPORTED:{domain.value}")

    @staticmethod
    def _runtime_by_provider(
        readiness: DomainOperationalReadiness,
    ) -> dict[str, ProviderRuntimeAssessment]:
        result: dict[str, ProviderRuntimeAssessment] = {}
        for assessment in readiness.provider_assessments:
            if assessment.provider_id in result:
                raise DataPlaneReconciliationError(
                    f"DUPLICATE_PROVIDER_RUNTIME_ASSESSMENT:{assessment.provider_id}"
                )
            result[assessment.provider_id] = assessment
        return result

    def reconcile(
        self,
        *,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        readiness_snapshot: DataPlaneReadinessSnapshot,
        market_policy: MarketReconciliationPolicy | None = None,
        research_policy: ResearchFactPolicy | None = None,
    ) -> CanonicalReconciliationResult:
        boundary = _aware_utc(request.as_of, "DATA_REQUEST_AS_OF")
        if readiness_snapshot.as_of != boundary:
            raise DataPlaneReconciliationError("READINESS_SNAPSHOT_AS_OF_REQUEST_MISMATCH")
        readiness = self._domain_readiness(readiness_snapshot, request.domain)
        if readiness.as_of != boundary:
            raise DataPlaneReconciliationError("DOMAIN_READINESS_AS_OF_REQUEST_MISMATCH")
        route = self._route(request.domain)
        ordered_observations = tuple(sorted(observations, key=lambda item: item.observation_id))
        incoming_ids = tuple(sorted({item.observation_id for item in ordered_observations}))

        if readiness.status is ReadinessStatus.BLOCKED:
            blockers = ("DOMAIN_OPERATIONAL_READINESS_BLOCKED", *readiness.blockers)
            return CanonicalReconciliationResult(
                request_id=request.request_id,
                domain=request.domain,
                as_of=boundary,
                route=route,
                data_plane_snapshot_id=readiness_snapshot.snapshot_id,
                domain_readiness_id=readiness.readiness_id,
                status=ReadinessStatus.BLOCKED,
                eligibility=(),
                incoming_observation_ids=incoming_ids,
                eligible_observation_ids=(),
                excluded_observation_ids=incoming_ids,
                canonical_state=None,
                blockers=blockers,
                warnings=readiness.warnings,
            )

        runtime_by_provider = self._runtime_by_provider(readiness)
        eligibility: list[ObservationEligibilityAssessment] = []
        eligible_observations: list[ProviderObservation] = []
        eligibility_blockers: list[str] = []
        eligibility_warnings: list[str] = []

        for observation in ordered_observations:
            runtime = runtime_by_provider.get(observation.provider_id)
            if runtime is None:
                reason = "PROVIDER_NOT_ASSESSED_FOR_DOMAIN"
                eligibility_blockers.append(f"{reason}:{observation.provider_id}")
                eligibility.append(
                    ObservationEligibilityAssessment(
                        observation_id=observation.observation_id,
                        provider_id=observation.provider_id,
                        independence_group=observation.independence_group,
                        eligible=False,
                        runtime_status=None,
                        runtime_assessment_id=None,
                        reasons=(reason,),
                    )
                )
                continue
            if not runtime.usable:
                reason = f"PROVIDER_RUNTIME_{runtime.status.value}"
                eligibility_warnings.append(
                    f"OBSERVATION_EXCLUDED_{runtime.status.value}:{observation.provider_id}"
                )
                eligibility.append(
                    ObservationEligibilityAssessment(
                        observation_id=observation.observation_id,
                        provider_id=observation.provider_id,
                        independence_group=observation.independence_group,
                        eligible=False,
                        runtime_status=runtime.status,
                        runtime_assessment_id=runtime.assessment_id,
                        reasons=(reason,),
                    )
                )
                continue
            eligibility.append(
                ObservationEligibilityAssessment(
                    observation_id=observation.observation_id,
                    provider_id=observation.provider_id,
                    independence_group=observation.independence_group,
                    eligible=True,
                    runtime_status=runtime.status,
                    runtime_assessment_id=runtime.assessment_id,
                )
            )
            eligible_observations.append(observation)

        eligible_ids = tuple(sorted({item.observation_id for item in eligible_observations}))
        excluded_ids = tuple(sorted(set(incoming_ids) - set(eligible_ids)))
        if eligibility_blockers:
            return CanonicalReconciliationResult(
                request_id=request.request_id,
                domain=request.domain,
                as_of=boundary,
                route=route,
                data_plane_snapshot_id=readiness_snapshot.snapshot_id,
                domain_readiness_id=readiness.readiness_id,
                status=ReadinessStatus.BLOCKED,
                eligibility=tuple(eligibility),
                incoming_observation_ids=incoming_ids,
                eligible_observation_ids=eligible_ids,
                excluded_observation_ids=excluded_ids,
                canonical_state=None,
                blockers=tuple(eligibility_blockers),
                warnings=(*readiness.warnings, *eligibility_warnings),
            )

        if route is CanonicalRoute.MARKET_BAR:
            canonical_state: CanonicalState = self.market_reconciler.reconcile_bar(
                request,
                tuple(eligible_observations),
                policy=market_policy or MarketReconciliationPolicy(),
            )
        elif route is CanonicalRoute.MARKET_QUOTE:
            canonical_state = self.market_reconciler.reconcile_quote(
                request,
                tuple(eligible_observations),
                policy=market_policy or MarketReconciliationPolicy(),
            )
        else:
            canonical_state = self.research_reconciler.reconcile(
                request,
                tuple(eligible_observations),
                policy=research_policy,
            )

        blockers = tuple(canonical_state.blockers)
        warnings = tuple(
            sorted({*readiness.warnings, *eligibility_warnings, *canonical_state.warnings})
        )
        if canonical_state.status is ReadinessStatus.BLOCKED or blockers:
            status = ReadinessStatus.BLOCKED
        elif readiness.status is ReadinessStatus.WARNING or warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS

        return CanonicalReconciliationResult(
            request_id=request.request_id,
            domain=request.domain,
            as_of=boundary,
            route=route,
            data_plane_snapshot_id=readiness_snapshot.snapshot_id,
            domain_readiness_id=readiness.readiness_id,
            status=status,
            eligibility=tuple(eligibility),
            incoming_observation_ids=incoming_ids,
            eligible_observation_ids=eligible_ids,
            excluded_observation_ids=excluded_ids,
            canonical_state=canonical_state,
            blockers=blockers,
            warnings=warnings,
        )
