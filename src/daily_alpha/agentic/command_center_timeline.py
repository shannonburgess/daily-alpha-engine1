"""Read-only command-center timeline facade for future API/UI consumers.

This module composes already-governed Stage 9L history records with Stage 9K audit diffs.
It does not recompute investment truth, mutate history, persist data, or create portfolio,
execution, capital, or live-trading authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .command_center_audit import (
    InstitutionalCommandCenterAuditBuilder,
    InstitutionalCommandCenterAuditDiff,
)
from .command_center_history import (
    CommandCenterHistoryOrder,
    CommandCenterHistoryQuery,
    CommandCenterHistoryRecord,
    InstitutionalCommandCenterHistoryRepository,
)


class CommandCenterTimelineError(ValueError):
    """Timeline composition violated exact-scope or read-only contracts."""


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
        raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CommandCenterTimelineEntry:
    """One retained snapshot plus its exact retained-predecessor audit diff when available."""

    record: CommandCenterHistoryRecord
    audit_diff: InstitutionalCommandCenterAuditDiff | None = None
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_TIMELINE_ENTRY_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.schema_version.strip():
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_ENTRY_SCHEMA_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_ENTRY_MUST_REMAIN_READ_ONLY")
        object.__setattr__(self, "schema_version", self.schema_version.strip())

        if self.audit_diff is None:
            return
        if self.audit_diff.current_snapshot_id != self.record.snapshot_id:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_CURRENT_SNAPSHOT_MISMATCH")
        if self.audit_diff.current_as_of != self.record.as_of:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_CURRENT_AS_OF_MISMATCH")
        snapshot = self.record.snapshot
        if (
            self.audit_diff.platform_id != snapshot.platform_id
            or self.audit_diff.portfolio_id != snapshot.portfolio_id
            or self.audit_diff.security_id != snapshot.security_id
        ):
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_AUDIT_SCOPE_MISMATCH")

    @property
    def predecessor_snapshot_id(self) -> str | None:
        return self.audit_diff.previous_snapshot_id if self.audit_diff else None

    @property
    def diff_available(self) -> bool:
        return self.audit_diff is not None

    @property
    def entry_id(self) -> str:
        return _digest(self.to_dict(include_entry_id=False))

    def to_dict(self, *, include_entry_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "record": self.record.to_dict(),
            "diff_available": self.diff_available,
            "predecessor_snapshot_id": self.predecessor_snapshot_id,
            "audit_diff": self.audit_diff.to_dict() if self.audit_diff else None,
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_entry_id:
            payload["entry_id"] = self.entry_id
        return payload


@dataclass(frozen=True)
class CommandCenterTimelinePage:
    """API-ready timeline page preserving the underlying Stage 9L pagination contract."""

    history_query_id: str
    entries: tuple[CommandCenterTimelineEntry, ...]
    matched_count: int
    next_cursor: str | None
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_TIMELINE_PAGE_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.history_query_id.strip() or not self.schema_version.strip():
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_PAGE_IDENTITY_REQUIRED")
        if self.matched_count < len(self.entries):
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_MATCHED_COUNT_INVALID")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_PAGE_MUST_REMAIN_READ_ONLY")
        object.__setattr__(self, "history_query_id", self.history_query_id.strip())
        object.__setattr__(self, "schema_version", self.schema_version.strip())
        object.__setattr__(self, "entries", tuple(self.entries))

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    @property
    def timeline_id(self) -> str:
        return _digest(self.to_dict(include_timeline_id=False))

    def to_dict(self, *, include_timeline_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "history_query_id": self.history_query_id,
            "matched_count": self.matched_count,
            "returned_count": len(self.entries),
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "entries": [item.to_dict() for item in self.entries],
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_timeline_id:
            payload["timeline_id"] = self.timeline_id
        return payload


class InstitutionalCommandCenterTimelineService:
    """Compose retained history with exact predecessor diffs without inventing facts."""

    def __init__(self, repository: InstitutionalCommandCenterHistoryRepository) -> None:
        self._repository = repository

    def get(self, snapshot_id: str) -> CommandCenterTimelineEntry | None:
        record = self._repository.get(snapshot_id)
        if record is None:
            return None
        return self._entry_for(record)

    def query(self, query: CommandCenterHistoryQuery) -> CommandCenterTimelinePage:
        page = self._repository.query(query)
        if page.query_id != query.query_id:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_HISTORY_QUERY_ID_MISMATCH")

        entries: list[CommandCenterTimelineEntry] = []
        for record in page.records:
            if record.scope_key != query.scope_key:
                raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_HISTORY_SCOPE_MISMATCH")
            entries.append(self._entry_for(record))

        return CommandCenterTimelinePage(
            history_query_id=page.query_id,
            entries=tuple(entries),
            matched_count=page.matched_count,
            next_cursor=page.next_cursor,
        )

    def _entry_for(self, record: CommandCenterHistoryRecord) -> CommandCenterTimelineEntry:
        snapshot = record.snapshot
        predecessor_page = self._repository.query(
            CommandCenterHistoryQuery(
                platform_id=snapshot.platform_id,
                portfolio_id=snapshot.portfolio_id,
                security_id=snapshot.security_id,
                end_as_of=record.as_of,
                order=CommandCenterHistoryOrder.NEWEST_FIRST,
                page_size=2,
            )
        )
        if not predecessor_page.records:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_RETAINED_RECORD_NOT_QUERYABLE")
        current = predecessor_page.records[0]
        if current.snapshot_id != record.snapshot_id or current.as_of != record.as_of:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_REPOSITORY_ORDER_INCONSISTENT")
        if current.scope_key != record.scope_key:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_REPOSITORY_SCOPE_INCONSISTENT")

        if len(predecessor_page.records) == 1:
            return CommandCenterTimelineEntry(record=record)

        previous = predecessor_page.records[1]
        if previous.scope_key != record.scope_key or previous.as_of >= record.as_of:
            raise CommandCenterTimelineError("COMMAND_CENTER_TIMELINE_PREDECESSOR_INCONSISTENT")

        audit_diff = InstitutionalCommandCenterAuditBuilder.build(
            previous=previous.snapshot,
            current=record.snapshot,
        )
        return CommandCenterTimelineEntry(record=record, audit_diff=audit_diff)
