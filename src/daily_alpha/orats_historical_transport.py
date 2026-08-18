"""Bounded, fail-closed HTTP transport for historical ORATS research calls.

This module is research infrastructure only. It deliberately distinguishes rate
limits, authentication failures, transient request exhaustion, and malformed data
so callers do not silently reinterpret transport failures as missing options.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HistoricalOratsError(RuntimeError):
    """Base class for historical ORATS research failures."""


class HistoricalOratsRequestError(HistoricalOratsError):
    """Raised when a historical ORATS request cannot return a usable response."""


class HistoricalOratsRateLimitedError(HistoricalOratsRequestError):
    """Raised when the bounded retry budget is exhausted by HTTP 429."""


class HistoricalOratsAuthError(HistoricalOratsRequestError):
    """Raised on authentication/authorization failure; never retry or mask it."""


class HistoricalOratsDataError(HistoricalOratsError):
    """Raised when ORATS returns malformed/unusable response data."""


class HistoricalOratsHttpError(HistoricalOratsRequestError):
    """Raised for non-retryable HTTP errors that are not auth failures."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


Sleep = Callable[[float], None]
Open = Callable[..., Any]
TRANSIENT_HTTP_CODES = frozenset({500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 8.0


def _retry_delay(
    attempt: int,
    *,
    retry_base_seconds: float,
    headers: Mapping[str, str] | None = None,
) -> float:
    calculated = min(retry_base_seconds * (2**attempt), MAX_BACKOFF_SECONDS)
    if headers is None:
        return calculated
    raw = headers.get("Retry-After")
    if raw is None:
        return calculated
    try:
        retry_after = max(0.0, float(raw))
    except (TypeError, ValueError):
        return calculated
    return min(max(calculated, retry_after), MAX_BACKOFF_SECONDS)


def request_json(
    url: str,
    *,
    token: str,
    header_auth: bool,
    timeout_seconds: float = 45.0,
    max_retries: int = 3,
    retry_base_seconds: float = 0.5,
    sleep: Sleep | None = None,
    opener: Open | None = None,
) -> Any:
    """Return JSON with bounded retries and explicit historical failure classes.

    Retried conditions: HTTP 429, HTTP 500/502/503/504, and network failures.
    Fail-immediate conditions: HTTP 401/403 and malformed JSON.
    """

    if not token:
        raise HistoricalOratsAuthError("ORATS token is required")
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    if retry_base_seconds < 0:
        raise ValueError("retry_base_seconds must be non-negative")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    do_sleep = sleep or time.sleep
    do_open = opener or urlopen
    headers = {"Accept": "application/json"}
    if header_auth:
        headers["Authorization"] = token

    attempts = max_retries + 1
    for attempt in range(attempts):
        request = Request(url, headers=headers)
        try:
            with do_open(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                if attempt < max_retries:
                    do_sleep(
                        _retry_delay(
                            attempt,
                            retry_base_seconds=retry_base_seconds,
                            headers=exc.headers,
                        )
                    )
                    continue
                raise HistoricalOratsRateLimitedError(
                    f"ORATS historical request rate limited after {attempts} attempts"
                ) from exc
            if exc.code in TRANSIENT_HTTP_CODES:
                if attempt < max_retries:
                    do_sleep(
                        _retry_delay(
                            attempt,
                            retry_base_seconds=retry_base_seconds,
                        )
                    )
                    continue
                raise HistoricalOratsRequestError(
                    f"ORATS historical transient HTTP {exc.code} after {attempts} attempts"
                ) from exc
            if exc.code in {401, 403}:
                raise HistoricalOratsAuthError(
                    f"ORATS historical authentication/authorization failed (HTTP {exc.code})"
                ) from exc
            raise HistoricalOratsHttpError(
                exc.code,
                f"ORATS historical HTTP error {exc.code}",
            ) from exc
        except URLError as exc:
            if attempt < max_retries:
                do_sleep(
                    _retry_delay(
                        attempt,
                        retry_base_seconds=retry_base_seconds,
                    )
                )
                continue
            raise HistoricalOratsRequestError(
                f"ORATS historical network error after {attempts} attempts"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HistoricalOratsDataError("ORATS historical response returned invalid JSON") from exc

    raise HistoricalOratsRequestError("ORATS historical request failed unexpectedly")
