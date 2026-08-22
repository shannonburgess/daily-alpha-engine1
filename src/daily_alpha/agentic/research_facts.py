"""Point-in-time canonical research facts for Daily Alpha.

This layer covers investment research inputs that are informative but do not all have
the same epistemic authority. Primary facts, corroborated normalized facts, and
single-source alternative observations are explicitly distinguished rather than
flattened into one undifferentiated data stream.
"""

from __future__ import annotations

import hashlib
import json
import math
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
from .event_reconciliation import SourceAuthority


class ResearchFactError(ValueError):
    """Research fact data violates point-in-time or authority invariants."""


class ResearchFactQuality(StrEnum):
    VERIFIED_PRIMARY = "VERIFIED_PRIMARY"
    CORROBORATED = "CORROBORATED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    BLOCKED = "BLOCKED"


_RESEARCH_DOMAINS = {
    DataDomain.FUNDAMENTALS,
    DataDomain.ESTIMATES_REVISIONS,
    DataDomain.MACRO,
    DataDomain.NEWS_CATALYSTS,
    DataDomain.INSTITUTIONAL,
    DataDomain.BEHAVIORAL,
}

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


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchFactError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _parse_optional_aware_iso(value: Any, field_name: str) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResearchFactError(f"{field_name}_INVALID") from exc
    return _aware_utc(parsed, field_name)


def _parse_aware_iso(value: Any, field_name: str) -> datetime:
    result = _parse_optional_aware_iso(value, field_name)
    if result is None:
        raise ResearchFactError(f"{field_name}_REQUIRED")
    return result


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
        raise ResearchFactError("RESEARCH_FACT_NOT_CANONICAL_JSON") from exc


def _normalize_subject(subject_key: str) -> str:
    subject = subject_key.strip().upper()
    if not subject.startswith(("SECURITY:", "GLOBAL:")):
        raise ResearchFactError("RESEARCH_FACT_SUBJECT_INVALID")
    if subject.endswith(":"):
        raise ResearchFactError("RESEARCH_FACT_SUBJECT_REQUIRED")
    return subject


