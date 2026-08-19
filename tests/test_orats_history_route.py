from __future__ import annotations

import pytest

from daily_alpha.orats_historical_transport import (
    HistoricalOratsAuthError,
    HistoricalOratsDataError,
    HistoricalOratsHttpError,
    HistoricalOratsRateLimitedError,
    HistoricalOratsRequestError,
)
from daily_alpha.orats_history_route import request_with_compatibility_fallback


@pytest.mark.parametrize("status", [404, 405, 410])
def test_explicit_endpoint_incompatibility_uses_fallback_once(status: int) -> None:
    calls: list[str] = []

    def requester(url: str, **_: object) -> object:
        calls.append(url)
        if url == "primary":
            raise HistoricalOratsHttpError(status, "endpoint unavailable")
        return {"data": [{"ticker": "MU"}]}

    result = request_with_compatibility_fallback(
        "primary", "fallback", token="token", requester=requester
    )

    assert calls == ["primary", "fallback"]
    assert result.source == "ORATS_DATAV2_API"
    assert result.used_compatibility_fallback is True


def test_successful_primary_never_calls_fallback() -> None:
    calls: list[str] = []

    def requester(url: str, **_: object) -> object:
        calls.append(url)
        return {"data": [{"ticker": "MU"}]}

    result = request_with_compatibility_fallback(
        "primary", "fallback", token="token", requester=requester
    )

    assert calls == ["primary"]
    assert result.source == "ORATS_DATA_API"
    assert result.used_compatibility_fallback is False


@pytest.mark.parametrize(
    "error",
    [
        HistoricalOratsRateLimitedError("rate limited"),
        HistoricalOratsAuthError("auth"),
        HistoricalOratsRequestError("network exhausted"),
        HistoricalOratsDataError("invalid json"),
        HistoricalOratsHttpError(400, "bad request"),
        HistoricalOratsHttpError(422, "invalid query"),
        HistoricalOratsHttpError(500, "server error"),
    ],
)
def test_non_compatibility_failures_never_call_fallback(error: Exception) -> None:
    calls: list[str] = []

    def requester(url: str, **_: object) -> object:
        calls.append(url)
        raise error

    with pytest.raises(type(error)):
        request_with_compatibility_fallback(
            "primary", "fallback", token="token", requester=requester
        )

    assert calls == ["primary"]


def test_fallback_failure_propagates_without_third_route() -> None:
    calls: list[str] = []

    def requester(url: str, **_: object) -> object:
        calls.append(url)
        if url == "primary":
            raise HistoricalOratsHttpError(404, "endpoint unavailable")
        raise HistoricalOratsRateLimitedError("fallback rate limited")

    with pytest.raises(HistoricalOratsRateLimitedError):
        request_with_compatibility_fallback(
            "primary", "fallback", token="token", requester=requester
        )

    assert calls == ["primary", "fallback"]
