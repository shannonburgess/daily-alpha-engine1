"""Primary-source-first reconciliation for material Daily Alpha events.

Scheduled events may occur after the evaluation boundary; what matters for
point-in-time integrity is when the event information was published and received.
Regulatory, issuer, and exchange primary sources outrank normalized vendor copies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import EvidenceStatus, ReadinessStatus
from .data_providers import (
    DataDomain,
    DataProviderError,
    DataRequest,
    ProviderObservation,
    ProviderRegistry,
    ProviderRole,
)


class EventDataError(ValueError):
    """Material event data cannot be normalized or reconciled safely."""


class SourceAuthority(StrEnum):
    REGULATOR_PRIMARY = "REGULATOR_PRIMARY"
    ISSUER_PRIMARY = "ISSUER_PRIMARY"
    EXCHANGE_PRIMARY = "EXCHANGE_PRIMARY"
    VENDOR_NORMALIZED = "VENDOR_NORMALIZED"
    SECONDARY = "SECONDARY"


_PRIMARY_AUTHORITIES = {
    SourceAuthority.REGULATOR_PRIMARY,
    SourceAuthority.ISSUER_PRIMARY,
    SourceAuthority.EXCHANGE_PRIMARY,
}

_AUTHORITY_PRIORITY = {
    SourceAuthority.REGULATOR_PRIMARY: 0,
    SourceAuthority.ISSUER_PRIMARY: 1,
    SourceAuthority.EXCHANGE_PRIMARY: 2,
    SourceAuthority.VENDOR_NORMALIZED: 3,
    SourceAuthority.SECONDARY: 4,
}

_ROLE_PRIORITY = {
    ProviderRole.PRIMARY: 0,
    ProviderRole.SECONDARY: 1,
    ProviderRole.BROKER_REFERENCE: 2,
    ProviderRole.OPTIONAL: 3,
}

_EVENT_DOMAINS = {
    DataDomain.CORPORATE_ACTIONS,
    DataDomain.EARNINGS_EVENTS,
    DataDomain.SEC_FILINGS,
}


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventDataError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _parse_aware_iso(value: Any, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise EventDataError(f"{field_name}_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EventDataError(f"{field_name}_INVALID") from exc
    return _aware_utc(parsed, field_name)


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
        raise EventDataError("EVENT_VALUE_NOT_CANONICAL_JSON") from exc


def _security_id_from_subject(subject_key: str) -> str:
    prefix = "SECURITY:"
    if not subject_key.startswith(prefix):
        raise EventDataError("MATERIAL_EVENT_REQUIRES_SECURITY_SUBJECT")
    security_id = subject_key[len(prefix) :].strip().upper()
    if not security_id:
        raise EventDataError("MATERIAL_EVENT_SECURITY_ID_REQUIRED")
    return security_id


@dataclass(frozen=True)
class EventCandidate:
    """Normalized source assertion about one material event."""

    security_id: str
    domain: DataDomain
    event_key: str
    event_type: str
    event_time: datetime
    published_at: datetime
    known_at: datetime
    authority: SourceAuthority
    facts: dict[str, Any]
    provider_id: str
    independence_group: str
    source_version: str
    primary_document_id: str | None
    observation_id: str
    confidence: float

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        event_key = self.event_key.strip().upper()
        event_type = self.event_type.strip().upper()
        provider_id = self.provider_id.strip().upper()
        group = self.independence_group.strip().upper()
        source_version = self.source_version.strip()
        document_id = self.primary_document_id.strip() if self.primary_document_id else None
        if not security_id:
            raise EventDataError("EVENT_SECURITY_ID_REQUIRED")
        if self.domain not in _EVENT_DOMAINS:
            raise EventDataError("EVENT_DOMAIN_UNSUPPORTED")
        if not event_key:
            raise EventDataError("EVENT_KEY_REQUIRED")
        if not event_type:
            raise EventDataError("EVENT_TYPE_REQUIRED")
        if not provider_id:
            raise EventDataError("EVENT_PROVIDER_ID_REQUIRED")
        if not group:
            raise EventDataError("EVENT_INDEPENDENCE_GROUP_REQUIRED")
        if not source_version:
            raise EventDataError("EVENT_SOURCE_VERSION_REQUIRED")
        if self.authority in _PRIMARY_AUTHORITIES and not document_id:
            raise EventDataError("PRIMARY_EVENT_DOCUMENT_ID_REQUIRED")
        event_time = _aware_utc(self.event_time, "EVENT_TIME")
        published_at = _aware_utc(self.published_at, "EVENT_PUBLISHED_AT")
        known_at = _aware_utc(self.known_at, "EVENT_KNOWN_AT")
        if known_at < published_at:
            raise EventDataError("EVENT_KNOWN_AT_PRECEDES_PUBLICATION")
        if not isinstance(self.facts, dict):
            raise EventDataError("EVENT_FACTS_MUST_BE_OBJECT")
        _canonical_json(self.facts)
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "event_key", event_key)
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "independence_group", group)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "primary_document_id", document_id)
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "published_at", published_at)
        object.__setattr__(self, "known_at", known_at)

    @classmethod
    def from_observation(cls, observation: ProviderObservation) -> EventCandidate:
        if observation.domain not in _EVENT_DOMAINS:
            raise EventDataError("EVENT_OBSERVATION_DOMAIN_UNSUPPORTED")
        if not isinstance(observation.value, dict):
            raise EventDataError("EVENT_OBSERVATION_VALUE_MUST_BE_OBJECT")
        value = observation.value
        try:
            authority = SourceAuthority(str(value.get("authority") or "").strip().upper())
        except ValueError as exc:
            raise EventDataError("EVENT_AUTHORITY_INVALID") from exc
        facts = value.get("facts")
        if not isinstance(facts, dict):
            raise EventDataError("EVENT_FACTS_MUST_BE_OBJECT")
        return cls(
            security_id=_security_id_from_subject(observation.subject_key),
            domain=observation.domain,
            event_key=str(value.get("event_key") or ""),
            event_type=str(value.get("event_type") or ""),
            event_time=_parse_aware_iso(value.get("event_time"), "EVENT_TIME"),
            published_at=_parse_aware_iso(value.get("published_at"), "EVENT_PUBLISHED_AT"),
            known_at=observation.received_at,
            authority=authority,
            facts=facts,
            provider_id=observation.provider_id,
            independence_group=observation.independence_group,
            source_version=observation.source_version,
            primary_document_id=(
                str(value.get("primary_document_id") or "").strip() or None
            ),
            observation_id=observation.observation_id,
            confidence=observation.confidence,
        )

    @property
    def fact_hash(self) -> str:
        payload = {
            "security_id": self.security_id,
            "domain": self.domain.value,
            "event_key": self.event_key,
            "event_type": self.event_type,
            "event_time": self.event_time.isoformat(),
            "facts": self.facts,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @property
    def candidate_id(self) -> str:
        payload = {
            "fact_hash": self.fact_hash,
            "provider_id": self.provider_id,
            "independence_group": self.independence_group,
            "source_version": self.source_version,
            "authority": self.authority.value,
            "published_at": self.published_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "primary_document_id": self.primary_document_id,
            "observation_id": self.observation_id,
            "confidence": self.confidence,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "domain": self.domain.value,
            "event_key": self.event_key,
            "event_type": self.event_type,
            "event_time": self.event_time.isoformat(),
            "published_at": self.published_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "authority": self.authority.value,
            "facts": self.facts,
            "provider_id": self.provider_id,
            "independence_group": self.independence_group,
            "source_version": self.source_version,
            "primary_document_id": self.primary_document_id,
            "observation_id": self.observation_id,
            "confidence": self.confidence,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True)
class EventReconciliationPolicy:
    require_primary_source: bool
    allowed_primary_authorities: tuple[SourceAuthority, ...]
    min_independent_vendor_groups: int = 2

    def __post_init__(self) -> None:
        allowed = tuple(sorted(set(self.allowed_primary_authorities), key=lambda item: item.value))
        if any(item not in _PRIMARY_AUTHORITIES for item in allowed):
            raise EventDataError("EVENT_POLICY_PRIMARY_AUTHORITY_INVALID")
        if self.require_primary_source and not allowed:
            raise EventDataError("EVENT_POLICY_REQUIRED_PRIMARY_AUTHORITIES_EMPTY")
        if self.min_independent_vendor_groups <= 0:
            raise EventDataError("EVENT_POLICY_VENDOR_GROUPS_MUST_BE_POSITIVE")
        object.__setattr__(self, "allowed_primary_authorities", allowed)


def default_event_policy(domain: DataDomain) -> EventReconciliationPolicy:
    if domain is DataDomain.SEC_FILINGS:
        return EventReconciliationPolicy(
            require_primary_source=True,
            allowed_primary_authorities=(SourceAuthority.REGULATOR_PRIMARY,),
        )
    if domain is DataDomain.CORPORATE_ACTIONS:
        return EventReconciliationPolicy(
            require_primary_source=True,
            allowed_primary_authorities=(
                SourceAuthority.REGULATOR_PRIMARY,
                SourceAuthority.ISSUER_PRIMARY,
                SourceAuthority.EXCHANGE_PRIMARY,
            ),
        )
    if domain is DataDomain.EARNINGS_EVENTS:
        return EventReconciliationPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(SourceAuthority.ISSUER_PRIMARY,),
            min_independent_vendor_groups=2,
        )
    raise EventDataError("EVENT_POLICY_DOMAIN_UNSUPPORTED")


@dataclass(frozen=True)
class CanonicalEventState:
    security_id: str
    domain: DataDomain
    metric: str
    as_of: datetime
    event_key: str | None
    status: ReadinessStatus
    canonical_candidate: dict[str, object] | None
    canonical_authority: SourceAuthority | None
    candidate_ids: tuple[str, ...]
    selected_provider_ids: tuple[str, ...]
    independence_groups: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        metric = self.metric.strip().upper()
        event_key = self.event_key.strip().upper() if self.event_key else None
        boundary = _aware_utc(self.as_of, "CANONICAL_EVENT_AS_OF")
        if not security_id:
            raise EventDataError("CANONICAL_EVENT_SECURITY_ID_REQUIRED")
        if self.domain not in _EVENT_DOMAINS:
            raise EventDataError("CANONICAL_EVENT_DOMAIN_UNSUPPORTED")
        if not metric:
            raise EventDataError("CANONICAL_EVENT_METRIC_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise EventDataError("CANONICAL_EVENT_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED and self.canonical_candidate is not None:
            raise EventDataError("BLOCKED_EVENT_STATE_CANNOT_HAVE_CANONICAL_CANDIDATE")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "event_key", event_key)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "candidate_ids", tuple(sorted(self.candidate_ids)))
        object.__setattr__(self, "selected_provider_ids", tuple(sorted(self.selected_provider_ids)))
        object.__setattr__(self, "independence_groups", tuple(sorted(self.independence_groups)))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def state_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "domain": self.domain.value,
            "metric": self.metric,
            "as_of": self.as_of.isoformat(),
            "event_key": self.event_key,
            "status": self.status.value,
            "canonical_candidate": self.canonical_candidate,
            "canonical_authority": (
                self.canonical_authority.value if self.canonical_authority else None
            ),
            "candidate_ids": list(self.candidate_ids),
            "selected_provider_ids": list(self.selected_provider_ids),
            "independence_groups": list(self.independence_groups),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class EventReconciler:
    """Reconcile material events using primary-source authority and corroboration."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def reconcile(
        self,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        *,
        policy: EventReconciliationPolicy | None = None,
    ) -> CanonicalEventState:
        if request.domain not in _EVENT_DOMAINS:
            raise EventDataError("EVENT_RECONCILIATION_DOMAIN_UNSUPPORTED")
        active_policy = policy or default_event_policy(request.domain)
        candidates: list[EventCandidate] = []
        blockers: list[str] = []
        warnings: list[str] = []

        by_group: dict[str, list[tuple[ProviderObservation, EventCandidate]]] = {}
        for observation in observations:
            try:
                observation.validate_against(request)
                definition = self.registry.get(observation.provider_id)
            except DataProviderError as exc:
                blockers.append(f"EVENT_OBSERVATION_CONTRACT_ERROR:{observation.provider_id}:{exc}")
                continue
            capability = definition.capability_for(request.domain)
            if capability is None:
                blockers.append(f"EVENT_PROVIDER_DOMAIN_UNREGISTERED:{observation.provider_id}")
                continue
            if definition.independence_group != observation.independence_group:
                blockers.append(f"EVENT_PROVIDER_GROUP_MISMATCH:{observation.provider_id}")
                continue
            if observation.status is not EvidenceStatus.COMPLETE:
                warnings.append(
                    f"EVENT_SOURCE_EXCLUDED:{observation.provider_id}:{observation.status.value}"
                )
                continue
            try:
                candidate = EventCandidate.from_observation(observation)
            except EventDataError as exc:
                blockers.append(f"INVALID_EVENT_CANDIDATE:{observation.provider_id}:{exc}")
                continue
            if candidate.published_at > request.as_of or candidate.known_at > request.as_of:
                blockers.append(f"FUTURE_EVENT_INFORMATION_NOT_ALLOWED:{observation.provider_id}")
                continue
            candidates.append(candidate)
            by_group.setdefault(candidate.independence_group, []).append((observation, candidate))

        selected_pairs: list[tuple[ProviderObservation, EventCandidate]] = []
        for group in sorted(by_group):
            selected_pairs.append(max(by_group[group], key=self._pair_rank))
        selected = [candidate for _, candidate in selected_pairs]

        event_keys = {candidate.event_key for candidate in selected}
        if len(event_keys) > 1:
            blockers.append("EVENT_KEY_CONFLICT")
        event_key = next(iter(event_keys), None)

        primary = [candidate for candidate in selected if candidate.authority in _PRIMARY_AUTHORITIES]
        canonical: EventCandidate | None = None
        if primary:
            canonical = max(primary, key=self._candidate_rank)
            if canonical.authority not in active_policy.allowed_primary_authorities:
                blockers.append(
                    f"PRIMARY_AUTHORITY_NOT_ALLOWED:{request.domain.value}:{canonical.authority.value}"
                )
            for candidate in primary:
                if candidate.candidate_id == canonical.candidate_id:
                    continue
                if candidate.fact_hash != canonical.fact_hash:
                    blockers.append(
                        f"PRIMARY_EVENT_CONFLICT:{canonical.provider_id}:{candidate.provider_id}"
                    )
            for candidate in selected:
                if candidate.authority in _PRIMARY_AUTHORITIES:
                    continue
                if candidate.fact_hash != canonical.fact_hash:
                    warnings.append(
                        f"SECONDARY_EVENT_CONFLICT_WITH_PRIMARY:{candidate.provider_id}"
                    )
        else:
            if active_policy.require_primary_source:
                blockers.append(f"PRIMARY_SOURCE_REQUIRED:{request.domain.value}")
            vendor_groups = {candidate.independence_group for candidate in selected}
            if len(vendor_groups) < active_policy.min_independent_vendor_groups:
                blockers.append(
                    f"INSUFFICIENT_VENDOR_CORROBORATION:{len(vendor_groups)}<"
                    f"{active_policy.min_independent_vendor_groups}"
                )
            hashes = {candidate.fact_hash for candidate in selected}
            if len(hashes) > 1:
                blockers.append("VENDOR_EVENT_CONFLICT")
            if selected and not blockers:
                canonical = max(selected, key=self._candidate_rank)
                warnings.append(f"NO_PRIMARY_SOURCE:{request.domain.value}")

        if blockers:
            status = ReadinessStatus.BLOCKED
            canonical_payload = None
            canonical_authority = None
        elif warnings:
            status = ReadinessStatus.WARNING
            canonical_payload = canonical.to_payload() if canonical else None
            canonical_authority = canonical.authority if canonical else None
        else:
            if canonical is None:
                blockers.append("CANONICAL_EVENT_CANDIDATE_MISSING")
                status = ReadinessStatus.BLOCKED
                canonical_payload = None
                canonical_authority = None
            else:
                status = ReadinessStatus.PASS
                canonical_payload = canonical.to_payload()
                canonical_authority = canonical.authority

        return CanonicalEventState(
            security_id=_security_id_from_subject(request.subject_key),
            domain=request.domain,
            metric=request.metric,
            as_of=request.as_of,
            event_key=event_key,
            status=status,
            canonical_candidate=canonical_payload,
            canonical_authority=canonical_authority,
            candidate_ids=tuple(candidate.candidate_id for candidate in candidates),
            selected_provider_ids=tuple(candidate.provider_id for candidate in selected),
            independence_groups=tuple(candidate.independence_group for candidate in selected),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _pair_rank(
        self,
        pair: tuple[ProviderObservation, EventCandidate],
    ) -> tuple[object, ...]:
        observation, candidate = pair
        definition = self.registry.get(observation.provider_id)
        capability = definition.capability_for(observation.domain)
        if capability is None:
            raise EventDataError("EVENT_PROVIDER_CAPABILITY_MISSING")
        return (
            -_AUTHORITY_PRIORITY[candidate.authority],
            -_ROLE_PRIORITY[capability.role],
            candidate.confidence,
            candidate.published_at,
            candidate.known_at,
            candidate.provider_id,
        )

    def _candidate_rank(self, candidate: EventCandidate) -> tuple[object, ...]:
        definition = self.registry.get(candidate.provider_id)
        capability = definition.capability_for(candidate.domain)
        if capability is None:
            raise EventDataError("EVENT_PROVIDER_CAPABILITY_MISSING")
        return (
            -_AUTHORITY_PRIORITY[candidate.authority],
            -_ROLE_PRIORITY[capability.role],
            candidate.confidence,
            candidate.published_at,
            candidate.known_at,
            candidate.provider_id,
        )