@dataclass(frozen=True)
class ResearchFactCandidate:
    subject_key: str
    domain: DataDomain
    metric: str
    fact_key: str
    fact_value: Any
    published_at: datetime
    known_at: datetime
    authority: SourceAuthority
    provider_id: str
    independence_group: str
    source_version: str
    observation_id: str
    confidence: float
    period_end: datetime | None = None
    unit: str | None = None
    revision_id: str | None = None
    primary_document_id: str | None = None

    def __post_init__(self) -> None:
        subject = _normalize_subject(self.subject_key)
        metric = self.metric.strip().upper()
        fact_key = self.fact_key.strip().upper()
        provider_id = self.provider_id.strip().upper()
        group = self.independence_group.strip().upper()
        source_version = self.source_version.strip()
        unit = self.unit.strip().upper() if self.unit else None
        revision_id = self.revision_id.strip() if self.revision_id else None
        document_id = self.primary_document_id.strip() if self.primary_document_id else None
        if self.domain not in _RESEARCH_DOMAINS:
            raise ResearchFactError("RESEARCH_FACT_DOMAIN_UNSUPPORTED")
        if not metric:
            raise ResearchFactError("RESEARCH_FACT_METRIC_REQUIRED")
        if not fact_key:
            raise ResearchFactError("RESEARCH_FACT_KEY_REQUIRED")
        if not provider_id:
            raise ResearchFactError("RESEARCH_FACT_PROVIDER_REQUIRED")
        if not group:
            raise ResearchFactError("RESEARCH_FACT_GROUP_REQUIRED")
        if not source_version:
            raise ResearchFactError("RESEARCH_FACT_SOURCE_VERSION_REQUIRED")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ResearchFactError("RESEARCH_FACT_CONFIDENCE_OUT_OF_RANGE")
        if self.authority in _PRIMARY_AUTHORITIES and not document_id:
            raise ResearchFactError("PRIMARY_RESEARCH_FACT_DOCUMENT_ID_REQUIRED")
        published = _aware_utc(self.published_at, "RESEARCH_FACT_PUBLISHED_AT")
        known = _aware_utc(self.known_at, "RESEARCH_FACT_KNOWN_AT")
        if known < published:
            raise ResearchFactError("RESEARCH_FACT_KNOWN_BEFORE_PUBLICATION")
        period_end = (
            _aware_utc(self.period_end, "RESEARCH_FACT_PERIOD_END")
            if self.period_end is not None
            else None
        )
        _canonical_json(self.fact_value)
        object.__setattr__(self, "subject_key", subject)
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "fact_key", fact_key)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "independence_group", group)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "primary_document_id", document_id)
        object.__setattr__(self, "published_at", published)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "period_end", period_end)

    @classmethod
    def from_observation(cls, observation: ProviderObservation) -> ResearchFactCandidate:
        if observation.domain not in _RESEARCH_DOMAINS:
            raise ResearchFactError("RESEARCH_OBSERVATION_DOMAIN_UNSUPPORTED")
        if not isinstance(observation.value, dict):
            raise ResearchFactError("RESEARCH_OBSERVATION_VALUE_MUST_BE_OBJECT")
        value = observation.value
        try:
            authority = SourceAuthority(str(value.get("authority") or "").strip().upper())
        except ValueError as exc:
            raise ResearchFactError("RESEARCH_FACT_AUTHORITY_INVALID") from exc
        if "fact_value" not in value:
            raise ResearchFactError("RESEARCH_FACT_VALUE_REQUIRED")
        return cls(
            subject_key=observation.subject_key,
            domain=observation.domain,
            metric=observation.metric,
            fact_key=str(value.get("fact_key") or ""),
            fact_value=value.get("fact_value"),
            published_at=_parse_aware_iso(value.get("published_at"), "RESEARCH_FACT_PUBLISHED_AT"),
            known_at=observation.received_at,
            authority=authority,
            provider_id=observation.provider_id,
            independence_group=observation.independence_group,
            source_version=observation.source_version,
            observation_id=observation.observation_id,
            confidence=observation.confidence,
            period_end=_parse_optional_aware_iso(
                value.get("period_end"), "RESEARCH_FACT_PERIOD_END"
            ),
            unit=str(value.get("unit") or "").strip() or None,
            revision_id=str(value.get("revision_id") or "").strip() or None,
            primary_document_id=(
                str(value.get("primary_document_id") or "").strip() or None
            ),
        )

    @property
    def fact_hash(self) -> str:
        payload = {
            "subject_key": self.subject_key,
            "domain": self.domain.value,
            "metric": self.metric,
            "fact_key": self.fact_key,
            "fact_value": self.fact_value,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "unit": self.unit,
            "revision_id": self.revision_id,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @property
    def candidate_id(self) -> str:
        payload = {
            "fact_hash": self.fact_hash,
            "published_at": self.published_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "authority": self.authority.value,
            "provider_id": self.provider_id,
            "independence_group": self.independence_group,
            "source_version": self.source_version,
            "observation_id": self.observation_id,
            "confidence": self.confidence,
            "primary_document_id": self.primary_document_id,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, object]:
        return {
            "subject_key": self.subject_key,
            "domain": self.domain.value,
            "metric": self.metric,
            "fact_key": self.fact_key,
            "fact_value": self.fact_value,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "unit": self.unit,
            "revision_id": self.revision_id,
            "published_at": self.published_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "authority": self.authority.value,
            "provider_id": self.provider_id,
            "independence_group": self.independence_group,
            "source_version": self.source_version,
            "observation_id": self.observation_id,
            "confidence": self.confidence,
            "primary_document_id": self.primary_document_id,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True)
class ResearchFactPolicy:
    require_primary_source: bool
    allowed_primary_authorities: tuple[SourceAuthority, ...]
    min_independent_groups: int = 2
    allow_single_source_warning: bool = True
    numeric_tolerance_abs: float | None = None

    def __post_init__(self) -> None:
        allowed = tuple(sorted(set(self.allowed_primary_authorities), key=lambda item: item.value))
        if any(item not in _PRIMARY_AUTHORITIES for item in allowed):
            raise ResearchFactError("RESEARCH_POLICY_PRIMARY_AUTHORITY_INVALID")
        if self.require_primary_source and not allowed:
            raise ResearchFactError("RESEARCH_POLICY_REQUIRED_PRIMARY_EMPTY")
        if self.min_independent_groups <= 0:
            raise ResearchFactError("RESEARCH_POLICY_MIN_GROUPS_MUST_BE_POSITIVE")
        if self.numeric_tolerance_abs is not None and self.numeric_tolerance_abs < 0:
            raise ResearchFactError("RESEARCH_POLICY_NUMERIC_TOLERANCE_NEGATIVE")
        object.__setattr__(self, "allowed_primary_authorities", allowed)


def default_research_fact_policy(domain: DataDomain) -> ResearchFactPolicy:
    if domain is DataDomain.FUNDAMENTALS:
        return ResearchFactPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(
                SourceAuthority.REGULATOR_PRIMARY,
                SourceAuthority.ISSUER_PRIMARY,
            ),
        )
    if domain is DataDomain.ESTIMATES_REVISIONS:
        return ResearchFactPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(),
            min_independent_groups=2,
            allow_single_source_warning=True,
        )
    if domain is DataDomain.MACRO:
        return ResearchFactPolicy(
            require_primary_source=True,
            allowed_primary_authorities=(SourceAuthority.REGULATOR_PRIMARY,),
            allow_single_source_warning=False,
        )
    if domain is DataDomain.NEWS_CATALYSTS:
        return ResearchFactPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(
                SourceAuthority.REGULATOR_PRIMARY,
                SourceAuthority.ISSUER_PRIMARY,
            ),
        )
    if domain is DataDomain.INSTITUTIONAL:
        return ResearchFactPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(SourceAuthority.REGULATOR_PRIMARY,),
        )
    if domain is DataDomain.BEHAVIORAL:
        return ResearchFactPolicy(
            require_primary_source=False,
            allowed_primary_authorities=(),
            min_independent_groups=2,
            allow_single_source_warning=True,
        )
    raise ResearchFactError("RESEARCH_POLICY_DOMAIN_UNSUPPORTED")


