"""Strict historical ORATS daily/earnings fetch adapter for research backtests.

This module prepares the final `fetch_orats_history()` wiring without changing any
strategy rule. It delegates all network behavior to the bounded historical transport
and the narrow compatibility-route policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode

from .orats_history_route import HistoricalRouteResult, request_with_compatibility_fallback

HistoricalRouter = Callable[..., HistoricalRouteResult]


@dataclass(frozen=True)
class HistoricalDailyEarningsPayloads:
    daily_payload: Any
    earnings_payload: Any
    daily_source: str
    earnings_source: str
    daily_used_compatibility_fallback: bool
    earnings_used_compatibility_fallback: bool


@dataclass(frozen=True)
class HistoricalDailyEarningsRows:
    """Normalized rows with endpoint-specific provenance preserved per row."""

    daily_rows: tuple[dict[str, Any], ...]
    earnings_rows: tuple[dict[str, Any], ...]
    daily_source: str
    earnings_source: str
    daily_used_compatibility_fallback: bool
    earnings_used_compatibility_fallback: bool


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize supported ORATS list/data-list payload shapes without hiding errors."""

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [row for row in payload["data"] if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise RuntimeError("Unexpected ORATS response shape")


def fetch_daily_earnings_payloads(
    ticker: str,
    *,
    warm_start: date,
    end: date,
    token: str,
    router: HistoricalRouter = request_with_compatibility_fallback,
) -> HistoricalDailyEarningsPayloads:
    """Fetch daily bars and earnings through the strict historical route policy."""

    if not ticker.strip():
        raise ValueError("ticker is required")
    if warm_start > end:
        raise ValueError("warm_start must not be after end")
    if not token:
        raise ValueError("token is required")

    primary_base = "https://api.orats.io/data"
    fallback_base = "https://api.orats.io/datav2"

    daily_primary_query = urlencode(
        {
            "tickers": ticker,
            "tradeDate": f"{warm_start.isoformat()},{end.isoformat()}",
            "fields[dailies]": "ticker,tradeDate,clsPx,hiPx,loPx,open,stockVolume",
        }
    )
    earnings_primary_query = urlencode(
        {
            "tickers": ticker,
            "fields[earnings]": "ticker,earnDate,anncTod",
        }
    )
    daily_fallback_query = urlencode(
        {
            "token": token,
            "ticker": ticker,
            "fields": "ticker,tradeDate,clsPx,hiPx,loPx,open,stockVolume",
        }
    )
    earnings_fallback_query = urlencode({"token": token, "ticker": ticker})

    daily = router(
        f"{primary_base}/hist/dailies?{daily_primary_query}",
        f"{fallback_base}/hist/dailies?{daily_fallback_query}",
        token=token,
        primary_header_auth=True,
        fallback_header_auth=False,
    )
    earnings = router(
        f"{primary_base}/hist/earnings?{earnings_primary_query}",
        f"{fallback_base}/hist/earnings?{earnings_fallback_query}",
        token=token,
        primary_header_auth=True,
        fallback_header_auth=False,
    )

    return HistoricalDailyEarningsPayloads(
        daily_payload=daily.payload,
        earnings_payload=earnings.payload,
        daily_source=daily.source,
        earnings_source=earnings.source,
        daily_used_compatibility_fallback=daily.used_compatibility_fallback,
        earnings_used_compatibility_fallback=earnings.used_compatibility_fallback,
    )


def fetch_daily_earnings_rows(
    ticker: str,
    *,
    warm_start: date,
    end: date,
    token: str,
    router: HistoricalRouter = request_with_compatibility_fallback,
) -> HistoricalDailyEarningsRows:
    """Fetch and normalize rows while retaining separate daily/earnings provenance."""

    payloads = fetch_daily_earnings_payloads(
        ticker,
        warm_start=warm_start,
        end=end,
        token=token,
        router=router,
    )
    daily_rows = tuple(
        {**row, "source": payloads.daily_source}
        for row in _payload_rows(payloads.daily_payload)
    )
    earnings_rows = tuple(
        {**row, "source": payloads.earnings_source}
        for row in _payload_rows(payloads.earnings_payload)
    )
    return HistoricalDailyEarningsRows(
        daily_rows=daily_rows,
        earnings_rows=earnings_rows,
        daily_source=payloads.daily_source,
        earnings_source=payloads.earnings_source,
        daily_used_compatibility_fallback=payloads.daily_used_compatibility_fallback,
        earnings_used_compatibility_fallback=payloads.earnings_used_compatibility_fallback,
    )
