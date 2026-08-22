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
from daily_alpha.agentic.command_center_api_contract import (
    CommandCenterAPIContractError,
    CommandCenterAPIOperation,
    CommandCenterAPIRequest,
    CommandCenterAPIResultStatus,
    InstitutionalCommandCenterAPIContract,
)
from daily_alpha.agentic.command_center_history import (
    BoundedInMemoryCommandCenterHistoryRepository,
    CommandCenterHistoryOrder,
)
from daily_alpha.agentic.command_center_timeline import InstitutionalCommandCenterTimelineService
from daily_alpha.agentic.contracts import ReadinessStatus


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def component(
    *,
    kind: CommandCenterComponentKind,
    entity_kind: CommandCenterEntityKind,
    entity_id: str,
    source_record_id: str,
    as_of: datetime = AS_OF,
    status: ReadinessStatus = ReadinessStatus.PASS,
    portfolio_id: str | None = None,
    security_id: str | None = None,
) -> CommandCenterComponent:
    warnings = ("REVIEW",) if status is ReadinessStatus.WARNING else ()
    blockers = ("BLOCK",) if status is ReadinessStatus.BLOCKED else ()
    return CommandCenterComponent(
        kind=kind,
        entity_kind=entity_kind,
        entity_id=entity_id,
        as_of=as_of,
        source_record_id=source_record_id,
        status=status,
        portfolio_id=portfolio_id,
        security_id=security_id,
        warnings=warnings,
        blockers=blockers,
    )


def snapshot(
    *,
    as_of: datetime = AS_OF,
    model_status: ReadinessStatus = ReadinessStatus.PASS,
):
    return InstitutionalCommandCenterBuilder.build(
        as_of=as_of,
        components=(
            component(
                kind=CommandCenterComponentKind.DATA_PLANE,
                entity_kind=CommandCenterEntityKind.PLATFORM,
                entity_id="DAILY_ALPHA",
                source_record_id="1" * 64,
                as_of=as_of,
            ),
            component(
                kind=CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
                entity_kind=CommandCenterEntityKind.PORTFOLIO,
                entity_id="SHADOW",
                source_record_id="2" * 64,
                as_of=as_of,
                portfolio_id="SHADOW",
            ),
            component(
                kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
                entity_kind=CommandCenterEntityKind.MODEL,
                entity_id="SH24:V2.4",
                source_record_id="3" * 64,
                as_of=as_of,
                status=model_status,
                security_id="MU",
            ),
        ),
    )


def service_with_history(*snapshots):
    repository = BoundedInMemoryCommandCenterHistoryRepository()
    for item in snapshots:
        repository.append(item)
    return InstitutionalCommandCenterTimelineService(repository)


def test_request_scope_and_identity_are_transport_neutral_and_deterministic() -> None:
    first = CommandCenterAPIRequest(
        operation=CommandCenterAPIOperation.PORTFOLIO_VIEW,
        platform_id="daily_alpha",
        portfolio_id="shadow",
    )
    second = CommandCenterAPIRequest(
        operation=CommandCenterAPIOperation.PORTFOLIO_VIEW,
        portfolio_id="SHADOW",
    )

    assert first.platform_id == "DAILY_ALPHA"
    assert first.portfolio_id == "SHADOW"
    assert first.request_id == second.request_id
    assert first.to_dict()["trading_authorized"] is False
    with pytest.raises(CommandCenterAPIContractError, match="HISTORY_FIELDS_REQUIRE_TIMELINE"):
        CommandCenterAPIRequest(
            operation=CommandCenterAPIOperation.CURRENT_SNAPSHOT,
            start_as_of=AS_OF,
        )


