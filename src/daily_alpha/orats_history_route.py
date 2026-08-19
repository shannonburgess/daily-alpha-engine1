"""Strict compatibility-route policy for historical ORATS research calls.

A caller chooses the documented route that matches the account's entitlement as
its primary route. A second documented route may be attempted only when the first
route explicitly reports endpoint incompatibility. Rate limits, authentication
failures, transient/network exhaustion, and malformed data remain fail-closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from daily_alpha.orats_historical_transport import (
    HistoricalOratsHttpError,
    request_json,
)

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
    primary_source: str = "ORATS_DATA_API",
    fallback_source: str = "ORATS_DATAV2_API",
    requester: HistoricalRequest = request_json,
) -> HistoricalRouteResult:
    """Request historical ORATS data with a fail-closed compatibility fallback."""

    try:
        payload = requester(
            primary_url,
            token=token,
            header_auth=primary_header_auth,
        )
        return HistoricalRouteResult(
            payload=payload,
            source=primary_source,
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
        source=fallback_source,
        used_compatibility_fallback=True,
    )
