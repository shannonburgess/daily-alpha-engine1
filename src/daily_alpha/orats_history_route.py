"""Strict compatibility-route policy for historical ORATS research calls.

The primary historical Data API is authoritative. The legacy datav2 route may be
used only when the primary route explicitly reports endpoint incompatibility.
Rate limits, authentication failures, transient/network exhaustion, and malformed
data must remain fail-closed and must never trigger a second request path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from daily_alpha.orats_historical_transport import (
    HistoricalOratsHttpError,
    request_json,
)

# Compatibility fallback is deliberately narrow. A malformed query (400/422),
# auth failure (401/403), rate limit (429), transient 5xx, or network/data error
# must not be reinterpreted as an account-routing problem.
COMPATIBILITY_HTTP_CODES = frozenset({404, 405, 410})

HistoricalRequest = Callable[..., Any]


@dataclass(frozen=True)
class HistoricalRouteResult:
    payload: Any
    source: str
    used_compatibility_fallback: bool


def request_with_compatibility_fallback(
    primary_url: str,
    fallback_url: str,
    *,
    token: str,
    primary_header_auth: bool = True,
    fallback_header_auth: bool = False,
    requester: HistoricalRequest = request_json,
) -> HistoricalRouteResult:
    """Request historical ORATS data with a fail-closed compatibility fallback.

    Only explicit endpoint/provisioning incompatibility represented by a narrow
    HTTP status allow-list may invoke the fallback route. All other historical
    transport exceptions propagate unchanged.
    """

    try:
        payload = requester(
            primary_url,
            token=token,
            header_auth=primary_header_auth,
        )
        return HistoricalRouteResult(
            payload=payload,
            source="ORATS_DATA_API",
            used_compatibility_fallback=False,
        )
    except HistoricalOratsHttpError as exc:
        if exc.status_code not in COMPATIBILITY_HTTP_CODES:
            raise

    payload = requester(
        fallback_url,
        token=token,
        header_auth=fallback_header_auth,
    )
    return HistoricalRouteResult(
        payload=payload,
        source="ORATS_DATAV2_API",
        used_compatibility_fallback=True,
    )