@dataclass(frozen=True)
class CanonicalResearchFactState:
    subject_key: str
    domain: DataDomain
    metric: str
    as_of: datetime
    fact_key: str | None
    status: ReadinessStatus
    quality: ResearchFactQuality
    canonical_candidate: dict[str, object] | None
    candidate_ids: tuple[str, ...]
    selected_provider_ids: tuple[str, ...]
    independence_groups: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        subject = _normalize_subject(self.subject_key)
        metric = self.metric.strip().upper()
        fact_key = self.fact_key.strip().upper() if self.fact_key else None
        boundary = _aware_utc(self.as_of, "CANONICAL_RESEARCH_AS_OF")
        if self.domain not in _RESEARCH_DOMAINS:
            raise ResearchFactError("CANONICAL_RESEARCH_DOMAIN_UNSUPPORTED")
        if not metric:
            raise ResearchFactError("CANONICAL_RESEARCH_METRIC_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ResearchFactError("CANONICAL_RESEARCH_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED and self.canonical_candidate is not None:
            raise ResearchFactError("BLOCKED_RESEARCH_STATE_CANNOT_HAVE_CANONICAL_CANDIDATE")
        object.__setattr__(self, "subject_key", subject)
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "fact_key", fact_key)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "candidate_ids", tuple(sorted(self.candidate_ids)))
        object.__setattr__(self, "selected_provider_ids", tuple(sorted(self.selected_provider_ids)))
        object.__setattr__(self, "independence_groups", tuple(sorted(self.independence_groups)))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def state_id(self) -> str:
        payload = {
            "subject_key": self.subject_key,
            "domain": self.domain.value,
            "metric": self.metric,
            "as_of": self.as_of.isoformat(),
            "fact_key": self.fact_key,
            "status": self.status.value,
            "quality": self.quality.value,
            "canonical_candidate": self.canonical_candidate,
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


class ResearchFactReconciler:
    """Reconcile point-in-time research facts without flattening source quality."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def reconcile(
        self,
        request: DataRequest,
        observations: tuple[ProviderObservation, ...],
        *,
        policy: ResearchFactPolicy | None = None,
    ) -> CanonicalResearchFactState:
        if request.domain not in _RESEARCH_DOMAINS:
            raise ResearchFactError("RESEARCH_RECONCILIATION_DOMAIN_UNSUPPORTED")
        active_policy = policy or default_research_fact_policy(request.domain)
        all_candidates: list[ResearchFactCandidate] = []
        blockers: list[str] = []
        warnings: list[str] = []
        by_group: dict[str, list[tuple[ProviderObservation, ResearchFactCandidate]]] = {}

        for observation in observations:
            try:
                observation.validate_against(request)
                definition = self.registry.get(observation.provider_id)
            except DataProviderError as exc:
                blockers.append(
                    f"RESEARCH_OBSERVATION_CONTRACT_ERROR:{observation.provider_id}:{exc}"
                )
                continue
            capability = definition.capability_for(request.domain)
            if capability is None:
                blockers.append(f"RESEARCH_PROVIDER_DOMAIN_UNREGISTERED:{observation.provider_id}")
                continue
            if definition.independence_group != observation.independence_group:
                blockers.append(f"RESEARCH_PROVIDER_GROUP_MISMATCH:{observation.provider_id}")
                continue
            if observation.status is not EvidenceStatus.COMPLETE:
                warnings.append(
                    f"RESEARCH_SOURCE_EXCLUDED:{observation.provider_id}:{observation.status.value}"
                )
                continue
            try:
                candidate = ResearchFactCandidate.from_observation(observation)
            except ResearchFactError as exc:
                blockers.append(f"INVALID_RESEARCH_FACT:{observation.provider_id}:{exc}")
                continue
            if candidate.published_at > request.as_of or candidate.known_at > request.as_of:
                blockers.append(f"FUTURE_RESEARCH_INFORMATION_NOT_ALLOWED:{observation.provider_id}")
                continue
            all_candidates.append(candidate)
            by_group.setdefault(candidate.independence_group, []).append((observation, candidate))

        selected_pairs = [
            max(by_group[group], key=self._pair_rank)
            for group in sorted(by_group)
        ]
        selected = [candidate for _, candidate in selected_pairs]
        fact_keys = {candidate.fact_key for candidate in selected}
        if len(fact_keys) > 1:
            blockers.append("RESEARCH_FACT_KEY_CONFLICT")
        fact_key = next(iter(fact_keys), None)

        primary = [candidate for candidate in selected if candidate.authority in _PRIMARY_AUTHORITIES]
        canonical: ResearchFactCandidate | None = None
        quality = ResearchFactQuality.BLOCKED

        if primary:
            canonical = max(primary, key=self._candidate_rank)
            if canonical.authority not in active_policy.allowed_primary_authorities:
                blockers.append(
                    f"RESEARCH_PRIMARY_AUTHORITY_NOT_ALLOWED:{request.domain.value}:"
                    f"{canonical.authority.value}"
                )
            for candidate in primary:
                if candidate.candidate_id == canonical.candidate_id:
                    continue
                if not _facts_agree(canonical, candidate, active_policy):
                    blockers.append(
                        f"RESEARCH_PRIMARY_CONFLICT:{canonical.provider_id}:{candidate.provider_id}"
                    )
            for candidate in selected:
                if candidate.authority in _PRIMARY_AUTHORITIES:
                    continue
                if not _facts_agree(canonical, candidate, active_policy):
                    warnings.append(
                        f"RESEARCH_SECONDARY_CONFLICT_WITH_PRIMARY:{candidate.provider_id}"
                    )
            quality = ResearchFactQuality.VERIFIED_PRIMARY
        else:
            if active_policy.require_primary_source:
                blockers.append(f"RESEARCH_PRIMARY_SOURCE_REQUIRED:{request.domain.value}")
            groups = {candidate.independence_group for candidate in selected}
            if len(selected) > 1:
                reference = max(selected, key=self._candidate_rank)
                if any(
                    not _facts_agree(reference, candidate, active_policy)
                    for candidate in selected
                    if candidate.candidate_id != reference.candidate_id
                ):
                    blockers.append("RESEARCH_NONPRIMARY_CONFLICT")
            if len(groups) >= active_policy.min_independent_groups and selected:
                canonical = max(selected, key=self._candidate_rank)
                quality = ResearchFactQuality.CORROBORATED
                warnings.append(f"RESEARCH_NO_PRIMARY_SOURCE:{request.domain.value}")
            elif len(groups) == 1 and selected and active_policy.allow_single_source_warning:
                canonical = selected[0]
                quality = ResearchFactQuality.SINGLE_SOURCE
                warnings.append(f"RESEARCH_SINGLE_SOURCE:{request.domain.value}")
            else:
                blockers.append(
                    f"RESEARCH_INSUFFICIENT_INDEPENDENT_SOURCES:{len(groups)}<"
                    f"{active_policy.min_independent_groups}"
                )

        if blockers:
            status = ReadinessStatus.BLOCKED
            quality = ResearchFactQuality.BLOCKED
            canonical_payload = None
        elif warnings:
            status = ReadinessStatus.WARNING
            canonical_payload = canonical.to_payload() if canonical else None
        else:
            if canonical is None:
                status = ReadinessStatus.BLOCKED
                quality = ResearchFactQuality.BLOCKED
                blockers.append("CANONICAL_RESEARCH_FACT_MISSING")
                canonical_payload = None
            else:
                status = ReadinessStatus.PASS
                canonical_payload = canonical.to_payload()

        return CanonicalResearchFactState(
            subject_key=request.subject_key,
            domain=request.domain,
            metric=request.metric,
            as_of=request.as_of,
            fact_key=fact_key,
            status=status,
            quality=quality,
            canonical_candidate=canonical_payload,
            candidate_ids=tuple(candidate.candidate_id for candidate in all_candidates),
            selected_provider_ids=tuple(candidate.provider_id for candidate in selected),
            independence_groups=tuple(candidate.independence_group for candidate in selected),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _pair_rank(
        self,
        pair: tuple[ProviderObservation, ResearchFactCandidate],
    ) -> tuple[object, ...]:
        observation, candidate = pair
        definition = self.registry.get(observation.provider_id)
        capability = definition.capability_for(observation.domain)
        if capability is None:
            raise ResearchFactError("RESEARCH_PROVIDER_CAPABILITY_MISSING")
        return (
            -_AUTHORITY_PRIORITY[candidate.authority],
            -_ROLE_PRIORITY[capability.role],
            candidate.confidence,
            candidate.published_at,
            candidate.known_at,
            candidate.provider_id,
        )

    def _candidate_rank(self, candidate: ResearchFactCandidate) -> tuple[object, ...]:
        definition = self.registry.get(candidate.provider_id)
        capability = definition.capability_for(candidate.domain)
        if capability is None:
            raise ResearchFactError("RESEARCH_PROVIDER_CAPABILITY_MISSING")
        return (
            -_AUTHORITY_PRIORITY[candidate.authority],
            -_ROLE_PRIORITY[capability.role],
            candidate.confidence,
            candidate.published_at,
            candidate.known_at,
            candidate.provider_id,
        )


def _facts_agree(
    left: ResearchFactCandidate,
    right: ResearchFactCandidate,
    policy: ResearchFactPolicy,
) -> bool:
    metadata_matches = (
        left.subject_key == right.subject_key
        and left.domain is right.domain
        and left.metric == right.metric
        and left.fact_key == right.fact_key
        and left.period_end == right.period_end
        and left.unit == right.unit
        and left.revision_id == right.revision_id
    )
    if not metadata_matches:
        return False
    tolerance = policy.numeric_tolerance_abs
    if tolerance is not None and isinstance(left.fact_value, (int, float)) and isinstance(
        right.fact_value, (int, float)
    ):
        return abs(float(left.fact_value) - float(right.fact_value)) <= tolerance
    return left.fact_hash == right.fact_hash