def test_current_and_drilldown_responses_preserve_governed_snapshot_truth() -> None:
    current = snapshot(model_status=ReadinessStatus.WARNING)
    contract = InstitutionalCommandCenterAPIContract(service_with_history(current))

    current_response = contract.execute(
        CommandCenterAPIRequest(operation=CommandCenterAPIOperation.CURRENT_SNAPSHOT),
        current_snapshot=current,
    )
    portfolio_response = contract.execute(
        CommandCenterAPIRequest(
            operation=CommandCenterAPIOperation.PORTFOLIO_VIEW,
            portfolio_id="SHADOW",
        ),
        current_snapshot=current,
    )
    security_response = contract.execute(
        CommandCenterAPIRequest(
            operation=CommandCenterAPIOperation.SECURITY_VIEW,
            security_id="MU",
        ),
        current_snapshot=current,
    )

    assert current_response.result_status is CommandCenterAPIResultStatus.OK
    assert current_response.resource_id == current.snapshot_id
    assert current_response.payload["status"] == "WARNING"
    assert portfolio_response.payload["scope_id"] == "SHADOW"
    assert security_response.payload["scope_id"] == "MU"
    assert security_response.payload["status"] == "WARNING"
    for response in (current_response, portfolio_response, security_response):
        assert response.trading_authorized is False
        assert response.live_trading_enabled is False


def test_missing_drilldown_scope_returns_deterministic_not_found() -> None:
    current = snapshot()
    contract = InstitutionalCommandCenterAPIContract(service_with_history(current))
    request = CommandCenterAPIRequest(
        operation=CommandCenterAPIOperation.SECURITY_VIEW,
        security_id="NVDA",
    )

    first = contract.execute(request, current_snapshot=current)
    second = contract.execute(request, current_snapshot=current)

    assert first.result_status is CommandCenterAPIResultStatus.NOT_FOUND
    assert first.payload is None
    assert first.resource_id is None
    assert current.snapshot_id in first.upstream_ids
    assert first.response_id == second.response_id


def test_current_snapshot_platform_mismatch_fails_closed() -> None:
    current = snapshot()
    contract = InstitutionalCommandCenterAPIContract(service_with_history(current))
    request = CommandCenterAPIRequest(
        operation=CommandCenterAPIOperation.CURRENT_SNAPSHOT,
        platform_id="OTHER_PLATFORM",
    )

    with pytest.raises(CommandCenterAPIContractError, match="PLATFORM_MISMATCH"):
        contract.execute(request, current_snapshot=current)


def test_timeline_request_preserves_history_pagination_and_cursor_contract() -> None:
    oldest = snapshot(as_of=AS_OF - timedelta(days=2))
    middle = snapshot(as_of=AS_OF - timedelta(days=1), model_status=ReadinessStatus.WARNING)
    newest = snapshot(as_of=AS_OF)
    contract = InstitutionalCommandCenterAPIContract(
        service_with_history(oldest, middle, newest)
    )
    first_request = CommandCenterAPIRequest(
        operation=CommandCenterAPIOperation.TIMELINE,
        order=CommandCenterHistoryOrder.NEWEST_FIRST,
        page_size=2,
    )

    first = contract.execute(first_request)
    assert first.result_status is CommandCenterAPIResultStatus.OK
    assert first.payload["returned_count"] == 2
    assert first.payload["has_more"] is True
    cursor = first.payload["next_cursor"]
    assert cursor

    second_request = replace(first_request, cursor=cursor)
    second = contract.execute(second_request)
    assert second.payload["returned_count"] == 1
    assert second.payload["has_more"] is False
    assert first_request.request_id != second_request.request_id
    assert first.payload["history_query_id"] == second.payload["history_query_id"]


def test_timeline_status_filter_and_read_only_response_remain_exact() -> None:
    clean = snapshot(as_of=AS_OF - timedelta(days=1))
    warning = snapshot(as_of=AS_OF, model_status=ReadinessStatus.WARNING)
    contract = InstitutionalCommandCenterAPIContract(service_with_history(clean, warning))
    request = CommandCenterAPIRequest(
        operation=CommandCenterAPIOperation.TIMELINE,
        status=ReadinessStatus.WARNING,
    )

    response = contract.execute(request)
    assert response.result_status is CommandCenterAPIResultStatus.OK
    assert response.payload["returned_count"] == 1
    assert response.payload["entries"][0]["record"]["snapshot_id"] == warning.snapshot_id
    assert response.payload["entries"][0]["diff_available"] is True
    assert response.to_dict()["execution_authorized"] is False
    with pytest.raises(CommandCenterAPIContractError, match="RESPONSE_MUST_REMAIN_READ_ONLY"):
        replace(response, trading_authorized=True)
