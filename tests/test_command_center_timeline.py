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
from daily_alpha.agentic.command_center_audit import CommandCenterTransitionDirection
from daily_alpha.agentic.command_center_history import (
    BoundedInMemoryCommandCenterHistoryRepository,
    CommandCenterHistoryOrder,
    CommandCenterHistoryQuery,
    CommandCenterRetentionPolicy,
)
from daily_alpha.agentic.command_center_timeline import (
    CommandCenterTimelineError,
    InstitutionalCommandCenterTimelineService,
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


def test_timeline_composes_immediate_retained_predecessor_diffs() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    snapshots = (
        _snapshot(0),
        _snapshot(1, status=ReadinessStatus.WARNING),
        _snapshot(2, status=ReadinessStatus.BLOCKED),
    )
    for snapshot in snapshots:
        repository.append(snapshot)

    page = InstitutionalCommandCenterTimelineService(repository).query(
        CommandCenterHistoryQuery(
            order=CommandCenterHistoryOrder.OLDEST_FIRST,
            page_size=3,
        )
    )

    assert [entry.record.snapshot_id for entry in page.entries] == [
        snapshot.snapshot_id for snapshot in snapshots
    ]
    assert page.entries[0].audit_diff is None
    assert page.entries[1].predecessor_snapshot_id == snapshots[0].snapshot_id
    assert page.entries[1].audit_diff is not None
    assert page.entries[1].audit_diff.changes[0].transition_direction is (
        CommandCenterTransitionDirection.WORSENED
    )
    assert page.entries[2].predecessor_snapshot_id == snapshots[1].snapshot_id
    assert page.entries[2].audit_diff is not None
    assert page.entries[2].audit_diff.changes[0].transition_direction is (
        CommandCenterTransitionDirection.WORSENED
    )


def test_newest_first_pagination_preserves_chronological_predecessors() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    snapshots = [_snapshot(index) for index in range(4)]
    for snapshot in snapshots:
        repository.append(snapshot)
    service = InstitutionalCommandCenterTimelineService(repository)

    first = service.query(CommandCenterHistoryQuery(page_size=2))
    second = service.query(CommandCenterHistoryQuery(page_size=2, cursor=first.next_cursor))

    assert [entry.record.snapshot_id for entry in first.entries] == [
        snapshots[3].snapshot_id,
        snapshots[2].snapshot_id,
    ]
    assert first.entries[0].predecessor_snapshot_id == snapshots[2].snapshot_id
    assert first.entries[1].predecessor_snapshot_id == snapshots[1].snapshot_id
    assert [entry.record.snapshot_id for entry in second.entries] == [
        snapshots[1].snapshot_id,
        snapshots[0].snapshot_id,
    ]
    assert second.entries[0].predecessor_snapshot_id == snapshots[0].snapshot_id
    assert second.entries[1].audit_diff is None
    assert first.matched_count == second.matched_count == 4
    assert first.has_more is True
    assert second.has_more is False


def test_filtered_timeline_diff_uses_immediate_retained_truth_not_filtered_neighbor() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    first = _snapshot(0)
    blocked = _snapshot(1, status=ReadinessStatus.BLOCKED)
    recovered = _snapshot(2)
    for snapshot in (first, blocked, recovered):
        repository.append(snapshot)

    page = InstitutionalCommandCenterTimelineService(repository).query(
        CommandCenterHistoryQuery(
            status=ReadinessStatus.PASS,
            order=CommandCenterHistoryOrder.OLDEST_FIRST,
        )
    )

    assert [entry.record.snapshot_id for entry in page.entries] == [
        first.snapshot_id,
        recovered.snapshot_id,
    ]
    assert page.entries[0].audit_diff is None
    assert page.entries[1].predecessor_snapshot_id == blocked.snapshot_id
    assert page.entries[1].audit_diff is not None
    assert page.entries[1].audit_diff.changes[0].transition_direction is (
        CommandCenterTransitionDirection.IMPROVED
    )


def test_retention_gap_never_invents_an_evicted_predecessor() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository(
        CommandCenterRetentionPolicy(max_records_per_scope=2)
    )
    snapshots = [_snapshot(index) for index in range(3)]
    for snapshot in snapshots:
        repository.append(snapshot)

    page = InstitutionalCommandCenterTimelineService(repository).query(
        CommandCenterHistoryQuery(order=CommandCenterHistoryOrder.OLDEST_FIRST)
    )

    assert [entry.record.snapshot_id for entry in page.entries] == [
        snapshots[1].snapshot_id,
        snapshots[2].snapshot_id,
    ]
    assert page.entries[0].audit_diff is None
    assert page.entries[0].predecessor_snapshot_id is None
    assert page.entries[1].predecessor_snapshot_id == snapshots[1].snapshot_id


def test_timeline_preserves_exact_platform_portfolio_and_security_scopes() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    platform = _snapshot(0)
    portfolio = _snapshot(0, portfolio_id="SHADOW")
    security = _snapshot(0, security_id="MU")
    for snapshot in (platform, portfolio, security):
        repository.append(snapshot)
    service = InstitutionalCommandCenterTimelineService(repository)

    assert service.query(CommandCenterHistoryQuery()).entries[0].record.snapshot_id == (
        platform.snapshot_id
    )
    assert service.query(CommandCenterHistoryQuery(portfolio_id="shadow")).entries[
        0
    ].record.snapshot_id == portfolio.snapshot_id
    assert service.query(CommandCenterHistoryQuery(security_id="mu")).entries[
        0
    ].record.snapshot_id == security.snapshot_id


def test_get_and_serialization_are_deterministic_and_read_only() -> None:
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    first = _snapshot(0)
    second = _snapshot(1, status=ReadinessStatus.WARNING)
    repository.append(first)
    repository.append(second)
    service = InstitutionalCommandCenterTimelineService(repository)

    entry = service.get(second.snapshot_id)
    assert entry is not None
    page = service.query(CommandCenterHistoryQuery())
    payload = page.to_dict()

    assert entry.predecessor_snapshot_id == first.snapshot_id
    assert entry.entry_id == service.get(second.snapshot_id).entry_id
    assert payload["timeline_id"] == page.timeline_id
    assert payload["entries"][0]["record"]["snapshot_id"] == second.snapshot_id
    assert payload["research_only"] is True
    assert payload["paper_ledger_mutation_authorized"] is False
    assert payload["portfolio_construction_authorized"] is False
    assert payload["execution_authorized"] is False
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False

    with pytest.raises(CommandCenterTimelineError, match="ENTRY_MUST_REMAIN_READ_ONLY"):
        replace(entry, trading_authorized=True)
    with pytest.raises(CommandCenterTimelineError, match="PAGE_MUST_REMAIN_READ_ONLY"):
        replace(page, live_trading_enabled=True)
