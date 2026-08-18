from datetime import datetime, timedelta, timezone

from daily_alpha.auth_contract import AuthSession, PrincipalRole, authorize_session


NOW = datetime(2026, 8, 18, 5, 0, tzinfo=timezone.utc)


def session(**overrides):
    values = {
        "session_id": "sess-1",
        "subject_id": "subject-1",
        "provider_id": "provider-neutral",
        "role": PrincipalRole.CUSTOMER,
        "issued_at": NOW - timedelta(minutes=30),
        "expires_at": NOW + timedelta(hours=1),
        "customer_id": "cust-a",
        "mfa_verified_at": None,
        "revoked_at": None,
    }
    values.update(overrides)
    return AuthSession(**values)


def test_customer_session_allows_only_its_own_tenant():
    own = authorize_session(session(), now=NOW, requested_customer_id="cust-a")
    other = authorize_session(session(), now=NOW, requested_customer_id="cust-b")

    assert own.allowed is True
    assert own.entitlement_check_required is True
    assert own.reason == "AUTHENTICATED_CUSTOMER"
    assert other.allowed is False
    assert other.reason == "TENANT_MISMATCH"


def test_customer_session_cannot_request_privileged_action():
    decision = authorize_session(
        session(),
        now=NOW,
        requested_customer_id="cust-a",
        privileged_action=True,
    )

    assert decision.allowed is False
    assert decision.reason == "CUSTOMER_PRIVILEGED_ACTION_DENIED"


def test_expired_and_revoked_sessions_fail_closed():
    expired = authorize_session(
        session(expires_at=NOW), now=NOW, requested_customer_id="cust-a"
    )
    revoked = authorize_session(
        session(revoked_at=NOW - timedelta(minutes=1)),
        now=NOW,
        requested_customer_id="cust-a",
    )

    assert expired.allowed is False
    assert expired.reason == "SESSION_EXPIRED"
    assert revoked.allowed is False
    assert revoked.reason == "SESSION_REVOKED"


def test_privileged_tenant_access_requires_explicit_action_and_recent_mfa():
    admin = session(
        role=PrincipalRole.ADMIN,
        customer_id=None,
        mfa_verified_at=NOW - timedelta(minutes=5),
    )

    implicit = authorize_session(admin, now=NOW, requested_customer_id="cust-b")
    explicit = authorize_session(
        admin,
        now=NOW,
        requested_customer_id="cust-b",
        privileged_action=True,
    )

    assert implicit.allowed is False
    assert implicit.reason == "PRIVILEGED_ACTION_REQUIRED"
    assert explicit.allowed is True
    assert explicit.reason == "AUTHENTICATED_PRIVILEGED"
    assert explicit.entitlement_check_required is True


def test_privileged_tenant_access_rejects_missing_or_stale_mfa():
    missing = authorize_session(
        session(role=PrincipalRole.SUPPORT, customer_id=None),
        now=NOW,
        requested_customer_id="cust-a",
        privileged_action=True,
    )
    stale = authorize_session(
        session(
            role=PrincipalRole.ADMIN,
            customer_id=None,
            mfa_verified_at=NOW - timedelta(minutes=16),
        ),
        now=NOW,
        requested_customer_id="cust-a",
        privileged_action=True,
    )

    assert missing.allowed is False
    assert missing.reason == "MFA_REQUIRED"
    assert stale.allowed is False
    assert stale.reason == "MFA_TOO_OLD"


def test_unknown_role_and_naive_timestamp_fail_closed():
    unknown = session(role="ADMIN")  # type: ignore[arg-type]
    naive = session(issued_at=datetime(2026, 8, 18, 4, 30))

    unknown_decision = authorize_session(
        unknown,
        now=NOW,
        requested_customer_id="cust-a",
        privileged_action=True,
    )
    naive_decision = authorize_session(
        naive,
        now=NOW,
        requested_customer_id="cust-a",
    )

    assert unknown_decision.allowed is False
    assert unknown_decision.reason == "UNKNOWN_PRINCIPAL_ROLE"
    assert naive_decision.allowed is False
    assert naive_decision.reason == "INVALID_TIMESTAMP"


def test_auth_success_never_implies_product_entitlement():
    decision = authorize_session(session(), now=NOW, requested_customer_id="cust-a")

    assert decision.allowed is True
    assert decision.entitlement_check_required is True
