"""Provider-neutral commercial beta subscription and launch controls.

This module is intentionally independent of any payment or identity vendor. It models
account state, billing-event idempotency, entitlement decisions, and launch readiness
without contacting customers, charging cards, or enabling brokerage execution.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class SubscriptionState(StrEnum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class BillingEventType(StrEnum):
    SUBSCRIPTION_STARTED = "SUBSCRIPTION_STARTED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    SUBSCRIPTION_CANCELED = "SUBSCRIPTION_CANCELED"
    SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
    SUSPENDED = "SUSPENDED"
    REACTIVATED = "REACTIVATED"
    TIER_CHANGED = "TIER_CHANGED"


@dataclass(frozen=True)
class BillingEvent:
    provider_event_id: str
    event_type: BillingEventType
    occurred_at: str
    tier_id: str | None = None

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.occurred_at)
        if not self.provider_event_id:
            raise ValueError("provider_event_id is required")
        if self.event_type in {
            BillingEventType.SUBSCRIPTION_STARTED,
            BillingEventType.TIER_CHANGED,
        } and not self.tier_id:
            raise ValueError(f"{self.event_type} requires tier_id")


@dataclass(frozen=True)
class SubscriptionProjection:
    customer_id: str
    tier_id: str | None = None
    state: SubscriptionState = SubscriptionState.EXPIRED
    last_event_at: str | None = None
    processed_event_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.customer_id:
            raise ValueError("customer_id is required")
        if self.last_event_at is not None:
            datetime.fromisoformat(self.last_event_at)


@dataclass(frozen=True)
class BillingApplyResult:
    projection: SubscriptionProjection
    disposition: str


def apply_billing_event(
    projection: SubscriptionProjection,
    event: BillingEvent,
) -> BillingApplyResult:
    """Apply one billing event idempotently and reject stale state regressions.

    Duplicate events are ignored. Events older than the last accepted billing event are
    also ignored rather than mutating entitlement state from stale information.
    """
    if event.provider_event_id in projection.processed_event_ids:
        return BillingApplyResult(projection=projection, disposition="DUPLICATE_IGNORED")

    if projection.last_event_at is not None:
        previous = datetime.fromisoformat(projection.last_event_at)
        current = datetime.fromisoformat(event.occurred_at)
        if current < previous:
            return BillingApplyResult(projection=projection, disposition="OUT_OF_ORDER_IGNORED")

    state = projection.state
    tier_id = projection.tier_id

    if event.event_type == BillingEventType.SUBSCRIPTION_STARTED:
        state = SubscriptionState.ACTIVE
        tier_id = event.tier_id
    elif event.event_type == BillingEventType.PAYMENT_SUCCEEDED:
        if tier_id is None:
            return BillingApplyResult(projection=projection, disposition="INVALID_STATE_IGNORED")
        state = SubscriptionState.ACTIVE
    elif event.event_type == BillingEventType.PAYMENT_FAILED:
        if tier_id is None:
            return BillingApplyResult(projection=projection, disposition="INVALID_STATE_IGNORED")
        state = SubscriptionState.PAST_DUE
    elif event.event_type == BillingEventType.SUBSCRIPTION_CANCELED:
        state = SubscriptionState.CANCELED
    elif event.event_type == BillingEventType.SUBSCRIPTION_EXPIRED:
        state = SubscriptionState.EXPIRED
    elif event.event_type == BillingEventType.SUSPENDED:
        state = SubscriptionState.SUSPENDED
    elif event.event_type == BillingEventType.REACTIVATED:
        if tier_id is None:
            return BillingApplyResult(projection=projection, disposition="INVALID_STATE_IGNORED")
        state = SubscriptionState.ACTIVE
    elif event.event_type == BillingEventType.TIER_CHANGED:
        if state not in {SubscriptionState.ACTIVE, SubscriptionState.TRIAL}:
            return BillingApplyResult(projection=projection, disposition="INVALID_STATE_IGNORED")
        tier_id = event.tier_id

    accepted = replace(
        projection,
        tier_id=tier_id,
        state=state,
        last_event_at=event.occurred_at,
        processed_event_ids=projection.processed_event_ids | {event.provider_event_id},
    )
    return BillingApplyResult(projection=accepted, disposition="APPLIED")


@dataclass(frozen=True)
class EntitlementCatalog:
    by_tier: dict[str, frozenset[str]]

    def __post_init__(self) -> None:
        if not self.by_tier:
            raise ValueError("at least one tier is required")
        if any(not tier for tier in self.by_tier):
            raise ValueError("tier identifiers cannot be blank")


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    reason: str


def check_entitlement(
    projection: SubscriptionProjection,
    catalog: EntitlementCatalog,
    entitlement: str,
) -> EntitlementDecision:
    """Fail closed unless account state and tier are explicitly entitled."""
    if not entitlement:
        return EntitlementDecision(False, "ENTITLEMENT_REQUIRED")
    if projection.state not in {SubscriptionState.ACTIVE, SubscriptionState.TRIAL}:
        return EntitlementDecision(False, f"ACCOUNT_{projection.state}")
    if projection.tier_id is None:
        return EntitlementDecision(False, "TIER_UNKNOWN")
    allowed = catalog.by_tier.get(projection.tier_id)
    if allowed is None:
        return EntitlementDecision(False, "TIER_UNKNOWN")
    if entitlement not in allowed:
        return EntitlementDecision(False, "NOT_ENTITLED")
    return EntitlementDecision(True, "ENTITLED")


@dataclass(frozen=True)
class CommercialBetaReadiness:
    reproducible_research_history: bool
    performance_basis_separation: bool
    delivery_monitoring: bool
    entitlement_isolation_tests: bool
    billing_reconciliation: bool
    external_legal_compliance_review: bool
    secrets_scan_passed: bool
    backup_restore_drill: bool
    incident_runbook_tested: bool
    support_owner_defined: bool
    rollback_disable_path_tested: bool
    live_brokerage_execution_enabled: bool = False

    @property
    def missing_gates(self) -> tuple[str, ...]:
        required = {
            "REPRODUCIBLE_RESEARCH_HISTORY": self.reproducible_research_history,
            "PERFORMANCE_BASIS_SEPARATION": self.performance_basis_separation,
            "DELIVERY_MONITORING": self.delivery_monitoring,
            "ENTITLEMENT_ISOLATION_TESTS": self.entitlement_isolation_tests,
            "BILLING_RECONCILIATION": self.billing_reconciliation,
            "EXTERNAL_LEGAL_COMPLIANCE_REVIEW": self.external_legal_compliance_review,
            "SECRETS_SCAN_PASSED": self.secrets_scan_passed,
            "BACKUP_RESTORE_DRILL": self.backup_restore_drill,
            "INCIDENT_RUNBOOK_TESTED": self.incident_runbook_tested,
            "SUPPORT_OWNER_DEFINED": self.support_owner_defined,
            "ROLLBACK_DISABLE_PATH_TESTED": self.rollback_disable_path_tested,
        }
        missing = [name for name, passed in required.items() if not passed]
        if self.live_brokerage_execution_enabled:
            missing.append("LIVE_EXECUTION_MUST_REMAIN_DISABLED_FOR_RESEARCH_BETA")
        return tuple(sorted(missing))

    @property
    def ready(self) -> bool:
        return not self.missing_gates
