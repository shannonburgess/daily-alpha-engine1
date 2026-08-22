"""Deterministic read-only command-center projections for Daily Alpha.

This module is intentionally decoupled from concrete Stage 9I packet classes so the
command-center contract can be built from the latest verified green institutional head.
Typed projection adapters can be added later without changing the UI/API-facing snapshot
schema. The command center is a projection of governed truth and cannot mutate research,
portfolio, PAPER, execution, capital, or live-trading state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus


class CommandCenterError(ValueError):
    """Command-center projection violates point-in-time or authority invariants."""


class CommandCenterComponentKind(StrEnum):
    DATA_PLANE = "DATA_PLANE"
    PROVIDER_RELIABILITY = "PROVIDER_RELIABILITY"
    MODEL_GOVERNANCE = "MODEL_GOVERNANCE"
    MODEL_STRESS = "MODEL_STRESS"
    MODEL_PERFORMANCE = "MODEL_PERFORMANCE"
    RESEARCH_COUNCIL = "RESEARCH_COUNCIL"
    CIO_DECISION = "CIO_DECISION"
    PORTFOLIO_PROPOSAL = "PORTFOLIO_PROPOSAL"
    RISK_GOVERNOR = "RISK_GOVERNOR"
    INCIDENT = "INCIDENT"


class CommandCenterEntityKind(StrEnum):
    PLATFORM = "PLATFORM"
    PORTFOLIO = "PORTFOLIO"
    SECURITY = "SECURITY"
    MODEL = "MODEL"
    PROVIDER = "PROVIDER"
    DECISION = "DECISION"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CommandCenterError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise CommandCenterError("COMMAND_CENTER_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item.strip().lower() for item in values if item.strip()}))


def _normalized_metrics(
    metrics: tuple[tuple[str, Any], ...] | dict[str, Any],
) -> tuple[tuple[str, Any], ...]:
    items = metrics.items() if isinstance(metrics, dict) else metrics
    normalized: list[tuple[str, Any]] = []
    for key, value in items:
        name = str(key).strip().lower()
        if not name:
            raise CommandCenterError("COMMAND_CENTER_METRIC_NAME_REQUIRED")
        _canonical_json(value)
        normalized.append((name, value))
    normalized.sort(key=lambda item: item[0])
    if len({key for key, _ in normalized}) != len(normalized):
        raise CommandCenterError("COMMAND_CENTER_METRIC_NAMES_MUST_BE_UNIQUE")
    _canonical_json(dict(normalized))
    return tuple(normalized)


@dataclass(frozen=True)
class CommandCenterComponent:
    """One immutable upstream truth projected into the command center."""

    kind: CommandCenterComponentKind
    entity_kind: CommandCenterEntityKind
    entity_id: str
    as_of: datetime
    source_record_id: str
    status: ReadinessStatus
    headline: str = ""
    security_id: str | None = None
    portfolio_id: str | None = None
    metrics: tuple[tuple[str, Any], ...] | dict[str, Any] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    lineage_ids: tuple[str, ...] = field(default_factory=tuple)
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        entity_id = self.entity_id.strip().upper()
        source_record_id = self.source_record_id.strip().lower()
        if not entity_id or not source_record_id:
            raise CommandCenterError("COMMAND_CENTER_COMPONENT_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterError("COMMAND_CENTER_COMPONENT_MUST_REMAIN_READ_ONLY")

        security_id = self.security_id.strip().upper() if self.security_id else None
        portfolio_id = self.portfolio_id.strip().upper() if self.portfolio_id else None
        if self.entity_kind is CommandCenterEntityKind.SECURITY and security_id is None:
            raise CommandCenterError("SECURITY_COMPONENT_REQUIRES_SECURITY_ID")
        if self.entity_kind is CommandCenterEntityKind.PORTFOLIO and portfolio_id is None:
            raise CommandCenterError("PORTFOLIO_COMPONENT_REQUIRES_PORTFOLIO_ID")

        blockers = tuple(sorted({item.strip() for item in self.blockers if item.strip()}))
        warnings = tuple(sorted({item.strip() for item in self.warnings if item.strip()}))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise CommandCenterError("PASS_COMMAND_CENTER_COMPONENT_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING:
            if blockers:
                raise CommandCenterError("WARNING_COMMAND_CENTER_COMPONENT_CANNOT_HAVE_BLOCKERS")
            if not warnings:
                raise CommandCenterError("WARNING_COMMAND_CENTER_COMPONENT_REQUIRES_WARNING")
        if self.status is ReadinessStatus.BLOCKED and not blockers:
            raise CommandCenterError("BLOCKED_COMMAND_CENTER_COMPONENT_REQUIRES_BLOCKER")

        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "source_record_id", source_record_id)
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "COMMAND_CENTER_COMPONENT_AS_OF"))
        object.__setattr__(self, "headline", self.headline.strip())
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "portfolio_id", portfolio_id)
        object.__setattr__(self, "metrics", _normalized_metrics(self.metrics))
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "lineage_ids", _normalized_ids(self.lineage_ids))

    @property
    def logical_slot(self) -> tuple[str, str, str, str | None, str | None]:
        return (
            self.kind.value,
            self.entity_kind.value,
            self.entity_id,
            self.security_id,
            self.portfolio_id,
        )

    @property
    def component_id(self) -> str:
        return _digest(self.to_dict(include_component_id=False))

    def to_dict(self, *, include_component_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "entity_kind": self.entity_kind.value,
            "entity_id": self.entity_id,
            "as_of": self.as_of.isoformat(),
            "source_record_id": self.source_record_id,
            "status": self.status.value,
            "headline": self.headline,
            "security_id": self.security_id,
            "portfolio_id": self.portfolio_id,
            "metrics": dict(self.metrics),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "lineage_ids": list(self.lineage_ids),
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_component_id:
            payload["component_id"] = self.component_id
        return payload


@dataclass(frozen=True)
class InstitutionalCommandCenterSnapshot:
    """API-ready, immutable projection of one exact institutional decision boundary."""

    as_of: datetime
    platform_id: str
    components: tuple[CommandCenterComponent, ...]
    status: ReadinessStatus
    pass_count: int
    warning_count: int
    blocked_count: int
    unresolved_issue_count: int
    portfolio_id: str | None = None
    security_id: str | None = None
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        platform_id = self.platform_id.strip().upper()
        if not platform_id or not self.schema_version.strip():
            raise CommandCenterError("COMMAND_CENTER_SNAPSHOT_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterError("COMMAND_CENTER_SNAPSHOT_MUST_REMAIN_READ_ONLY")
        boundary = _aware_utc(self.as_of, "COMMAND_CENTER_SNAPSHOT_AS_OF")
        portfolio_id = self.portfolio_id.strip().upper() if self.portfolio_id else None
        security_id = self.security_id.strip().upper() if self.security_id else None
        components = tuple(sorted(self.components, key=lambda item: item.component_id))
        if not components:
            raise CommandCenterError("COMMAND_CENTER_SNAPSHOT_COMPONENTS_REQUIRED")
        if any(component.as_of != boundary for component in components):
            raise CommandCenterError("COMMAND_CENTER_COMPONENT_AS_OF_MISMATCH")
        if portfolio_id and any(
            component.portfolio_id not in {None, portfolio_id} for component in components
        ):
            raise CommandCenterError("COMMAND_CENTER_PORTFOLIO_ID_MISMATCH")
        if security_id and any(
            component.security_id not in {None, security_id} for component in components
        ):
            raise CommandCenterError("COMMAND_CENTER_SECURITY_ID_MISMATCH")

        actual_pass = sum(item.status is ReadinessStatus.PASS for item in components)
        actual_warning = sum(item.status is ReadinessStatus.WARNING for item in components)
        actual_blocked = sum(item.status is ReadinessStatus.BLOCKED for item in components)
        actual_issues = sum(len(item.blockers) + len(item.warnings) for item in components)
        if (self.pass_count, self.warning_count, self.blocked_count, self.unresolved_issue_count) != (
            actual_pass,
            actual_warning,
            actual_blocked,
            actual_issues,
        ):
            raise CommandCenterError("COMMAND_CENTER_SNAPSHOT_COUNT_MISMATCH")
        expected_status = (
            ReadinessStatus.BLOCKED
            if actual_blocked
            else ReadinessStatus.WARNING
            if actual_warning
            else ReadinessStatus.PASS
        )
        if self.status is not expected_status:
            raise CommandCenterError("COMMAND_CENTER_SNAPSHOT_STATUS_MISMATCH")

        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "platform_id", platform_id)
        object.__setattr__(self, "portfolio_id", portfolio_id)
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "schema_version", self.schema_version.strip())

    @property
    def snapshot_id(self) -> str:
        return _digest(self.to_dict(include_snapshot_id=False, include_components=False))

    def to_dict(
        self,
        *,
        include_snapshot_id: bool = True,
        include_components: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "as_of": self.as_of.isoformat(),
            "platform_id": self.platform_id,
            "portfolio_id": self.portfolio_id,
            "security_id": self.security_id,
            "status": self.status.value,
            "pass_count": self.pass_count,
            "warning_count": self.warning_count,
            "blocked_count": self.blocked_count,
            "unresolved_issue_count": self.unresolved_issue_count,
            "component_ids": [item.component_id for item in self.components],
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_components:
            payload["components"] = [item.to_dict() for item in self.components]
        if include_snapshot_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


class InstitutionalCommandCenterBuilder:
    """Build one fail-closed snapshot without recomputing upstream investment truth."""

    @staticmethod
    def build(
        *,
        as_of: datetime,
        components: tuple[CommandCenterComponent, ...],
        platform_id: str = "DAILY_ALPHA",
        portfolio_id: str | None = None,
        security_id: str | None = None,
    ) -> InstitutionalCommandCenterSnapshot:
        boundary = _aware_utc(as_of, "COMMAND_CENTER_BUILD_AS_OF")
        if not components:
            raise CommandCenterError("COMMAND_CENTER_COMPONENTS_REQUIRED")

        by_slot: dict[
            tuple[str, str, str, str | None, str | None], CommandCenterComponent
        ] = {}
        for component in components:
            if component.as_of > boundary:
                raise CommandCenterError("FUTURE_COMMAND_CENTER_COMPONENT_NOT_ALLOWED")
            if component.as_of != boundary:
                raise CommandCenterError("STALE_COMMAND_CENTER_COMPONENT_NOT_ALLOWED")
            existing = by_slot.get(component.logical_slot)
            if existing is None:
                by_slot[component.logical_slot] = component
                continue
            if existing.component_id != component.component_id:
                raise CommandCenterError(
                    "COMMAND_CENTER_COMPONENT_LOGICAL_SLOT_CONFLICT:"
                    f"{component.kind.value}:{component.entity_id}"
                )

        unique = tuple(sorted(by_slot.values(), key=lambda item: item.component_id))
        normalized_portfolio = portfolio_id.strip().upper() if portfolio_id else None
        normalized_security = security_id.strip().upper() if security_id else None
        if normalized_portfolio and any(
            item.portfolio_id not in {None, normalized_portfolio} for item in unique
        ):
            raise CommandCenterError("COMMAND_CENTER_PORTFOLIO_ID_MISMATCH")
        if normalized_security and any(
            item.security_id not in {None, normalized_security} for item in unique
        ):
            raise CommandCenterError("COMMAND_CENTER_SECURITY_ID_MISMATCH")

        pass_count = sum(item.status is ReadinessStatus.PASS for item in unique)
        warning_count = sum(item.status is ReadinessStatus.WARNING for item in unique)
        blocked_count = sum(item.status is ReadinessStatus.BLOCKED for item in unique)
        unresolved = sum(len(item.blockers) + len(item.warnings) for item in unique)
        status = (
            ReadinessStatus.BLOCKED
            if blocked_count
            else ReadinessStatus.WARNING
            if warning_count
            else ReadinessStatus.PASS
        )
        return InstitutionalCommandCenterSnapshot(
            as_of=boundary,
            platform_id=platform_id,
            portfolio_id=normalized_portfolio,
            security_id=normalized_security,
            components=unique,
            status=status,
            pass_count=pass_count,
            warning_count=warning_count,
            blocked_count=blocked_count,
            unresolved_issue_count=unresolved,
        )
