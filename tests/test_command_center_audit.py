from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.command_center import (
    CommandCenterComponent,
    CommandCenterComponentKind,
    CommandCenterEntityKind,
    InstitutionalCommandCenterBuilder,
)
from daily_alpha.agentic.command_center_audit import (
    CommandCenterAuditError,
    CommandCenterChangeKind,
    CommandCenterTransitionDirection,
    InstitutionalCommandCenterAuditBuilder,
)
from daily_alpha.agentic.contracts import ReadinessStatus


PREVIOUS_AS_OF = datetime(2026, 8, 21, 19, 0, tzinfo=UTC)
CURRENT_AS_OF = PREVIOUS_AS_OF + timedelta(hours=1)


def _component(
    *,
    as_of: datetime,
    kind: CommandCenterComponentKind,
    entity_kind: CommandCenterEntityKind,
    entity_id: str,
    source: str,
    status: ReadinessStatus = ReadinessStatus.PASS,
    security_id: str | None = None,
    portfolio_id: str | None = None,
    metrics: dict[str, object] | None = None,
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    lineage: tuple[str, ...] = (),
) -> CommandCenterComponent:
    return CommandCenterComponent(
        kind=kind,
        entity_kind=entity_kind,
        entity_id=entity_id,
        as_of=as_of,
        source_record_id=source,
        status=status,
        security_id=security_id,
        portfolio_id=portfolio_id,
        metrics=metrics or {},
        blockers=blockers,
        warnings=warnings,
        lineage_ids=lineage,
    )


def _snapshots(*, reverse: bool = False):
    previous_components = (
        _component(
            as_of=PREVIOUS_AS_OF,
            kind=CommandCenterComponentKind.DATA_PLANE,
            entity_kind=CommandCenterEntityKind.PLATFORM,
            entity_id="DAILY_ALPHA",
            source="1" * 64,
        ),
        _component(
            as_of=PREVIOUS_AS_OF,
            kind=CommandCenterComponentKind.PROVIDER_RELIABILITY,
            entity_kind=CommandCenterEntityKind.PROVIDER,
            entity_id="DATABENTO:MARKET_BARS",
            source="2" * 64,
            metrics={"healthy_ratio": 1.0},
        ),
        _component(
            as_of=PREVIOUS_AS_OF,
            kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id="SH24:V2.4",
            source="3" * 64,
            security_id="MU",
            metrics={"expectancy_r": 0.40},
            lineage=("a" * 64,),
        ),
        _component(
            as_of=PREVIOUS_AS_OF,
            kind=CommandCenterComponentKind.CIO_DECISION,
            entity_kind=CommandCenterEntityKind.DECISION,
            entity_id="MU:CIO",
            source="4" * 64,
            status=ReadinessStatus.WARNING,
            security_id="MU",
            warnings=("CIO_WAIT",),
        ),
        _component(
            as_of=PREVIOUS_AS_OF,
            kind=CommandCenterComponentKind.RISK_GOVERNOR,
            entity_kind=CommandCenterEntityKind.PORTFOLIO,
            entity_id="SHADOW:RISK",
            source="5" * 64,
            portfolio_id="SHADOW",
        ),
        _component(
            as_of=PREVIOUS_AS_OF,
            kind=CommandCenterComponentKind.MODEL_STRESS,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id="SH25:V1",
            source="6" * 64,
            security_id="MU",
        ),
    )
    current_components = (
        _component(
            as_of=CURRENT_AS_OF,
            kind=CommandCenterComponentKind.DATA_PLANE,
            entity_kind=CommandCenterEntityKind.PLATFORM,
            entity_id="DAILY_ALPHA",
            source="7" * 64,
        ),
        _component(
            as_of=CURRENT_AS_OF,
            kind=CommandCenterComponentKind.PROVIDER_RELIABILITY,
            entity_kind=CommandCenterEntityKind.PROVIDER,
            entity_id="DATABENTO:MARKET_BARS",
            source="8" * 64,
            status=ReadinessStatus.WARNING,
            metrics={"healthy_ratio": 0.8},
            warnings=("PROVIDER_DEGRADED",),
        ),
        _component(
            as_of=CURRENT_AS_OF,
            kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
            entity_kind=CommandCenterEntityKind.MODEL,
            entity_id="SH24:V2.4",
            source="9" * 64,
            status=ReadinessStatus.WARNING,
            security_id="MU",
            metrics={"expectancy_r": 0.05},
            warnings=("ALPHA_DECAY",),
            lineage=("b" * 64,),
        ),
        _component(
            as_of=CURRENT_AS_OF,
            kind=CommandCenterComponentKind.CIO_DECISION,
            entity_kind=CommandCenterEntityKind.DECISION,
            entity_id="MU:CIO",
            source="c" * 64,
            security_id="MU",
        ),
        _component(
            as_of=CURRENT_AS_OF,
            kind=CommandCenterComponentKind.RISK_GOVERNOR,
            entity_kind=CommandCenterEntityKind.PORTFOLIO,
            entity_id="SHADOW:RISK",
            source="d" * 64,
            status=ReadinessStatus.BLOCKED,
            portfolio_id="SHADOW",
            blockers=("DRAWDOWN_THROTTLE_BLOCKS_NEW_RISK",),
        ),
        _component(
            as_of=CURRENT_AS_OF,
            kind=CommandCenterComponentKind.INCIDENT,
            entity_kind=CommandCenterEntityKind.PROVIDER,
            entity_id="DATABENTO:INCIDENT:OPEN",
            source="e" * 64,
            status=ReadinessStatus.WARNING,
            warnings=("ACTIVE_PROVIDER_INCIDENT",),
        ),
    )
    if reverse:
        previous_components = tuple(reversed(previous_components))
        current_components = tuple(reversed(current_components))
    return (
        InstitutionalCommandCenterBuilder.build(
            as_of=PREVIOUS_AS_OF,
            components=previous_components,
        ),
        InstitutionalCommandCenterBuilder.build(
            as_of=CURRENT_AS_OF,
            components=current_components,
        ),
    )


