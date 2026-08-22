"""Deterministic point-in-time audit diff for institutional command-center snapshots.

This module explains how already-governed command-center truth changed between two
strictly ordered snapshots. It never recomputes investment facts, mutates an upstream
snapshot, or creates portfolio, execution, capital, or live-trading authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
    InstitutionalCommandCenterSnapshot,
)
from .contracts import ReadinessStatus


class CommandCenterAuditError(ValueError):
    """Command-center audit inputs violate deterministic point-in-time contracts."""


class CommandCenterChangeKind(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    STATUS_CHANGED = "STATUS_CHANGED"
    CONTENT_CHANGED = "CONTENT_CHANGED"
    REFRESHED = "REFRESHED"


class CommandCenterTransitionDirection(StrEnum):
    WORSENED = "WORSENED"
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_STATUS_SEVERITY = {
    ReadinessStatus.PASS: 0,
    ReadinessStatus.WARNING: 1,
    ReadinessStatus.BLOCKED: 2,
}


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
        raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _slot_sort_key(slot: tuple[str, str, str, str | None, str | None]) -> tuple[str, ...]:
    return tuple(item or "" for item in slot)


def _display_payload(component: CommandCenterComponent) -> dict[str, Any]:
    """Return presentation facts while excluding point-in-time/source refresh identity."""

    return {
        "status": component.status.value,
        "headline": component.headline,
        "metrics": dict(component.metrics),
        "blockers": list(component.blockers),
        "warnings": list(component.warnings),
    }


def _transition_direction(
    previous: ReadinessStatus | None,
    current: ReadinessStatus | None,
) -> CommandCenterTransitionDirection:
    if previous is None or current is None:
        return CommandCenterTransitionDirection.NOT_APPLICABLE
    previous_severity = _STATUS_SEVERITY[previous]
    current_severity = _STATUS_SEVERITY[current]
    if current_severity > previous_severity:
        return CommandCenterTransitionDirection.WORSENED
    if current_severity < previous_severity:
        return CommandCenterTransitionDirection.IMPROVED
    return CommandCenterTransitionDirection.UNCHANGED


@dataclass(frozen=True)
class CommandCenterComponentChange:
    """One exact logical-slot transition between two immutable snapshots."""

    change_kind: CommandCenterChangeKind
    component_kind: CommandCenterComponentKind
    entity_kind: CommandCenterEntityKind
    entity_id: str
    security_id: str | None
    portfolio_id: str | None
    previous_component_id: str | None
    current_component_id: str | None
    previous_source_record_id: str | None
    current_source_record_id: str | None
    previous_status: ReadinessStatus | None
    current_status: ReadinessStatus | None
    previous_lineage_ids: tuple[str, ...] = ()
    current_lineage_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        entity_id = self.entity_id.strip().upper()
        if not entity_id:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_ENTITY_ID_REQUIRED")
        if self.change_kind is CommandCenterChangeKind.ADDED:
            if self.previous_component_id is not None or self.current_component_id is None:
                raise CommandCenterAuditError("COMMAND_CENTER_ADDED_CHANGE_IDENTITY_INVALID")
        elif self.change_kind is CommandCenterChangeKind.REMOVED:
            if self.previous_component_id is None or self.current_component_id is not None:
                raise CommandCenterAuditError("COMMAND_CENTER_REMOVED_CHANGE_IDENTITY_INVALID")
        elif self.previous_component_id is None or self.current_component_id is None:
            raise CommandCenterAuditError("COMMAND_CENTER_MATCHED_CHANGE_IDENTITY_REQUIRED")

        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(
            self,
            "security_id",
            self.security_id.strip().upper() if self.security_id else None,
        )
        object.__setattr__(
            self,
            "portfolio_id",
            self.portfolio_id.strip().upper() if self.portfolio_id else None,
        )
        object.__setattr__(
            self,
            "previous_lineage_ids",
            tuple(sorted(set(self.previous_lineage_ids))),
        )
        object.__setattr__(
            self,
            "current_lineage_ids",
            tuple(sorted(set(self.current_lineage_ids))),
        )

    @property
    def transition_direction(self) -> CommandCenterTransitionDirection:
        return _transition_direction(self.previous_status, self.current_status)

    @property
    def logical_slot(self) -> tuple[str, str, str, str | None, str | None]:
        return (
            self.component_kind.value,
            self.entity_kind.value,
            self.entity_id,
            self.security_id,
            self.portfolio_id,
        )

    @property
    def change_id(self) -> str:
        return _digest(self.to_dict(include_change_id=False))

    def to_dict(self, *, include_change_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "change_kind": self.change_kind.value,
            "transition_direction": self.transition_direction.value,
            "component_kind": self.component_kind.value,
            "entity_kind": self.entity_kind.value,
            "entity_id": self.entity_id,
            "security_id": self.security_id,
            "portfolio_id": self.portfolio_id,
            "previous_component_id": self.previous_component_id,
            "current_component_id": self.current_component_id,
            "previous_source_record_id": self.previous_source_record_id,
            "current_source_record_id": self.current_source_record_id,
            "previous_status": self.previous_status.value if self.previous_status else None,
            "current_status": self.current_status.value if self.current_status else None,
            "previous_lineage_ids": list(self.previous_lineage_ids),
            "current_lineage_ids": list(self.current_lineage_ids),
        }
        if include_change_id:
            payload["change_id"] = self.change_id
        return payload


@dataclass(frozen=True)
class InstitutionalCommandCenterAuditDiff:
    """API-ready explanation of change between two exact command-center boundaries."""

    previous_snapshot_id: str
    current_snapshot_id: str
    previous_as_of: datetime
    current_as_of: datetime
    platform_id: str
    previous_status: ReadinessStatus
    current_status: ReadinessStatus
    changes: tuple[CommandCenterComponentChange, ...]
    portfolio_id: str | None = None
    security_id: str | None = None
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_AUDIT_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.previous_snapshot_id.strip() or not self.current_snapshot_id.strip():
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_SNAPSHOT_IDS_REQUIRED")
        if self.current_as_of <= self.previous_as_of:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_TIME_MUST_INCREASE")
        if not self.platform_id.strip() or not self.schema_version.strip():
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_MUST_REMAIN_READ_ONLY")

        changes = tuple(sorted(self.changes, key=lambda item: _slot_sort_key(item.logical_slot)))
        if len({item.logical_slot for item in changes}) != len(changes):
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_CHANGE_SLOTS_MUST_BE_UNIQUE")
        object.__setattr__(self, "platform_id", self.platform_id.strip().upper())
        object.__setattr__(
            self,
            "portfolio_id",
            self.portfolio_id.strip().upper() if self.portfolio_id else None,
        )
        object.__setattr__(
            self,
            "security_id",
            self.security_id.strip().upper() if self.security_id else None,
        )
        object.__setattr__(self, "schema_version", self.schema_version.strip())
        object.__setattr__(self, "changes", changes)

    @property
    def added_count(self) -> int:
        return sum(item.change_kind is CommandCenterChangeKind.ADDED for item in self.changes)

    @property
    def removed_count(self) -> int:
        return sum(item.change_kind is CommandCenterChangeKind.REMOVED for item in self.changes)

    @property
    def status_changed_count(self) -> int:
        return sum(
            item.change_kind is CommandCenterChangeKind.STATUS_CHANGED for item in self.changes
        )

    @property
    def content_changed_count(self) -> int:
        return sum(
            item.change_kind is CommandCenterChangeKind.CONTENT_CHANGED for item in self.changes
        )

    @property
    def refreshed_count(self) -> int:
        return sum(item.change_kind is CommandCenterChangeKind.REFRESHED for item in self.changes)

    @property
    def worsened_count(self) -> int:
        return sum(
            item.transition_direction is CommandCenterTransitionDirection.WORSENED
            for item in self.changes
        )

    @property
    def improved_count(self) -> int:
        return sum(
            item.transition_direction is CommandCenterTransitionDirection.IMPROVED
            for item in self.changes
        )

    @property
    def diff_id(self) -> str:
        return _digest(self.to_dict(include_diff_id=False))

    def to_dict(self, *, include_diff_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "previous_snapshot_id": self.previous_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "previous_as_of": self.previous_as_of.isoformat(),
            "current_as_of": self.current_as_of.isoformat(),
            "platform_id": self.platform_id,
            "portfolio_id": self.portfolio_id,
            "security_id": self.security_id,
            "previous_status": self.previous_status.value,
            "current_status": self.current_status.value,
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "status_changed_count": self.status_changed_count,
            "content_changed_count": self.content_changed_count,
            "refreshed_count": self.refreshed_count,
            "worsened_count": self.worsened_count,
            "improved_count": self.improved_count,
            "changes": [item.to_dict() for item in self.changes],
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_diff_id:
            payload["diff_id"] = self.diff_id
        return payload


class InstitutionalCommandCenterAuditBuilder:
    """Compare two snapshots without recomputing or mutating upstream truth."""

    @staticmethod
    def build(
        *,
        previous: InstitutionalCommandCenterSnapshot,
        current: InstitutionalCommandCenterSnapshot,
    ) -> InstitutionalCommandCenterAuditDiff:
        if current.as_of <= previous.as_of:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_TIME_MUST_INCREASE")
        if current.platform_id != previous.platform_id:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_PLATFORM_MISMATCH")
        if current.portfolio_id != previous.portfolio_id:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_PORTFOLIO_SCOPE_MISMATCH")
        if current.security_id != previous.security_id:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_SECURITY_SCOPE_MISMATCH")
        if current.schema_version != previous.schema_version:
            raise CommandCenterAuditError("COMMAND_CENTER_AUDIT_SCHEMA_MISMATCH")

        previous_by_slot = {item.logical_slot: item for item in previous.components}
        current_by_slot = {item.logical_slot: item for item in current.components}
        slots = sorted(set(previous_by_slot) | set(current_by_slot), key=_slot_sort_key)
        changes: list[CommandCenterComponentChange] = []

        for slot in slots:
            old = previous_by_slot.get(slot)
            new = current_by_slot.get(slot)
            if old is None:
                assert new is not None
                change_kind = CommandCenterChangeKind.ADDED
            elif new is None:
                change_kind = CommandCenterChangeKind.REMOVED
            elif old.status is not new.status:
                change_kind = CommandCenterChangeKind.STATUS_CHANGED
            elif _display_payload(old) != _display_payload(new):
                change_kind = CommandCenterChangeKind.CONTENT_CHANGED
            else:
                change_kind = CommandCenterChangeKind.REFRESHED

            component = new or old
            assert component is not None
            changes.append(
                CommandCenterComponentChange(
                    change_kind=change_kind,
                    component_kind=component.kind,
                    entity_kind=component.entity_kind,
                    entity_id=component.entity_id,
                    security_id=component.security_id,
                    portfolio_id=component.portfolio_id,
                    previous_component_id=old.component_id if old else None,
                    current_component_id=new.component_id if new else None,
                    previous_source_record_id=old.source_record_id if old else None,
                    current_source_record_id=new.source_record_id if new else None,
                    previous_status=old.status if old else None,
                    current_status=new.status if new else None,
                    previous_lineage_ids=old.lineage_ids if old else (),
                    current_lineage_ids=new.lineage_ids if new else (),
                )
            )

        return InstitutionalCommandCenterAuditDiff(
            previous_snapshot_id=previous.snapshot_id,
            current_snapshot_id=current.snapshot_id,
            previous_as_of=previous.as_of,
            current_as_of=current.as_of,
            platform_id=current.platform_id,
            portfolio_id=current.portfolio_id,
            security_id=current.security_id,
            previous_status=previous.status,
            current_status=current.status,
            changes=tuple(changes),
        )
