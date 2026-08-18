"""Provider-neutral authentication/session contract for commercial-beta research.

This module deliberately stops at authentication and tenant-access authorization.
It does not grant product entitlements, process payments, select an identity vendor,
or enable any trading/execution path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum


class PrincipalRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    SUPPORT = "SUPPORT"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class AuthSession:
    """Normalized identity-provider session claims used by Daily Alpha.

    ``customer_id`` is required for CUSTOMER sessions and identifies the one tenant
    the session may access. SUPPORT/ADMIN sessions may inspect a customer tenant
    only through an explicitly privileged action with recent MFA.
    """

    session_id: str
    subject_id: str
    provider_id: str
    role: PrincipalRole
    issued_at: datetime
    expires_at: datetime
    customer_id: str | None = None
    mfa_verified_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    reason: str
    entitlement_check_required: bool = True


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("authentication timestamps must be timezone-aware")
    return value.astimezone(UTC)


def authorize_session(
    session: AuthSession,
    *,
    now: datetime,
    requested_customer_id: str,
    privileged_action: bool = False,
    privileged_mfa_max_age: timedelta = timedelta(minutes=15),
    max_clock_skew: timedelta = timedelta(minutes=2),
) -> AuthDecision:
    """Fail-closed authentication/tenant authorization decision.

    A successful result means only that the identity/session is permitted to reach
    the requested tenant boundary. Product access still requires a separate,
    server-side entitlement decision.
    """

    if not session.session_id.strip() or not session.subject_id.strip():
        return AuthDecision(False, "MISSING_SESSION_IDENTITY")
    if not session.provider_id.strip():
        return AuthDecision(False, "MISSING_AUTH_PROVIDER")
    if not requested_customer_id.strip():
        return AuthDecision(False, "MISSING_REQUESTED_CUSTOMER")
    if not isinstance(session.role, PrincipalRole):
        return AuthDecision(False, "UNKNOWN_PRINCIPAL_ROLE")
    if privileged_mfa_max_age <= timedelta(0) or max_clock_skew < timedelta(0):
        return AuthDecision(False, "INVALID_AUTH_POLICY")

    try:
        current = _utc(now)
        issued = _utc(session.issued_at)
        expires = _utc(session.expires_at)
        revoked = _utc(session.revoked_at) if session.revoked_at is not None else None
        mfa = (
            _utc(session.mfa_verified_at)
            if session.mfa_verified_at is not None
            else None
        )
    except ValueError:
        return AuthDecision(False, "INVALID_TIMESTAMP")

    if expires <= issued:
        return AuthDecision(False, "INVALID_SESSION_WINDOW")
    if issued > current + max_clock_skew:
        return AuthDecision(False, "SESSION_ISSUED_IN_FUTURE")
    if current >= expires:
        return AuthDecision(False, "SESSION_EXPIRED")
    if revoked is not None and revoked <= current:
        return AuthDecision(False, "SESSION_REVOKED")

    if session.role is PrincipalRole.CUSTOMER:
        if privileged_action:
            return AuthDecision(False, "CUSTOMER_PRIVILEGED_ACTION_DENIED")
        if not session.customer_id or session.customer_id != requested_customer_id:
            return AuthDecision(False, "TENANT_MISMATCH")
        return AuthDecision(True, "AUTHENTICATED_CUSTOMER")

    # Any SUPPORT/ADMIN customer-tenant access is privileged. This prevents a
    # support/admin identity from silently becoming a broad cross-tenant reader.
    if not privileged_action:
        return AuthDecision(False, "PRIVILEGED_ACTION_REQUIRED")
    if mfa is None:
        return AuthDecision(False, "MFA_REQUIRED")
    if mfa < issued:
        return AuthDecision(False, "MFA_PREDATES_SESSION")
    if mfa > current + max_clock_skew:
        return AuthDecision(False, "MFA_TIMESTAMP_IN_FUTURE")
    if current - mfa > privileged_mfa_max_age:
        return AuthDecision(False, "MFA_TOO_OLD")

    return AuthDecision(True, "AUTHENTICATED_PRIVILEGED")
