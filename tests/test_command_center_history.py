from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
    InstitutionalCommandCenterBuilder,
)
from daily_alpha.agentic.command_center_history import (
    BoundedInMemoryCommandCenterHistoryRepository,
    CommandCenterHistoryError,
    CommandCenterHistoryOrder,
    CommandCenterHistoryQuery,
    CommandCenterRetentionPolicy,
)
from daily_alpha.agentic.contracts import ReadinessStatus


BASE = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)


def _snapshot(
    offset: int,
    *,
    portfolio_id: str | None = None,
    security_id: str | None = None,
    status: ReadinessStatus = ReadinessStatus.PASS,
):
    as_of = BASE + timedelta(hours=offset)
    warnings = ("RESEARCH_WARNING",) if status is ReadinessStatus.WARNING else ()
    blockers = ("RESEARCH_BLOCK",) if status is ReadinessStatus.BLOCKED else ()
    if portfolio_id:
        component = CommandCenterComponent(
            kind=CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
            entity_kind=CommandCenterEntityKind.PORTFOLIO,
            entity_id=portfolio_id,
            as_of=as_of,
            source_record_id=f"{offset + 1:064x}",
            status=status,
            portfolio_id=portfolio_id,
            warnings=warnings,
            blockers=blockers,
        )
    elif security_id:
        component = CommandCenterComponent(
            kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id="SH24:V2.4",
            as_of=as_of,
            source_record_id=f"{offset + 1:064x}",
            status=status,
            security_id=security_id,
            warnings=warnings,
            blockers=blockers,
        )
    else:
        component = CommandCenterComponent(
            kind=CommandCenterComponentKind.DATA_PLANE,
            entity_kind=CommandCenterEntityKind.PLATFORM,
            entity_id="DAILY_ALPHA",
            as_of=as_of,
            source_record_id=f"{offset + 1:064x}",
            status=status,
            warnings=warnings,
            blockers=blockers,
        )
    return InstitutionalCommandCenterBuilder.build(
        as_of=as_of,
        portfolio_id=portfolio_id,
        security_id=security_id,
        components=(component,),
    )


def test_append_is_idempotent_and_same_scope_time_conflicts_fail_closed() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    first = _snapshot(0)

    initial = repository.append(first)
    repeated = repository.append(first)

    assert initial.idempotent is False
    assert repeated.idempotent is True
    assert repeated.record.snapshot_id == first.snapshot_id
    assert repeated.retained_count == 1

    conflicting = _snapshot(0, status=ReadinessStatus.WARNING)
    with pytest.raises(CommandCenterHistoryError, match="COMMAND_CENTER_HISTORY_AS_OF_CONFLICT"):
        repository.append(conflicting)


def test_retention_is_bounded_per_exact_scope_and_reports_evictions() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository(
        CommandCenterRetentionPolicy(max_records_per_scope=2)
    )
    first = _snapshot(0)
    second = _snapshot(1)
    third = _snapshot(2)
    portfolio = _snapshot(0, portfolio_id="SHADOW")

    repository.append(first)
    repository.append(second)
    outcome = repository.append(third)
    repository.append(portfolio)

    assert outcome.retained_count == 2
    assert outcome.evicted_snapshot_ids == (first.snapshot_id,)
    assert repository.get(first.snapshot_id) is None
    assert repository.get(second.snapshot_id) is not None
    assert repository.get(portfolio.snapshot_id) is not None
    assert [item.snapshot_id for item in repository.query(CommandCenterHistoryQuery()).records] == [
        third.snapshot_id,
        second.snapshot_id,
    ]
    portfolio_page = repository.query(CommandCenterHistoryQuery(portfolio_id="shadow"))
    assert [item.snapshot_id for item in portfolio_page.records] == [portfolio.snapshot_id]


def test_pagination_is_deterministic_in_both_orders() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    snapshots = [_snapshot(index) for index in range(5)]
    for snapshot in reversed(snapshots):
        repository.append(snapshot)

    first = repository.query(CommandCenterHistoryQuery(page_size=2))
    second = repository.query(CommandCenterHistoryQuery(page_size=2, cursor=first.next_cursor))
    third = repository.query(CommandCenterHistoryQuery(page_size=2, cursor=second.next_cursor))

    assert [item.snapshot_id for item in first.records] == [
        snapshots[4].snapshot_id,
        snapshots[3].snapshot_id,
    ]
    assert [item.snapshot_id for item in second.records] == [
        snapshots[2].snapshot_id,
        snapshots[1].snapshot_id,
    ]
    assert [item.snapshot_id for item in third.records] == [snapshots[0].snapshot_id]
    assert first.matched_count == second.matched_count == third.matched_count == 5
    assert third.next_cursor is None

    oldest = repository.query(
        CommandCenterHistoryQuery(
            order=CommandCenterHistoryOrder.OLDEST_FIRST,
            page_size=5,
        )
    )
    assert [item.snapshot_id for item in oldest.records] == [
        snapshot.snapshot_id for snapshot in snapshots
    ]


