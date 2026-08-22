"""Provider-agnostic institutional data contracts for Daily Alpha.

Daily Alpha owns the canonical request/observation contract. External vendors,
primary sources, brokers, and future internal feeds implement adapters to this
contract rather than leaking vendor schemas into research, portfolio, or agent code.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from .contracts import EvidenceStatus


class DataProviderError(ValueError):
    """Provider metadata or observations violate the institutional data contract."""


class DataDomain(StrEnum):
    MARKET_BARS = "MARKET_BARS"
    MARKET_QUOTES = "MARKET_QUOTES"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    EARNINGS_EVENTS = "EARNINGS_EVENTS"
    SEC_FILINGS = "SEC_FILINGS"
    FUNDAMENTALS = "FUNDAMENTALS"
    ESTIMATES_REVISIONS = "ESTIMATES_REVISIONS"
    MACRO = "MACRO"
    NEWS_CATALYSTS = "NEWS_CATALYSTS"
    INSTITUTIONAL = "INSTITUTIONAL"
    BEHAVIORAL = "BEHAVIORAL"
    PORTFOLIO_ACCOUNT = "PORTFOLIO_ACCOUNT"
    OPTIONS_CHAIN = "OPTIONS_CHAIN"


class ProviderRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    BROKER_REFERENCE = "BROKER_REFERENCE"
    OPTIONAL = "OPTIONAL"


class SubjectType(StrEnum):
    SECURITY = "SECURITY"
    GLOBAL = "GLOBAL"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataProviderError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise DataProviderError("PROVIDER_VALUE_NOT_CANONICAL_JSON") from exc


def _normalize_pairs(
    pairs: tuple[tuple[str, str], ...] | dict[str, str],
) -> tuple[tuple[str, str], ...]:
    items = pairs.items() if isinstance(pairs, dict) else pairs
    normalized = tuple(sorted((str(key).strip(), str(value).strip()) for key, value in items))
    if any(not key for key, _ in normalized):
        raise DataProviderError("PROVIDER_PROVENANCE_KEY_REQUIRED")
    if len({key for key, _ in normalized}) != len(normalized):
        raise DataProviderError("PROVIDER_PROVENANCE_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True)
class DataRequest:
    """Vendor-neutral, point-in-time data request."""

    domain: DataDomain
    metric: str
    as_of: datetime
    subject_type: SubjectType
    security_id: str | None = None
    global_series_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    def __post_init__(self) -> None:
        metric = self.metric.strip().upper()
        if not metric:
            raise DataProviderError("DATA_REQUEST_METRIC_REQUIRED")
        boundary = _aware_utc(self.as_of, "DATA_REQUEST_AS_OF")
        security_id = self.security_id.strip().upper() if self.security_id else None
        series_id = self.global_series_id.strip().upper() if self.global_series_id else None

        if self.subject_type is SubjectType.SECURITY:
            if not security_id or series_id is not None:
                raise DataProviderError("SECURITY_REQUEST_REQUIRES_ONLY_SECURITY_ID")
        elif self.subject_type is SubjectType.GLOBAL and (
            not series_id or security_id is not None
        ):
            raise DataProviderError("GLOBAL_REQUEST_REQUIRES_ONLY_SERIES_ID")
        elif self.subject_type not in {SubjectType.SECURITY, SubjectType.GLOBAL}:
            raise DataProviderError("DATA_REQUEST_SUBJECT_TYPE_INVALID")

        start = _aware_utc(self.start_at, "DATA_REQUEST_START_AT") if self.start_at else None
        end = _aware_utc(self.end_at, "DATA_REQUEST_END_AT") if self.end_at else None
        if start and end and end <= start:
            raise DataProviderError("DATA_REQUEST_END_MUST_FOLLOW_START")
        if end and end > boundary:
            raise DataProviderError("DATA_REQUEST_END_AFTER_AS_OF")

        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "global_series_id", series_id)
        object.__setattr__(self, "start_at", start)
        object.__setattr__(self, "end_at", end)

    @property
    def subject_key(self) -> str:
        if self.subject_type is SubjectType.SECURITY:
            return f"SECURITY:{self.security_id}"
        return f"GLOBAL:{self.global_series_id}"

    @property
    def request_id(self) -> str:
        payload = {
            "domain": self.domain.value,
            "metric": self.metric,
            "as_of": self.as_of.isoformat(),
            "subject_type": self.subject_type.value,
            "subject_key": self.subject_key,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, order=True)
class ProviderCapability:
    domain: DataDomain
    role: ProviderRole
    cadence_seconds: int
    max_freshness_seconds: int
    supports_point_in_time_history: bool

    def __post_init__(self) -> None:
        if self.cadence_seconds <= 0:
            raise DataProviderError("PROVIDER_CADENCE_MUST_BE_POSITIVE")
        if self.max_freshness_seconds <= 0:
            raise DataProviderError("PROVIDER_FRESHNESS_MUST_BE_POSITIVE")


@dataclass(frozen=True)
class ProviderDefinition:
    """Stable description of one provider adapter.

    `independence_group` identifies the upstream source family. Two provider adapters
    in the same group do not count as independent redundancy.
    """

    provider_id: str
    display_name: str
    independence_group: str
    source_version: str
    capabilities: tuple[ProviderCapability, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip().upper()
        display_name = self.display_name.strip()
        group = self.independence_group.strip().upper()
        source_version = self.source_version.strip()
        if not provider_id:
            raise DataProviderError("PROVIDER_ID_REQUIRED")
        if not display_name:
            raise DataProviderError("PROVIDER_DISPLAY_NAME_REQUIRED")
        if not group:
            raise DataProviderError("PROVIDER_INDEPENDENCE_GROUP_REQUIRED")
        if not source_version:
            raise DataProviderError("PROVIDER_SOURCE_VERSION_REQUIRED")
        if not self.capabilities:
            raise DataProviderError("PROVIDER_CAPABILITIES_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DataProviderError("PROVIDER_DEFINITION_MUST_REMAIN_RESEARCH_ONLY")
        capabilities = tuple(
            sorted(
                set(self.capabilities),
                key=lambda item: (item.domain.value, item.role.value),
            )
        )
        if len({item.domain for item in capabilities}) != len(capabilities):
            raise DataProviderError("PROVIDER_DOMAIN_CAPABILITY_DUPLICATE")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "independence_group", group)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "capabilities", capabilities)

    def capability_for(self, domain: DataDomain) -> ProviderCapability | None:
        return next((item for item in self.capabilities if item.domain is domain), None)

    @property
    def definition_id(self) -> str:
        payload = {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "independence_group": self.independence_group,
            "source_version": self.source_version,
            "capabilities": [
                {
                    "domain": item.domain.value,
                    "role": item.role.value,
                    "cadence_seconds": item.cadence_seconds,
                    "max_freshness_seconds": item.max_freshness_seconds,
                    "supports_point_in_time_history": item.supports_point_in_time_history,
                }
                for item in self.capabilities
            ],
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderObservation:
    """Canonical output from any institutional data provider adapter."""

    provider_id: str
    independence_group: str
    domain: DataDomain
    metric: str
    subject_key: str
    value: Any
    observed_at: datetime
    received_at: datetime
    source_version: str
    status: EvidenceStatus = EvidenceStatus.COMPLETE
    confidence: float = 1.0
    reason_code: str | None = None
    provenance: tuple[tuple[str, str], ...] | dict[str, str] = field(default_factory=tuple)
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip().upper()
        group = self.independence_group.strip().upper()
        metric = self.metric.strip().upper()
        subject = self.subject_key.strip().upper()
        source_version = self.source_version.strip()
        if not provider_id:
            raise DataProviderError("OBSERVATION_PROVIDER_ID_REQUIRED")
        if not group:
            raise DataProviderError("OBSERVATION_INDEPENDENCE_GROUP_REQUIRED")
        if not metric:
            raise DataProviderError("OBSERVATION_METRIC_REQUIRED")
        if not subject.startswith(("SECURITY:", "GLOBAL:")):
            raise DataProviderError("OBSERVATION_SUBJECT_KEY_INVALID")
        if not source_version:
            raise DataProviderError("OBSERVATION_SOURCE_VERSION_REQUIRED")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise DataProviderError("OBSERVATION_CONFIDENCE_OUT_OF_RANGE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DataProviderError("PROVIDER_OBSERVATION_MUST_REMAIN_RESEARCH_ONLY")
        observed = _aware_utc(self.observed_at, "OBSERVATION_OBSERVED_AT")
        received = _aware_utc(self.received_at, "OBSERVATION_RECEIVED_AT")
        if received < observed:
            raise DataProviderError("OBSERVATION_RECEIVED_BEFORE_OBSERVED")
        _canonical_json(self.value)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "independence_group", group)
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "subject_key", subject)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "received_at", received)
        object.__setattr__(self, "provenance", _normalize_pairs(self.provenance))
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", self.reason_code.strip().upper() or None)

    def validate_against(self, request: DataRequest) -> None:
        if self.domain is not request.domain:
            raise DataProviderError("OBSERVATION_DOMAIN_REQUEST_MISMATCH")
        if self.metric != request.metric:
            raise DataProviderError("OBSERVATION_METRIC_REQUEST_MISMATCH")
        if self.subject_key != request.subject_key:
            raise DataProviderError("OBSERVATION_SUBJECT_REQUEST_MISMATCH")
        if self.observed_at > request.as_of or self.received_at > request.as_of:
            raise DataProviderError("FUTURE_PROVIDER_OBSERVATION_NOT_ALLOWED")

    @property
    def observation_id(self) -> str:
        payload = {
            "provider_id": self.provider_id,
            "independence_group": self.independence_group,
            "domain": self.domain.value,
            "metric": self.metric,
            "subject_key": self.subject_key,
            "value": self.value,
            "observed_at": self.observed_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "source_version": self.source_version,
            "status": self.status.value,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "provenance": list(self.provenance),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class InstitutionalDataProvider(Protocol):
    """Minimal adapter interface implemented by every data source."""

    @property
    def definition(self) -> ProviderDefinition: ...

    def fetch(self, request: DataRequest) -> tuple[ProviderObservation, ...]: ...


@dataclass(frozen=True)
class RedundancyPolicy:
    domain: DataDomain
    min_independent_groups: int
    required_roles: tuple[ProviderRole, ...] = ()

    def __post_init__(self) -> None:
        if self.min_independent_groups <= 0:
            raise DataProviderError("REDUNDANCY_MIN_GROUPS_MUST_BE_POSITIVE")
        object.__setattr__(self, "required_roles", tuple(sorted(set(self.required_roles))))


@dataclass(frozen=True)
class ProviderCoverageAssessment:
    domain: DataDomain
    provider_ids: tuple[str, ...]
    independence_groups: tuple[str, ...]
    roles_present: tuple[ProviderRole, ...]
    required_independent_groups: int
    required_roles: tuple[ProviderRole, ...]
    complete: bool
    blockers: tuple[str, ...]


class ProviderRegistry:
    """Deterministic vendor-independent provider registry and redundancy auditor."""

    def __init__(self, definitions: tuple[ProviderDefinition, ...] = ()) -> None:
        self._definitions: dict[str, ProviderDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ProviderDefinition) -> None:
        existing = self._definitions.get(definition.provider_id)
        if existing is None:
            self._definitions[definition.provider_id] = definition
            return
        if existing != definition:
            raise DataProviderError(f"PROVIDER_DEFINITION_CONFLICT:{definition.provider_id}")

    def get(self, provider_id: str) -> ProviderDefinition:
        key = provider_id.strip().upper()
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise DataProviderError(f"PROVIDER_NOT_REGISTERED:{key}") from exc

    def providers_for(self, domain: DataDomain) -> tuple[ProviderDefinition, ...]:
        return tuple(
            sorted(
                (
                    definition
                    for definition in self._definitions.values()
                    if definition.capability_for(domain) is not None
                ),
                key=lambda item: item.provider_id,
            )
        )

    def assess_coverage(self, policy: RedundancyPolicy) -> ProviderCoverageAssessment:
        providers = self.providers_for(policy.domain)
        groups = tuple(sorted({item.independence_group for item in providers}))
        roles = tuple(
            sorted(
                {
                    capability.role
                    for item in providers
                    if (capability := item.capability_for(policy.domain)) is not None
                }
            )
        )
        blockers: list[str] = []
        if len(groups) < policy.min_independent_groups:
            blockers.append(
                f"INSUFFICIENT_INDEPENDENT_PROVIDER_GROUPS:{policy.domain.value}:"
                f"{len(groups)}<{policy.min_independent_groups}"
            )
        missing_roles = [role for role in policy.required_roles if role not in roles]
        blockers.extend(
            f"MISSING_REQUIRED_PROVIDER_ROLE:{policy.domain.value}:{role.value}"
            for role in missing_roles
        )
        return ProviderCoverageAssessment(
            domain=policy.domain,
            provider_ids=tuple(item.provider_id for item in providers),
            independence_groups=groups,
            roles_present=roles,
            required_independent_groups=policy.min_independent_groups,
            required_roles=policy.required_roles,
            complete=not blockers,
            blockers=tuple(sorted(blockers)),
        )

    @property
    def registry_id(self) -> str:
        payload = [
            {
                "provider_id": definition.provider_id,
                "definition_id": definition.definition_id,
            }
            for definition in sorted(
                self._definitions.values(), key=lambda item: item.provider_id
            )
        ]
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
