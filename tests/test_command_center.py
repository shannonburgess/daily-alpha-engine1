from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
    CommandCenterError,
    InstitutionalCommandCenterBuilder,
    InstitutionalCommandCenterSnapshot,
)
from daily_alpha.agentic.contracts import ReadinessStatus


AS_OF = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def component(
    *,
    kind: CommandCenterComponentKind = CommandCenterComponentKind.MODEL_STRESS,
    entity_kind: CommandCenterEntityKind = CommandCenterEntityKind.MODEL,
    entity_id: str = "SH24:v2.4",
    status: ReadinessStatus = ReadinessStatus.PASS,
    as_of: datetime = AS_OF,
    source_record_id: str = "a" * 64,
    security_id: str | None = "MU",
    portfolio_id: str | None = "SHADOW",
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> CommandCenterComponent:
    return CommandCenterComponent(
        kind=kind,
        entity_kind=entity_kind,
        entity_id=entity_id,
        as_of=as_of,
        source_record_id=source_record_id,
        status=status,
        headline="institutional projection",
        security_id=security_id,
        portfolio_id=portfolio_id,
        metrics={"expectancy_r": 0.42, "sample_size": 88},
        blockers=blockers,
        warnings=warnings,
        lineage_ids=("C" * 64, "b" * 64),
    )


def test_clean_snapshot_is_pass_api_ready_and_deterministic() -> None:
    data = component(
        kind=CommandCenterComponentKind.DATA_PLANE,
        entity_kind=CommandCenterEntityKind.PLATFORM,
        entity_id="DAILY_ALPHA",
        source_record_id="1" * 64,
        security_id=None,
        portfolio_id=None,
    )
    stress = component(source_record_id="2" * 64)
    first = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(stress, data),
        portfolio_id="shadow",
        security_id="mu",
    )
    second = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(data, stress),
        portfolio_id="SHADOW",
        security_id="MU",
    )

    assert first.status is ReadinessStatus.PASS
    assert first.pass_count == 2
    assert first.warning_count == 0
    assert first.blocked_count == 0
    assert first.unresolved_issue_count == 0
    assert first.snapshot_id == second.snapshot_id
    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["components"][0]["component_id"]
    assert first.to_dict()["component_ids"] == sorted(first.to_dict()["component_ids"])


def test_warning_and_blocked_components_roll_up_without_upgrade() -> None:
    warning = component(
        kind=CommandCenterComponentKind.PROVIDER_RELIABILITY,
        entity_kind=CommandCenterEntityKind.PROVIDER,
        entity_id="DATABENTO",
        source_record_id="3" * 64,
        status=ReadinessStatus.WARNING,
        warnings=("INSUFFICIENT_HISTORY",),
        security_id=None,
        portfolio_id=None,
    )
    blocked = component(
        kind=CommandCenterComponentKind.RISK_GOVERNOR,
        entity_kind=CommandCenterEntityKind.DECISION,
        entity_id="RISK-001",
        source_record_id="4" * 64,
        status=ReadinessStatus.BLOCKED,
        blockers=("POSITION_LIMIT",),
    )

    warning_snapshot = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(warning,),
    )
    blocked_snapshot = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(warning, blocked),
    )

    assert warning_snapshot.status is ReadinessStatus.WARNING
    assert warning_snapshot.warning_count == 1
    assert warning_snapshot.unresolved_issue_count == 1
    assert blocked_snapshot.status is ReadinessStatus.BLOCKED
    assert blocked_snapshot.blocked_count == 1
    assert blocked_snapshot.unresolved_issue_count == 2


def test_future_and_stale_components_fail_closed() -> None:
    future = component(as_of=AS_OF + timedelta(seconds=1))
    stale = component(as_of=AS_OF - timedelta(seconds=1))

    with pytest.raises(CommandCenterError, match="FUTURE_COMMAND_CENTER_COMPONENT_NOT_ALLOWED"):
        InstitutionalCommandCenterBuilder.build(as_of=AS_OF, components=(future,))
    with pytest.raises(CommandCenterError, match="STALE_COMMAND_CENTER_COMPONENT_NOT_ALLOWED"):
        InstitutionalCommandCenterBuilder.build(as_of=AS_OF, components=(stale,))


def test_security_and_portfolio_identity_mismatches_fail_closed() -> None:
    wrong_security = component(security_id="NVDA")
    wrong_portfolio = component(portfolio_id="OTHER")

    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_SECURITY_ID_MISMATCH"):
        InstitutionalCommandCenterBuilder.build(
            as_of=AS_OF,
            components=(wrong_security,),
            security_id="MU",
        )
    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_PORTFOLIO_ID_MISMATCH"):
        InstitutionalCommandCenterBuilder.build(
            as_of=AS_OF,
            components=(wrong_portfolio,),
            portfolio_id="SHADOW",
        )


