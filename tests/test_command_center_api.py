from __future__ import annotations

from datetime import UTC, datetime

from daily_alpha.agentic.command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
    InstitutionalCommandCenterBuilder,
)
from daily_alpha.agentic.command_center_api import (
    CommandCenterScopeKind,
    InstitutionalCommandCenterAPIBuilder,
)
from daily_alpha.agentic.contracts import ReadinessStatus


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _component(
    *,
    kind: CommandCenterComponentKind,
    entity_kind: CommandCenterEntityKind,
    entity_id: str,
    source_record_id: str,
    status: ReadinessStatus,
    security_id: str | None = None,
    portfolio_id: str | None = None,
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> CommandCenterComponent:
    return CommandCenterComponent(
        kind=kind,
        entity_kind=entity_kind,
        entity_id=entity_id,
        security_id=security_id,
        portfolio_id=portfolio_id,
        as_of=AS_OF,
        source_record_id=source_record_id,
        status=status,
        blockers=blockers,
        warnings=warnings,
    )


def _snapshot(order_reversed: bool = False):
    components = (
        _component(
            kind=CommandCenterComponentKind.DATA_PLANE,
            entity_kind=CommandCenterEntityKind.PLATFORM,
            entity_id="DAILY_ALPHA",
            source_record_id="1" * 64,
            status=ReadinessStatus.PASS,
        ),
        _component(
            kind=CommandCenterComponentKind.RESEARCH_COUNCIL,
            entity_kind=CommandCenterEntityKind.SECURITY,
            entity_id="MU",
            security_id="MU",
            source_record_id="2" * 64,
            status=ReadinessStatus.WARNING,
            warnings=("COUNCIL_DISAGREEMENT",),
        ),
        _component(
            kind=CommandCenterComponentKind.CIO_DECISION,
            entity_kind=CommandCenterEntityKind.DECISION,
            entity_id="MU:CIO",
            security_id="MU",
            source_record_id="3" * 64,
            status=ReadinessStatus.WARNING,
            warnings=("CIO_WAIT",),
        ),
        _component(
            kind=CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
            entity_kind=CommandCenterEntityKind.PORTFOLIO,
            entity_id="SHADOW",
            portfolio_id="SHADOW",
            source_record_id="4" * 64,
            status=ReadinessStatus.PASS,
        ),
        _component(
            kind=CommandCenterComponentKind.RISK_GOVERNOR,
            entity_kind=CommandCenterEntityKind.PORTFOLIO,
            entity_id="SHADOW:RISK",
            portfolio_id="SHADOW",
            source_record_id="5" * 64,
            status=ReadinessStatus.BLOCKED,
            blockers=("DRAWDOWN_THROTTLE_BLOCKS_NEW_RISK",),
        ),
    )
    if order_reversed:
        components = tuple(reversed(components))
    return InstitutionalCommandCenterBuilder.build(as_of=AS_OF, components=components)


def test_api_view_exposes_portfolio_security_and_platform_drilldowns() -> None:
    view = InstitutionalCommandCenterAPIBuilder.build(_snapshot())

    security = view.security("mu")
    portfolio = view.portfolio("shadow")
    assert security is not None
    assert portfolio is not None
    assert view.platform_scope.scope_kind is CommandCenterScopeKind.PLATFORM
    assert view.platform_scope.status is ReadinessStatus.BLOCKED
    assert security.scope_kind is CommandCenterScopeKind.SECURITY
    assert security.status is ReadinessStatus.WARNING
    assert {item.kind for item in security.components} == {
        CommandCenterComponentKind.RESEARCH_COUNCIL,
        CommandCenterComponentKind.CIO_DECISION,
    }
    assert portfolio.scope_kind is CommandCenterScopeKind.PORTFOLIO
    assert portfolio.status is ReadinessStatus.BLOCKED
    assert {item.kind for item in portfolio.components} == {
        CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
        CommandCenterComponentKind.RISK_GOVERNOR,
    }
    assert view.security("NVDA") is None
    assert view.portfolio("WEALTH") is None

    payload = view.to_dict()
    assert payload["snapshot_id"] == view.snapshot.snapshot_id
    assert payload["status"] == "BLOCKED"
    assert payload["research_only"] is True
    assert payload["paper_ledger_mutation_authorized"] is False
    assert payload["portfolio_construction_authorized"] is False
    assert payload["execution_authorized"] is False
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False


def test_api_view_identity_is_input_order_stable_and_preserves_severity() -> None:
    first = InstitutionalCommandCenterAPIBuilder.build(_snapshot())
    second = InstitutionalCommandCenterAPIBuilder.build(_snapshot(order_reversed=True))

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.api_view_id == second.api_view_id
    assert first.to_dict() == second.to_dict()
    assert first.platform_scope.blocked_count == 1
    assert first.platform_scope.warning_count == 2
    assert first.platform_scope.pass_count == 2
    assert first.platform_scope.unresolved_issue_count == 3
