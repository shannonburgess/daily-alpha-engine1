"""Bounded read-only history/query contracts for institutional command-center snapshots.

This module deliberately stops at repository semantics. It defines immutable history
records, retention and pagination contracts, and a bounded in-memory fixture adapter for
regression proof. It does not deploy persistence, recompute investment truth, mutate
PAPER state, or create portfolio/execution/capital/live-trading authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from .command_center import InstitutionalCommandCenterSnapshot
from .contracts import ReadinessStatus


class CommandCenterHistoryError(ValueError):
    """History/query input violates deterministic read-only contracts."""


class CommandCenterHistoryOrder(StrEnum):
    OLDEST_FIRST = "OLDEST_FIRST"
    NEWEST_FIRST = "NEWEST_FIRST"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CommandCenterHistoryError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _scope_key(
    platform_id: str,
    portfolio_id: str | None,
    security_id: str | None,
) -> tuple[str, str | None, str | None]:
    return (
        platform_id.strip().upper(),
        portfolio_id.strip().upper() if portfolio_id else None,
        security_id.strip().upper() if security_id else None,
    )


def _encode_cursor(payload: dict[str, Any]) -> str:
    canonical = _canonical_json(payload)
    envelope = {"payload": payload, "checksum": hashlib.sha256(canonical.encode()).hexdigest()}
    raw = _canonical_json(envelope).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, Any]:
    token = cursor.strip()
    if not token:
        raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_REQUIRED")
    try:
        padded = token + "=" * (-len(token) % 4)
        envelope = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_INVALID") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "checksum"}:
        raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_INVALID")
    payload = envelope["payload"]
    checksum = envelope["checksum"]
    if not isinstance(payload, dict) or not isinstance(checksum, str):
        raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_INVALID")
    expected = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    if checksum != expected:
        raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_TAMPERED")
    return payload


@dataclass(frozen=True)
class CommandCenterRetentionPolicy:
    """Deterministic bounded-retention policy for one exact command-center scope."""

    max_records_per_scope: int = 500

    def __post_init__(self) -> None:
        if not 1 <= self.max_records_per_scope <= 10_000:
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_RETENTION_OUT_OF_RANGE")


@dataclass(frozen=True)
class CommandCenterHistoryRecord:
    """Immutable repository identity for one already-governed command-center snapshot."""

    snapshot: InstitutionalCommandCenterSnapshot
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_HISTORY_RECORD_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.schema_version.strip():
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_RECORD_SCHEMA_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_RECORD_MUST_REMAIN_READ_ONLY")
        object.__setattr__(self, "schema_version", self.schema_version.strip())

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    @property
    def as_of(self) -> datetime:
        return self.snapshot.as_of

    @property
    def scope_key(self) -> tuple[str, str | None, str | None]:
        return _scope_key(
            self.snapshot.platform_id,
            self.snapshot.portfolio_id,
            self.snapshot.security_id,
        )

    @property
    def record_id(self) -> str:
        return _digest(self.to_dict(include_record_id=False))

    def to_dict(self, *, include_record_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "as_of": self.as_of.isoformat(),
            "platform_id": self.snapshot.platform_id,
            "portfolio_id": self.snapshot.portfolio_id,
            "security_id": self.snapshot.security_id,
            "status": self.snapshot.status.value,
            "pass_count": self.snapshot.pass_count,
            "warning_count": self.snapshot.warning_count,
            "blocked_count": self.snapshot.blocked_count,
            "unresolved_issue_count": self.snapshot.unresolved_issue_count,
            "component_ids": [item.component_id for item in self.snapshot.components],
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_record_id:
            payload["record_id"] = self.record_id
        return payload


@dataclass(frozen=True)
class CommandCenterHistoryQuery:
    """Exact-scope bounded query contract for future API/UI history retrieval."""

    platform_id: str = "DAILY_ALPHA"
    portfolio_id: str | None = None
    security_id: str | None = None
    start_as_of: datetime | None = None
    end_as_of: datetime | None = None
    status: ReadinessStatus | None = None
    order: CommandCenterHistoryOrder = CommandCenterHistoryOrder.NEWEST_FIRST
    page_size: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        platform_id, portfolio_id, security_id = _scope_key(
            self.platform_id,
            self.portfolio_id,
            self.security_id,
        )
        if not platform_id:
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_PLATFORM_REQUIRED")
        if not 1 <= self.page_size <= 100:
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_PAGE_SIZE_OUT_OF_RANGE")
        start = (
            _aware_utc(self.start_as_of, "COMMAND_CENTER_HISTORY_START_AS_OF")
            if self.start_as_of
            else None
        )
        end = (
            _aware_utc(self.end_as_of, "COMMAND_CENTER_HISTORY_END_AS_OF")
            if self.end_as_of
            else None
        )
        if start is not None and end is not None and start > end:
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_RANGE_REVERSED")
        object.__setattr__(self, "platform_id", platform_id)
        object.__setattr__(self, "portfolio_id", portfolio_id)
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "start_as_of", start)
        object.__setattr__(self, "end_as_of", end)
        object.__setattr__(self, "cursor", self.cursor.strip() if self.cursor else None)

    @property
    def scope_key(self) -> tuple[str, str | None, str | None]:
        return (self.platform_id, self.portfolio_id, self.security_id)

    @property
    def query_id(self) -> str:
        return _digest(
            {
                "platform_id": self.platform_id,
                "portfolio_id": self.portfolio_id,
                "security_id": self.security_id,
                "start_as_of": self.start_as_of.isoformat() if self.start_as_of else None,
                "end_as_of": self.end_as_of.isoformat() if self.end_as_of else None,
                "status": self.status.value if self.status else None,
                "order": self.order.value,
                "page_size": self.page_size,
            }
        )


@dataclass(frozen=True)
class CommandCenterHistoryAppendResult:
    """Deterministic append/retention outcome with no update/delete authority."""

    record: CommandCenterHistoryRecord
    retained_count: int
    evicted_snapshot_ids: tuple[str, ...] = ()
    idempotent: bool = False

    def __post_init__(self) -> None:
        if self.retained_count < 1:
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_RETAINED_COUNT_INVALID")
        object.__setattr__(self, "evicted_snapshot_ids", tuple(self.evicted_snapshot_ids))


@dataclass(frozen=True)
class CommandCenterHistoryPage:
    """API-ready immutable page of exact history records."""

    query_id: str
    records: tuple[CommandCenterHistoryRecord, ...]
    matched_count: int
    next_cursor: str | None
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_HISTORY_PAGE_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.query_id.strip() or not self.schema_version.strip():
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_PAGE_IDENTITY_REQUIRED")
        if self.matched_count < len(self.records):
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_MATCHED_COUNT_INVALID")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_PAGE_MUST_REMAIN_READ_ONLY")
        object.__setattr__(self, "query_id", self.query_id.strip())
        object.__setattr__(self, "schema_version", self.schema_version.strip())

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "query_id": self.query_id,
            "matched_count": self.matched_count,
            "returned_count": len(self.records),
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "records": [item.to_dict() for item in self.records],
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


class InstitutionalCommandCenterHistoryRepository(Protocol):
    """Storage-neutral append/get/query surface; intentionally no update/delete methods."""

    def append(self, snapshot: InstitutionalCommandCenterSnapshot) -> CommandCenterHistoryAppendResult:
        """Append one immutable snapshot, applying configured bounded retention."""

    def get(self, snapshot_id: str) -> CommandCenterHistoryRecord | None:
        """Return one retained immutable record by exact snapshot identity."""

    def query(self, query: CommandCenterHistoryQuery) -> CommandCenterHistoryPage:
        """Return one deterministic bounded history page for an exact scope."""


class BoundedInMemoryCommandCenterHistoryRepository:
    """Fixture adapter proving repository semantics without external persistence."""

    def __init__(self, policy: CommandCenterRetentionPolicy | None = None) -> None:
        self._policy = policy or CommandCenterRetentionPolicy()
        self._records_by_snapshot_id: dict[str, CommandCenterHistoryRecord] = {}
        self._snapshot_ids_by_scope: dict[tuple[str, str | None, str | None], list[str]] = {}

    def append(self, snapshot: InstitutionalCommandCenterSnapshot) -> CommandCenterHistoryAppendResult:
        record = CommandCenterHistoryRecord(snapshot=snapshot)
        existing = self._records_by_snapshot_id.get(record.snapshot_id)
        if existing is not None:
            if existing.snapshot.to_dict() != snapshot.to_dict():
                raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_SNAPSHOT_ID_CONFLICT")
            retained = len(self._snapshot_ids_by_scope[existing.scope_key])
            return CommandCenterHistoryAppendResult(
                record=existing,
                retained_count=retained,
                idempotent=True,
            )

        scope_ids = self._snapshot_ids_by_scope.setdefault(record.scope_key, [])
        for snapshot_id in scope_ids:
            other = self._records_by_snapshot_id[snapshot_id]
            if other.as_of == record.as_of:
                raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_AS_OF_CONFLICT")

        self._records_by_snapshot_id[record.snapshot_id] = record
        scope_ids.append(record.snapshot_id)
        scope_ids.sort(
            key=lambda snapshot_id: (
                self._records_by_snapshot_id[snapshot_id].as_of,
                snapshot_id,
            )
        )

        evicted: list[str] = []
        while len(scope_ids) > self._policy.max_records_per_scope:
            evicted_id = scope_ids.pop(0)
            del self._records_by_snapshot_id[evicted_id]
            evicted.append(evicted_id)

        return CommandCenterHistoryAppendResult(
            record=record,
            retained_count=len(scope_ids),
            evicted_snapshot_ids=tuple(evicted),
        )

    def get(self, snapshot_id: str) -> CommandCenterHistoryRecord | None:
        return self._records_by_snapshot_id.get(snapshot_id.strip().lower()) or self._records_by_snapshot_id.get(
            snapshot_id.strip()
        )

    def query(self, query: CommandCenterHistoryQuery) -> CommandCenterHistoryPage:
        scope_ids = self._snapshot_ids_by_scope.get(query.scope_key, [])
        records = [self._records_by_snapshot_id[snapshot_id] for snapshot_id in scope_ids]
        records = [
            item
            for item in records
            if (query.start_as_of is None or item.as_of >= query.start_as_of)
            and (query.end_as_of is None or item.as_of <= query.end_as_of)
            and (query.status is None or item.snapshot.status is query.status)
        ]
        records.sort(
            key=lambda item: (item.as_of, item.snapshot_id),
            reverse=query.order is CommandCenterHistoryOrder.NEWEST_FIRST,
        )
        matched_count = len(records)

        start_index = 0
        if query.cursor:
            payload = _decode_cursor(query.cursor)
            if payload.get("query_id") != query.query_id:
                raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_QUERY_MISMATCH")
            anchor_id = payload.get("anchor_snapshot_id")
            anchor_as_of = payload.get("anchor_as_of")
            if not isinstance(anchor_id, str) or not isinstance(anchor_as_of, str):
                raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_INVALID")
            anchor_index = next(
                (
                    index
                    for index, item in enumerate(records)
                    if item.snapshot_id == anchor_id and item.as_of.isoformat() == anchor_as_of
                ),
                None,
            )
            if anchor_index is None:
                raise CommandCenterHistoryError("COMMAND_CENTER_HISTORY_CURSOR_ANCHOR_NOT_RETAINED")
            start_index = anchor_index + 1

        page_records = tuple(records[start_index : start_index + query.page_size])
        next_cursor = None
        if page_records and start_index + len(page_records) < matched_count:
            anchor = page_records[-1]
            next_cursor = _encode_cursor(
                {
                    "query_id": query.query_id,
                    "anchor_snapshot_id": anchor.snapshot_id,
                    "anchor_as_of": anchor.as_of.isoformat(),
                }
            )
        return CommandCenterHistoryPage(
            query_id=query.query_id,
            records=page_records,
            matched_count=matched_count,
            next_cursor=next_cursor,
        )
