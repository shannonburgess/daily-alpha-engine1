import pytest

from daily_alpha.commercial_beta import (
    BillingEvent,
    BillingEventType,
    CommercialBetaReadiness,
    EntitlementCatalog,
    OverrideAction,
    PrivilegedEntitlementOverrideAudit,
    SubscriptionProjection,
    SubscriptionState,
    apply_billing_event,
    check_entitlement,
)


def _active_projection() -> SubscriptionProjection:
    return SubscriptionProjection(
        customer_id="cust-1",
        tier_id="research",
        state=SubscriptionState.ACTIVE,
        last_event_at="2026-08-16T20:00:00-07:00",
        processed_event_ids=frozenset({"evt-start"}),
    )


def _ready(**overrides: bool) -> CommercialBetaReadiness:
    values = {
        "reproducible_research_history": True,
        "research_provenance_replay": True,
        "performance_basis_separation": True,
        "performance_methodology_contract": True,
        "customer_visible_claim_gate": True,
        "delivery_monitoring": True,
        "entitlement_isolation_tests": True,
        "billing_reconciliation": True,
        "privileged_override_audit": True,
        "external_legal_compliance_review": True,
        "terms_privacy_support_complete": True,
        "customer_data_retention_controls": True,
        "secrets_scan_passed": True,
        "backup_restore_drill": True,
        "incident_runbook_tested": True,
        "support_owner_defined": True,
        "rollback_disable_path_tested": True,
        "live_brokerage_execution_enabled": False,
    }
    values.update(overrides)
    return CommercialBetaReadiness(**values)


def test_active_customer_receives_only_catalog_entitlements():
    catalog = EntitlementCatalog(
        by_tier={
            "research": frozenset({"MORNING_NOTE", "EVENING_BRIEF"}),
            "research_plus": frozenset(
                {"MORNING_NOTE", "EVENING_BRIEF", "QUANT_DASHBOARD"}
            ),
        }
    )
    projection = _active_projection()

    assert check_entitlement(projection, catalog, "MORNING_NOTE").allowed is True
    denied = check_entitlement(projection, catalog, "QUANT_DASHBOARD")
    assert denied.allowed is False
    assert denied.reason == "NOT_ENTITLED"


def test_past_due_customer_fails_closed():
    catalog = EntitlementCatalog(by_tier={"research": frozenset({"MORNING_NOTE"})})
    projection = SubscriptionProjection(
        customer_id="cust-1",
        tier_id="research",
        state=SubscriptionState.PAST_DUE,
    )

    decision = check_entitlement(projection, catalog, "MORNING_NOTE")
    assert decision.allowed is False
    assert decision.reason == "ACCOUNT_PAST_DUE"


def test_duplicate_billing_event_is_idempotent():
    projection = _active_projection()
    duplicate = BillingEvent(
        provider_event_id="evt-start",
        event_type=BillingEventType.SUBSCRIPTION_STARTED,
        occurred_at="2026-08-16T20:00:00-07:00",
        tier_id="research",
    )

    result = apply_billing_event(projection, duplicate)
    assert result.disposition == "DUPLICATE_IGNORED"
    assert result.projection == projection


def test_out_of_order_billing_event_does_not_regress_state():
    projection = _active_projection()
    stale_failure = BillingEvent(
        provider_event_id="evt-old-failure",
        event_type=BillingEventType.PAYMENT_FAILED,
        occurred_at="2026-08-16T19:59:59-07:00",
    )

    result = apply_billing_event(projection, stale_failure)
    assert result.disposition == "OUT_OF_ORDER_IGNORED"
    assert result.projection.state == SubscriptionState.ACTIVE


def test_payment_failure_moves_active_customer_to_past_due():
    projection = _active_projection()
    failure = BillingEvent(
        provider_event_id="evt-failure",
        event_type=BillingEventType.PAYMENT_FAILED,
        occurred_at="2026-08-16T20:01:00-07:00",
    )

    result = apply_billing_event(projection, failure)
    assert result.disposition == "APPLIED"
    assert result.projection.state == SubscriptionState.PAST_DUE
    assert "evt-failure" in result.projection.processed_event_ids


def test_tier_change_requires_active_or_trial_account():
    projection = SubscriptionProjection(
        customer_id="cust-1",
        tier_id="research",
        state=SubscriptionState.CANCELED,
        last_event_at="2026-08-16T20:00:00-07:00",
    )
    tier_change = BillingEvent(
        provider_event_id="evt-tier",
        event_type=BillingEventType.TIER_CHANGED,
        occurred_at="2026-08-16T20:01:00-07:00",
        tier_id="research_plus",
    )

    result = apply_billing_event(projection, tier_change)
    assert result.disposition == "INVALID_STATE_IGNORED"
    assert result.projection.tier_id == "research"


def test_privileged_override_is_auditable_and_does_not_grant_by_itself():
    audit = PrivilegedEntitlementOverrideAudit(
        audit_id="audit-1",
        customer_id="cust-1",
        actor_id="admin-7",
        entitlement="QUANT_DASHBOARD",
        action=OverrideAction.GRANT,
        occurred_at="2026-08-17T10:00:00-07:00",
        reason="support correction",
        expires_at="2026-08-18T10:00:00-07:00",
    )

    assert audit.action is OverrideAction.GRANT
    catalog = EntitlementCatalog(by_tier={"research": frozenset({"MORNING_NOTE"})})
    decision = check_entitlement(_active_projection(), catalog, "QUANT_DASHBOARD")
    assert decision.allowed is False


def test_privileged_override_rejects_non_future_expiry():
    with pytest.raises(ValueError, match="override expiry"):
        PrivilegedEntitlementOverrideAudit(
            audit_id="audit-1",
            customer_id="cust-1",
            actor_id="admin-7",
            entitlement="QUANT_DASHBOARD",
            action=OverrideAction.GRANT,
            occurred_at="2026-08-17T10:00:00-07:00",
            reason="support correction",
            expires_at="2026-08-17T09:59:00-07:00",
        )


def test_commercial_beta_gate_requires_all_controls_and_live_execution_off():
    ready = _ready()
    assert ready.ready is True
    assert ready.missing_gates == ()

    missing_method = _ready(performance_methodology_contract=False)
    assert missing_method.ready is False
    assert "PERFORMANCE_METHODOLOGY_CONTRACT" in missing_method.missing_gates

    unsafe = _ready(live_brokerage_execution_enabled=True)
    assert unsafe.ready is False
    assert "LIVE_EXECUTION_MUST_REMAIN_DISABLED_FOR_RESEARCH_BETA" in unsafe.missing_gates