def test_identical_duplicates_deduplicate_but_conflicting_logical_slot_blocks() -> None:
    original = component()
    same = component()
    deduped = InstitutionalCommandCenterBuilder.build(
        as_of=AS_OF,
        components=(same, original),
    )
    assert len(deduped.components) == 1

    conflict = replace(original, source_record_id="9" * 64)
    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_COMPONENT_LOGICAL_SLOT_CONFLICT"):
        InstitutionalCommandCenterBuilder.build(
            as_of=AS_OF,
            components=(original, conflict),
        )


def test_component_status_contract_is_fail_closed() -> None:
    with pytest.raises(CommandCenterError, match="PASS_COMMAND_CENTER_COMPONENT_CANNOT_HAVE_ISSUES"):
        component(warnings=("SHOULD_NOT_EXIST",))
    with pytest.raises(CommandCenterError, match="WARNING_COMMAND_CENTER_COMPONENT_REQUIRES_WARNING"):
        component(status=ReadinessStatus.WARNING)
    with pytest.raises(CommandCenterError, match="BLOCKED_COMMAND_CENTER_COMPONENT_REQUIRES_BLOCKER"):
        component(status=ReadinessStatus.BLOCKED)


def test_entity_scope_requirements_are_explicit() -> None:
    with pytest.raises(CommandCenterError, match="SECURITY_COMPONENT_REQUIRES_SECURITY_ID"):
        component(
            entity_kind=CommandCenterEntityKind.SECURITY,
            entity_id="MU",
            security_id=None,
        )
    with pytest.raises(CommandCenterError, match="PORTFOLIO_COMPONENT_REQUIRES_PORTFOLIO_ID"):
        component(
            entity_kind=CommandCenterEntityKind.PORTFOLIO,
            entity_id="SHADOW",
            portfolio_id=None,
        )


def test_metrics_and_lineage_are_canonicalized_for_api_replay() -> None:
    projected = CommandCenterComponent(
        kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
        entity_kind=CommandCenterEntityKind.MODEL,
        entity_id="SH25:v1",
        as_of=AS_OF,
        source_record_id="F" * 64,
        status=ReadinessStatus.PASS,
        metrics=(("z_metric", 3), ("a_metric", {"value": 1.25})),
        lineage_ids=("D" * 64, "c" * 64, "D" * 64),
    )

    assert tuple(name for name, _ in projected.metrics) == ("a_metric", "z_metric")
    assert projected.lineage_ids == ("c" * 64, "d" * 64)
    assert projected.to_dict()["source_record_id"] == "f" * 64
    assert projected.to_dict()["metrics"]["a_metric"] == {"value": 1.25}


def test_snapshot_constructor_rejects_forged_counts_or_status() -> None:
    projected = component()
    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_SNAPSHOT_COUNT_MISMATCH"):
        InstitutionalCommandCenterSnapshot(
            as_of=AS_OF,
            platform_id="DAILY_ALPHA",
            components=(projected,),
            status=ReadinessStatus.PASS,
            pass_count=0,
            warning_count=0,
            blocked_count=0,
            unresolved_issue_count=0,
        )
    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_SNAPSHOT_STATUS_MISMATCH"):
        InstitutionalCommandCenterSnapshot(
            as_of=AS_OF,
            platform_id="DAILY_ALPHA",
            components=(projected,),
            status=ReadinessStatus.WARNING,
            pass_count=1,
            warning_count=0,
            blocked_count=0,
            unresolved_issue_count=0,
        )


def test_command_center_has_no_mutation_or_trading_authority() -> None:
    projected = component()
    snapshot = InstitutionalCommandCenterBuilder.build(as_of=AS_OF, components=(projected,))

    for item in (projected, snapshot):
        assert item.research_only is True
        assert item.paper_ledger_mutation_authorized is False
        assert item.portfolio_construction_authorized is False
        assert item.execution_authorized is False
        assert item.trading_authorized is False
        assert item.live_trading_enabled is False

    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_COMPONENT_MUST_REMAIN_READ_ONLY"):
        replace(projected, execution_authorized=True)
    with pytest.raises(CommandCenterError, match="COMMAND_CENTER_SNAPSHOT_MUST_REMAIN_READ_ONLY"):
        replace(snapshot, trading_authorized=True)