def test_audit_diff_preserves_exact_changes_and_status_direction() -> None:
    previous, current = _snapshots()
    audit = InstitutionalCommandCenterAuditBuilder.build(previous=previous, current=current)

    assert audit.previous_snapshot_id == previous.snapshot_id
    assert audit.current_snapshot_id == current.snapshot_id
    assert audit.previous_status is ReadinessStatus.WARNING
    assert audit.current_status is ReadinessStatus.BLOCKED
    assert audit.added_count == 1
    assert audit.removed_count == 1
    assert audit.status_changed_count == 4
    assert audit.content_changed_count == 0
    assert audit.refreshed_count == 1
    assert audit.worsened_count == 3
    assert audit.improved_count == 1

    by_kind_entity = {
        (item.component_kind, item.entity_id): item
        for item in audit.changes
    }
    provider = by_kind_entity[
        (CommandCenterComponentKind.PROVIDER_RELIABILITY, "DATABENTO:MARKET_BARS")
    ]
    model = by_kind_entity[(CommandCenterComponentKind.MODEL_PERFORMANCE, "SH24:V2.4")]
    cio = by_kind_entity[(CommandCenterComponentKind.CIO_DECISION, "MU:CIO")]
    incident = by_kind_entity[
        (CommandCenterComponentKind.INCIDENT, "DATABENTO:INCIDENT:OPEN")
    ]
    stress = by_kind_entity[(CommandCenterComponentKind.MODEL_STRESS, "SH25:V1")]
    refreshed = by_kind_entity[(CommandCenterComponentKind.DATA_PLANE, "DAILY_ALPHA")]

    assert provider.change_kind is CommandCenterChangeKind.STATUS_CHANGED
    assert provider.transition_direction is CommandCenterTransitionDirection.WORSENED
    assert model.transition_direction is CommandCenterTransitionDirection.WORSENED
    assert model.previous_lineage_ids == ("a" * 64,)
    assert model.current_lineage_ids == ("b" * 64,)
    assert cio.transition_direction is CommandCenterTransitionDirection.IMPROVED
    assert incident.change_kind is CommandCenterChangeKind.ADDED
    assert incident.previous_component_id is None
    assert stress.change_kind is CommandCenterChangeKind.REMOVED
    assert stress.current_component_id is None
    assert refreshed.change_kind is CommandCenterChangeKind.REFRESHED
    assert refreshed.transition_direction is CommandCenterTransitionDirection.UNCHANGED