def test_queries_apply_inclusive_time_status_and_exact_scope_filters() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    pass_snapshot = _snapshot(0)
    warning_snapshot = _snapshot(1, status=ReadinessStatus.WARNING)
    blocked_snapshot = _snapshot(2, status=ReadinessStatus.BLOCKED)
    security_snapshot = _snapshot(1, security_id="MU")
    for snapshot in (pass_snapshot, warning_snapshot, blocked_snapshot, security_snapshot):
        repository.append(snapshot)

    page = repository.query(
        CommandCenterHistoryQuery(
            start_as_of=warning_snapshot.as_of,
            end_as_of=blocked_snapshot.as_of,
            status=ReadinessStatus.WARNING,
        )
    )
    assert [item.snapshot_id for item in page.records] == [warning_snapshot.snapshot_id]

    security_page = repository.query(CommandCenterHistoryQuery(security_id="mu"))
    assert [item.snapshot_id for item in security_page.records] == [security_snapshot.snapshot_id]


def test_reversed_range_and_oversized_pages_fail_closed() -> None:
    with pytest.raises(CommandCenterHistoryError, match="COMMAND_CENTER_HISTORY_RANGE_REVERSED"):
        CommandCenterHistoryQuery(start_as_of=BASE + timedelta(hours=1), end_as_of=BASE)
    with pytest.raises(
        CommandCenterHistoryError,
        match="COMMAND_CENTER_HISTORY_PAGE_SIZE_OUT_OF_RANGE",
    ):
        CommandCenterHistoryQuery(page_size=101)


def test_cursor_rejects_tampering_and_cross_query_reuse() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    repository.append(_snapshot(0))
    repository.append(_snapshot(1))
    first = repository.query(CommandCenterHistoryQuery(page_size=1))
    assert first.next_cursor is not None

    tampered = first.next_cursor[:-2] + ("AA" if first.next_cursor[-2:] != "AA" else "BB")
    with pytest.raises(CommandCenterHistoryError, match="COMMAND_CENTER_HISTORY_CURSOR_"):
        repository.query(CommandCenterHistoryQuery(page_size=1, cursor=tampered))

    with pytest.raises(
        CommandCenterHistoryError,
        match="COMMAND_CENTER_HISTORY_CURSOR_QUERY_MISMATCH",
    ):
        repository.query(
            CommandCenterHistoryQuery(
                page_size=1,
                order=CommandCenterHistoryOrder.OLDEST_FIRST,
                cursor=first.next_cursor,
            )
        )


def test_cursor_fails_closed_when_retention_evicts_its_anchor() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository(
        CommandCenterRetentionPolicy(max_records_per_scope=3)
    )
    for index in range(3):
        repository.append(_snapshot(index))
    first = repository.query(
        CommandCenterHistoryQuery(
            order=CommandCenterHistoryOrder.OLDEST_FIRST,
            page_size=1,
        )
    )
    assert first.next_cursor is not None

    repository.append(_snapshot(3))
    with pytest.raises(
        CommandCenterHistoryError,
        match="COMMAND_CENTER_HISTORY_CURSOR_ANCHOR_NOT_RETAINED",
    ):
        repository.query(
            CommandCenterHistoryQuery(
                order=CommandCenterHistoryOrder.OLDEST_FIRST,
                page_size=1,
                cursor=first.next_cursor,
            )
        )


def test_history_records_and_pages_remain_read_only_and_api_ready() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    snapshot = _snapshot(0)
    record = repository.append(snapshot).record
    page = repository.query(CommandCenterHistoryQuery())
    payload = page.to_dict()

    assert record.snapshot is snapshot
    assert payload["records"][0]["snapshot_id"] == snapshot.snapshot_id
    assert payload["records"][0]["component_ids"] == [
        component.component_id for component in snapshot.components
    ]
    assert payload["research_only"] is True
    assert payload["paper_ledger_mutation_authorized"] is False
    assert payload["portfolio_construction_authorized"] is False
    assert payload["execution_authorized"] is False
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False

    for item in (record, page):
        with pytest.raises(CommandCenterHistoryError, match="MUST_REMAIN_READ_ONLY"):
            replace(item, trading_authorized=True)
