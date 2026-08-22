"""Deterministic API drill-down view over an institutional command-center snapshot.

The API view is a read-only index over immutable command-center components. It does not
recompute investment facts, mutate state, or create any additional authority. Scope status
is the worst upstream component status within that scope, so a WARNING/BLOCKED component
can never be upgraded by presentation logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    InstitutionalCommandCenterSnapshot,
)
from .contracts import ReadinessStatus


class CommandCenterScopeKind(StrEnum):
    PLATFORM = "PLATFORM"
    PORTFOLIO = "PORTFOLIO"
    SECURITY = "SECURITY"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _rollup_status(components: tuple[CommandCenterComponent, ...]) -> ReadinessStatus:
    if any(item.status is ReadinessStatus.BLOCKED for item in components):
        return ReadinessStatus.BLOCKED
    if any(item.status is ReadinessStatus.WARNING for item in components):
        return ReadinessStatus.WARNING
    return ReadinessStatus.PASS


@dataclass(frozen=True)
class CommandCenterTileSummary:
    """Status/count tile derived only from already-governed projected components."""

    kind: CommandCenterComponentKind
    total_count: int
    pass_count: int
    warning_count: int
    blocked_count: int
    unresolved_issue_count: int
    component_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        counts = (
            self.total_count,
            self.pass_count,
            self.warning_count,
            self.blocked_count,
            self.unresolved_issue_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("COMMAND_CENTER_TILE_COUNTS_NONNEGATIVE")
        if self.total_count != self.pass_count + self.warning_count + self.blocked_count:
            raise ValueError("COMMAND_CENTER_TILE_STATUS_COUNTS_INVALID")
        component_ids = tuple(sorted(set(self.component_ids)))
        if len(component_ids) != self.total_count:
            raise ValueError("COMMAND_CENTER_TILE_COMPONENT_COUNT_MISMATCH")
        object.__setattr__(self, "component_ids", component_ids)

    @property
    def status(self) -> ReadinessStatus:
        if self.blocked_count:
            return ReadinessStatus.BLOCKED
        if self.warning_count:
            return ReadinessStatus.WARNING
        return ReadinessStatus.PASS

    @property
    def tile_id(self) -> str:
        return _digest(
            {
                "kind": self.kind.value,
                "status": self.status.value,
                "component_ids": list(self.component_ids),
                "unresolved_issue_count": self.unresolved_issue_count,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tile_id": self.tile_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "total_count": self.total_count,
            "pass_count": self.pass_count,
            "warning_count": self.warning_count,
            "blocked_count": self.blocked_count,
            "unresolved_issue_count": self.unresolved_issue_count,
            "component_ids": list(self.component_ids),
        }


def _tile_summaries(
    components: tuple[CommandCenterComponent, ...],
) -> tuple[CommandCenterTileSummary, ...]:
    summaries: list[CommandCenterTileSummary] = []
    for kind in sorted(CommandCenterComponentKind, key=lambda item: item.value):
        selected = tuple(item for item in components if item.kind is kind)
        if not selected:
            continue
        summaries.append(
            CommandCenterTileSummary(
                kind=kind,
                total_count=len(selected),
                pass_count=sum(item.status is ReadinessStatus.PASS for item in selected),
                warning_count=sum(item.status is ReadinessStatus.WARNING for item in selected),
                blocked_count=sum(item.status is ReadinessStatus.BLOCKED for item in selected),
                unresolved_issue_count=sum(
                    len(item.blockers) + len(item.warnings) for item in selected
                ),
                component_ids=tuple(item.component_id for item in selected),
            )
        )
    return tuple(summaries)


@dataclass(frozen=True)
class CommandCenterScopeView:
    """One deterministic portfolio/security/platform drill-down scope."""

    scope_kind: CommandCenterScopeKind
    scope_id: str
    components: tuple[CommandCenterComponent, ...]

    def __post_init__(self) -> None:
        scope_id = self.scope_id.strip().upper()
        if not scope_id:
            raise ValueError("COMMAND_CENTER_SCOPE_ID_REQUIRED")
        components = tuple(sorted(self.components, key=lambda item: item.component_id))
        if not components:
            raise ValueError("COMMAND_CENTER_SCOPE_COMPONENTS_REQUIRED")
        if self.scope_kind is CommandCenterScopeKind.SECURITY and any(
            item.security_id != scope_id for item in components
        ):
            raise ValueError("COMMAND_CENTER_SECURITY_SCOPE_MISMATCH")
        if self.scope_kind is CommandCenterScopeKind.PORTFOLIO and any(
            item.portfolio_id != scope_id for item in components
        ):
            raise ValueError("COMMAND_CENTER_PORTFOLIO_SCOPE_MISMATCH")
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(self, "components", components)

    @property
    def status(self) -> ReadinessStatus:
        return _rollup_status(self.components)

    @property
    def pass_count(self) -> int:
        return sum(item.status is ReadinessStatus.PASS for item in self.components)

    @property
    def warning_count(self) -> int:
        return sum(item.status is ReadinessStatus.WARNING for item in self.components)

    @property
    def blocked_count(self) -> int:
        return sum(item.status is ReadinessStatus.BLOCKED for item in self.components)

    @property
    def unresolved_issue_count(self) -> int:
        return sum(len(item.blockers) + len(item.warnings) for item in self.components)

    @property
    def tile_summaries(self) -> tuple[CommandCenterTileSummary, ...]:
        return _tile_summaries(self.components)

    def tile(self, kind: CommandCenterComponentKind) -> CommandCenterTileSummary | None:
        return next((item for item in self.tile_summaries if item.kind is kind), None)

    @property
    def scope_view_id(self) -> str:
        return _digest(
            {
                "scope_kind": self.scope_kind.value,
                "scope_id": self.scope_id,
                "status": self.status.value,
                "component_ids": [item.component_id for item in self.components],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_view_id": self.scope_view_id,
            "scope_kind": self.scope_kind.value,
            "scope_id": self.scope_id,
            "status": self.status.value,
            "pass_count": self.pass_count,
            "warning_count": self.warning_count,
            "blocked_count": self.blocked_count,
            "unresolved_issue_count": self.unresolved_issue_count,
            "component_ids": [item.component_id for item in self.components],
            "tiles": [item.to_dict() for item in self.tile_summaries],
            "components": [item.to_dict() for item in self.components],
            "research_only": True,
            "paper_ledger_mutation_authorized": False,
            "portfolio_construction_authorized": False,
            "execution_authorized": False,
            "trading_authorized": False,
            "live_trading_enabled": False,
        }


@dataclass(frozen=True)
class InstitutionalCommandCenterAPIView:
    """Hierarchical API index tied to exactly one immutable command-center snapshot."""

    snapshot: InstitutionalCommandCenterSnapshot
    platform_scope: CommandCenterScopeView
    portfolio_scopes: tuple[CommandCenterScopeView, ...]
    security_scopes: tuple[CommandCenterScopeView, ...]
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_API_V1"

    def __post_init__(self) -> None:
        portfolio_scopes = tuple(sorted(self.portfolio_scopes, key=lambda item: item.scope_id))
        security_scopes = tuple(sorted(self.security_scopes, key=lambda item: item.scope_id))
        if self.platform_scope.scope_kind is not CommandCenterScopeKind.PLATFORM:
            raise ValueError("COMMAND_CENTER_API_PLATFORM_SCOPE_REQUIRED")
        if any(item.scope_kind is not CommandCenterScopeKind.PORTFOLIO for item in portfolio_scopes):
            raise ValueError("COMMAND_CENTER_API_PORTFOLIO_SCOPE_INVALID")
        if any(item.scope_kind is not CommandCenterScopeKind.SECURITY for item in security_scopes):
            raise ValueError("COMMAND_CENTER_API_SECURITY_SCOPE_INVALID")
        if not self.schema_version.strip():
            raise ValueError("COMMAND_CENTER_API_SCHEMA_VERSION_REQUIRED")
        object.__setattr__(self, "portfolio_scopes", portfolio_scopes)
        object.__setattr__(self, "security_scopes", security_scopes)
        object.__setattr__(self, "schema_version", self.schema_version.strip())

    @property
    def api_view_id(self) -> str:
        return _digest(
            {
                "schema_version": self.schema_version,
                "snapshot_id": self.snapshot.snapshot_id,
                "platform_scope_view_id": self.platform_scope.scope_view_id,
                "portfolio_scope_view_ids": [item.scope_view_id for item in self.portfolio_scopes],
                "security_scope_view_ids": [item.scope_view_id for item in self.security_scopes],
            }
        )

    def portfolio(self, portfolio_id: str) -> CommandCenterScopeView | None:
        normalized = portfolio_id.strip().upper()
        return next((item for item in self.portfolio_scopes if item.scope_id == normalized), None)

    def security(self, security_id: str) -> CommandCenterScopeView | None:
        normalized = security_id.strip().upper()
        return next((item for item in self.security_scopes if item.scope_id == normalized), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "api_view_id": self.api_view_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "as_of": self.snapshot.as_of.isoformat(),
            "platform_id": self.snapshot.platform_id,
            "status": self.snapshot.status.value,
            "platform": self.platform_scope.to_dict(),
            "portfolios": [item.to_dict() for item in self.portfolio_scopes],
            "securities": [item.to_dict() for item in self.security_scopes],
            "research_only": True,
            "paper_ledger_mutation_authorized": False,
            "portfolio_construction_authorized": False,
            "execution_authorized": False,
            "trading_authorized": False,
            "live_trading_enabled": False,
        }


class InstitutionalCommandCenterAPIBuilder:
    """Index one immutable snapshot into deterministic API drill-down scopes."""

    @staticmethod
    def build(snapshot: InstitutionalCommandCenterSnapshot) -> InstitutionalCommandCenterAPIView:
        platform_scope = CommandCenterScopeView(
            scope_kind=CommandCenterScopeKind.PLATFORM,
            scope_id=snapshot.platform_id,
            components=snapshot.components,
        )

        portfolio_ids = sorted(
            {item.portfolio_id for item in snapshot.components if item.portfolio_id is not None}
        )
        portfolio_scopes = tuple(
            CommandCenterScopeView(
                scope_kind=CommandCenterScopeKind.PORTFOLIO,
                scope_id=portfolio_id,
                components=tuple(
                    item for item in snapshot.components if item.portfolio_id == portfolio_id
                ),
            )
            for portfolio_id in portfolio_ids
        )

        security_ids = sorted(
            {item.security_id for item in snapshot.components if item.security_id is not None}
        )
        security_scopes = tuple(
            CommandCenterScopeView(
                scope_kind=CommandCenterScopeKind.SECURITY,
                scope_id=security_id,
                components=tuple(
                    item for item in snapshot.components if item.security_id == security_id
                ),
            )
            for security_id in security_ids
        )
        return InstitutionalCommandCenterAPIView(
            snapshot=snapshot,
            platform_scope=platform_scope,
            portfolio_scopes=portfolio_scopes,
            security_scopes=security_scopes,
        )
