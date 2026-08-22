"""Transport-neutral read-only command-center API contracts.

This layer maps already-governed current snapshots, Stage 9J drill-down views, and Stage 9M
bounded timelines into deterministic request/response envelopes. It deliberately defines no
HTTP server, route framework, persistence adapter, authentication implementation, mutation
surface, portfolio authority, execution authority, or live-trading authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .command_center import InstitutionalCommandCenterSnapshot
from .command_center_api import InstitutionalCommandCenterAPIBuilder
from .command_center_history import CommandCenterHistoryOrder, CommandCenterHistoryQuery
from .command_center_timeline import InstitutionalCommandCenterTimelineService
from .contracts import ReadinessStatus


class CommandCenterAPIContractError(ValueError):
    """A transport-neutral command-center API contract invariant failed."""


class CommandCenterAPIOperation(StrEnum):
    CURRENT_SNAPSHOT = "CURRENT_SNAPSHOT"
    PLATFORM_VIEW = "PLATFORM_VIEW"
    PORTFOLIO_VIEW = "PORTFOLIO_VIEW"
    SECURITY_VIEW = "SECURITY_VIEW"
    TIMELINE = "TIMELINE"


class CommandCenterAPIResultStatus(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"


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
        raise CommandCenterAPIContractError("COMMAND_CENTER_API_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _aware_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise CommandCenterAPIContractError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CommandCenterAPIRequest:
    """Transport-independent query contract for one read-only command-center operation."""

    operation: CommandCenterAPIOperation
    platform_id: str = "DAILY_ALPHA"
    portfolio_id: str | None = None
    security_id: str | None = None
    start_as_of: datetime | None = None
    end_as_of: datetime | None = None
    status: ReadinessStatus | None = None
    order: CommandCenterHistoryOrder = CommandCenterHistoryOrder.NEWEST_FIRST
    page_size: int = 50
    cursor: str | None = None
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_API_REQUEST_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        platform_id = self.platform_id.strip().upper()
        portfolio_id = self.portfolio_id.strip().upper() if self.portfolio_id else None
        security_id = self.security_id.strip().upper() if self.security_id else None
        schema_version = self.schema_version.strip()
        cursor = self.cursor.strip() if self.cursor else None
        if not platform_id or not schema_version:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_REQUEST_IDENTITY_REQUIRED")
        if not 1 <= self.page_size <= 100:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_PAGE_SIZE_OUT_OF_RANGE")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_REQUEST_MUST_REMAIN_READ_ONLY")

        start = _aware_utc(self.start_as_of, "COMMAND_CENTER_API_START_AS_OF")
        end = _aware_utc(self.end_as_of, "COMMAND_CENTER_API_END_AS_OF")
        if start is not None and end is not None and start > end:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_RANGE_REVERSED")

        if self.operation in {
            CommandCenterAPIOperation.CURRENT_SNAPSHOT,
            CommandCenterAPIOperation.PLATFORM_VIEW,
        } and (portfolio_id is not None or security_id is not None):
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_PLATFORM_OPERATION_SCOPE_INVALID")
        if self.operation is CommandCenterAPIOperation.PORTFOLIO_VIEW:
            if portfolio_id is None or security_id is not None:
                raise CommandCenterAPIContractError("COMMAND_CENTER_API_PORTFOLIO_SCOPE_REQUIRED")
        if self.operation is CommandCenterAPIOperation.SECURITY_VIEW:
            if security_id is None or portfolio_id is not None:
                raise CommandCenterAPIContractError("COMMAND_CENTER_API_SECURITY_SCOPE_REQUIRED")
        if self.operation is not CommandCenterAPIOperation.TIMELINE and any(
            value is not None for value in (start, end, self.status, cursor)
        ):
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_HISTORY_FIELDS_REQUIRE_TIMELINE")
        if self.operation is not CommandCenterAPIOperation.TIMELINE and (
            self.order is not CommandCenterHistoryOrder.NEWEST_FIRST or self.page_size != 50
        ):
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_PAGINATION_REQUIRES_TIMELINE")

        object.__setattr__(self, "platform_id", platform_id)
        object.__setattr__(self, "portfolio_id", portfolio_id)
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "start_as_of", start)
        object.__setattr__(self, "end_as_of", end)
        object.__setattr__(self, "cursor", cursor)
        object.__setattr__(self, "schema_version", schema_version)

    @property
    def request_id(self) -> str:
        return _digest(self.to_dict(include_request_id=False))

    @property
    def scope_key(self) -> tuple[str, str | None, str | None]:
        return (self.platform_id, self.portfolio_id, self.security_id)

    def to_history_query(self) -> CommandCenterHistoryQuery:
        if self.operation is not CommandCenterAPIOperation.TIMELINE:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_TIMELINE_REQUEST_REQUIRED")
        return CommandCenterHistoryQuery(
            platform_id=self.platform_id,
            portfolio_id=self.portfolio_id,
            security_id=self.security_id,
            start_as_of=self.start_as_of,
            end_as_of=self.end_as_of,
            status=self.status,
            order=self.order,
            page_size=self.page_size,
            cursor=self.cursor,
        )

    def to_dict(self, *, include_request_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "operation": self.operation.value,
            "platform_id": self.platform_id,
            "portfolio_id": self.portfolio_id,
            "security_id": self.security_id,
            "start_as_of": self.start_as_of.isoformat() if self.start_as_of else None,
            "end_as_of": self.end_as_of.isoformat() if self.end_as_of else None,
            "status": self.status.value if self.status else None,
            "order": self.order.value,
            "page_size": self.page_size,
            "cursor": self.cursor,
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_request_id:
            payload["request_id"] = self.request_id
        return payload


@dataclass(frozen=True)
class CommandCenterAPIResponse:
    """Deterministic read-only envelope suitable for a later transport adapter."""

    request: CommandCenterAPIRequest
    result_status: CommandCenterAPIResultStatus
    payload: dict[str, Any] | None
    resource_id: str | None
    upstream_ids: tuple[str, ...] = ()
    schema_version: str = "INSTITUTIONAL_COMMAND_CENTER_API_RESPONSE_V1"
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        schema_version = self.schema_version.strip()
        resource_id = self.resource_id.strip() if self.resource_id else None
        upstream_ids = tuple(sorted({item.strip() for item in self.upstream_ids if item.strip()}))
        if not schema_version:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_RESPONSE_SCHEMA_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_RESPONSE_MUST_REMAIN_READ_ONLY")
        if self.result_status is CommandCenterAPIResultStatus.OK:
            if self.payload is None or resource_id is None:
                raise CommandCenterAPIContractError("COMMAND_CENTER_API_OK_RESPONSE_REQUIRES_RESOURCE")
            _canonical_json(self.payload)
        else:
            if self.payload is not None or resource_id is not None:
                raise CommandCenterAPIContractError("COMMAND_CENTER_API_NOT_FOUND_MUST_BE_EMPTY")
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "upstream_ids", upstream_ids)

    @property
    def response_id(self) -> str:
        return _digest(self.to_dict(include_response_id=False))

    def to_dict(self, *, include_response_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "request_id": self.request.request_id,
            "operation": self.request.operation.value,
            "result_status": self.result_status.value,
            "resource_id": self.resource_id,
            "upstream_ids": list(self.upstream_ids),
            "payload": self.payload,
            "research_only": self.research_only,
            "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        if include_response_id:
            payload["response_id"] = self.response_id
        return payload


class InstitutionalCommandCenterAPIContract:
    """Resolve transport-neutral read requests over governed current/timeline inputs only."""

    def __init__(self, timeline_service: InstitutionalCommandCenterTimelineService) -> None:
        self._timeline_service = timeline_service

    def execute(
        self,
        request: CommandCenterAPIRequest,
        *,
        current_snapshot: InstitutionalCommandCenterSnapshot | None = None,
    ) -> CommandCenterAPIResponse:
        if request.operation is CommandCenterAPIOperation.TIMELINE:
            return self._timeline(request)
        if current_snapshot is None:
            return self._not_found(request)
        self._assert_snapshot_platform(request, current_snapshot)

        if request.operation is CommandCenterAPIOperation.CURRENT_SNAPSHOT:
            return self._ok(
                request,
                payload=current_snapshot.to_dict(),
                resource_id=current_snapshot.snapshot_id,
                upstream_ids=(current_snapshot.snapshot_id,),
            )

        api_view = InstitutionalCommandCenterAPIBuilder.build(current_snapshot)
        if request.operation is CommandCenterAPIOperation.PLATFORM_VIEW:
            scope = api_view.platform_scope
        elif request.operation is CommandCenterAPIOperation.PORTFOLIO_VIEW:
            scope = api_view.portfolio(request.portfolio_id or "")
        elif request.operation is CommandCenterAPIOperation.SECURITY_VIEW:
            scope = api_view.security(request.security_id or "")
        else:  # pragma: no cover - enum exhaustiveness guard
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_OPERATION_UNSUPPORTED")

        if scope is None:
            return self._not_found(request, upstream_ids=(current_snapshot.snapshot_id,))
        return self._ok(
            request,
            payload=scope.to_dict(),
            resource_id=scope.scope_view_id,
            upstream_ids=(current_snapshot.snapshot_id, scope.scope_view_id),
        )

    def _timeline(self, request: CommandCenterAPIRequest) -> CommandCenterAPIResponse:
        query = request.to_history_query()
        page = self._timeline_service.query(query)
        if page.history_query_id != query.query_id:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_TIMELINE_QUERY_ID_MISMATCH")
        if not page.entries:
            return self._not_found(request, upstream_ids=(query.query_id,))
        return self._ok(
            request,
            payload=page.to_dict(),
            resource_id=page.timeline_id,
            upstream_ids=(query.query_id, *(entry.record.snapshot_id for entry in page.entries)),
        )

    @staticmethod
    def _assert_snapshot_platform(
        request: CommandCenterAPIRequest,
        snapshot: InstitutionalCommandCenterSnapshot,
    ) -> None:
        if snapshot.platform_id != request.platform_id:
            raise CommandCenterAPIContractError("COMMAND_CENTER_API_PLATFORM_MISMATCH")

    @staticmethod
    def _ok(
        request: CommandCenterAPIRequest,
        *,
        payload: dict[str, Any],
        resource_id: str,
        upstream_ids: tuple[str, ...],
    ) -> CommandCenterAPIResponse:
        return CommandCenterAPIResponse(
            request=request,
            result_status=CommandCenterAPIResultStatus.OK,
            payload=payload,
            resource_id=resource_id,
            upstream_ids=upstream_ids,
        )

    @staticmethod
    def _not_found(
        request: CommandCenterAPIRequest,
        *,
        upstream_ids: tuple[str, ...] = (),
    ) -> CommandCenterAPIResponse:
        return CommandCenterAPIResponse(
            request=request,
            result_status=CommandCenterAPIResultStatus.NOT_FOUND,
            payload=None,
            resource_id=None,
            upstream_ids=upstream_ids,
        )