def test_same_status_display_change_is_content_change_not_status_transition() -> None:
    previous_component = _component(
        as_of=PREVIOUS_AS_OF,
        kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
        entity_kind=CommandCenterEntityKind.MODEL,
        entity_id="SH24:V2.4",
        source="1" * 64,
        metrics={"expectancy_r": 0.4},
    )
    current_component = _component(
        as_of=CURRENT_AS_OF,
        kind=CommandCenterComponentKind.MODEL_PERFORMANCE,
        entity_kind=CommandCenterEntityKind.MODEL,
        entity_id="SH24:V2.4",
        source="2" * 64,
        metrics={"expectancy_r": 0.3},
    )
    previous = InstitutionalCommandCenterBuilder.build(
        as_of=PREVIOUS_AS_OF,
        components=(previous_component,),
    )
    current = InstitutionalCommandCenterBuilder.build(
        as_of=CURRENT_AS_OF,
        components=(current_component,),
    )

    audit = InstitutionalCommandCenterAuditBuilder.build(previous=previous, current=current)

    assert len(audit.changes) == 1
    assert audit.changes[0].change_kind is CommandCenterChangeKind.CONTENT_CHANGED
    assert audit.changes[0].transition_direction is CommandCenterTransitionDirection.UNCHANGED
    assert audit.content_changed_count == 1
    assert audit.worsened_count == 0
    assert audit.improved_count == 0


def test_audit_diff_is_input_order_stable_and_api_ready() -> None:
    first_previous, first_current = _snapshots()
    second_previous, second_current = _snapshots(reverse=True)

    first = InstitutionalCommandCenterAuditBuilder.build(
        previous=first_previous,
        current=first_current,
    )
    second = InstitutionalCommandCenterAuditBuilder.build(
        previous=second_previous,
        current=second_current,
    )

    assert first.diff_id == second.diff_id
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert payload["research_only"] is True
    assert payload["paper_ledger_mutation_authorized"] is False
    assert payload["portfolio_construction_authorized"] is False
    assert payload["execution_authorized"] is False
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False


def test_audit_diff_fails_closed_on_reverse_time_and_scope_mismatch() -> None:
    previous, current = _snapshots()

    with pytest.raises(CommandCenterAuditError, match="COMMAND_CENTER_AUDIT_TIME_MUST_INCREASE"):
        InstitutionalCommandCenterAuditBuilder.build(previous=current, current=previous)

    previous_portfolio = InstitutionalCommandCenterBuilder.build(
        as_of=PREVIOUS_AS_OF,
        portfolio_id="SHADOW",
        components=(
            _component(
                as_of=PREVIOUS_AS_OF,
                kind=CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
                entity_kind=CommandCenterEntityKind.PORTFOLIO,
                entity_id="SHADOW",
                source="1" * 64,
                portfolio_id="SHADOW",
            ),
        ),
    )
    current_portfolio = InstitutionalCommandCenterBuilder.build(
        as_of=CURRENT_AS_OF,
        portfolio_id="WEALTH",
        components=(
            _component(
                as_of=CURRENT_AS_OF,
                kind=CommandCenterComponentKind.PORTFOLIO_PROPOSAL,
                entity_kind=CommandCenterEntityKind.PORTFOLIO,
                entity_id="WEALTH",
                source="2" * 64,
                portfolio_id="WEALTH",
            ),
        ),
    )

    with pytest.raises(
        CommandCenterAuditError,
        match="COMMAND_CENTER_AUDIT_PORTFOLIO_SCOPE_MISMATCH",
    ):
        InstitutionalCommandCenterAuditBuilder.build(
            previous=previous_portfolio,
            current=current_portfolio,
        )
