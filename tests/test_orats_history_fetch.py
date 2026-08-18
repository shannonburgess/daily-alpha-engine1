from datetime import date

import pytest

from daily_alpha.orats_historical_transport import HistoricalOratsRateLimitedError
from daily_alpha.orats_history_fetch import (
    fetch_daily_earnings_payloads,
    fetch_daily_earnings_rows,
)
from daily_alpha.orats_history_route import HistoricalRouteResult


def test_fetch_adapter_builds_primary_and_compatibility_urls_without_leaking_auth_mode():
    calls = []

    def router(primary_url, fallback_url, **kwargs):
        calls.append((primary_url, fallback_url, kwargs))
        source = "ORATS_DATA_API" if "dailies" in primary_url else "ORATS_DATAV2_API"
        return HistoricalRouteResult(
            payload={"data": []},
            source=source,
            used_compatibility_fallback=source == "ORATS_DATAV2_API",
        )

    result = fetch_daily_earnings_payloads(
        "NVDA",
        warm_start=date(2024, 1, 1),
        end=date(2026, 8, 14),
        token="secret-token",
        router=router,
    )

    assert len(calls) == 2
    daily_primary, daily_fallback, daily_kwargs = calls[0]
    assert "/data/hist/dailies?" in daily_primary
    assert "tickers=NVDA" in daily_primary
    assert "tradeDate=2024-01-01%2C2026-08-14" in daily_primary
    assert "/datav2/hist/dailies?" in daily_fallback
    assert "token=secret-token" in daily_fallback
    assert daily_kwargs["primary_header_auth"] is True
    assert daily_kwargs["fallback_header_auth"] is False

    assert result.daily_source == "ORATS_DATA_API"
    assert result.earnings_source == "ORATS_DATAV2_API"
    assert result.earnings_used_compatibility_fallback is True


def test_rate_limit_propagates_without_becoming_compatibility_or_missing_data():
    def router(*args, **kwargs):
        raise HistoricalOratsRateLimitedError("rate limited")

    with pytest.raises(HistoricalOratsRateLimitedError, match="rate limited"):
        fetch_daily_earnings_payloads(
            "NVDA",
            warm_start=date(2024, 1, 1),
            end=date(2026, 8, 14),
            token="secret-token",
            router=router,
        )


def test_adapter_rejects_invalid_request_identity_before_network_work():
    def router(*args, **kwargs):
        raise AssertionError("router should not be called")

    with pytest.raises(ValueError, match="ticker"):
        fetch_daily_earnings_payloads(
            " ",
            warm_start=date(2024, 1, 1),
            end=date(2026, 8, 14),
            token="secret-token",
            router=router,
        )

    with pytest.raises(ValueError, match="warm_start"):
        fetch_daily_earnings_payloads(
            "NVDA",
            warm_start=date(2026, 8, 15),
            end=date(2026, 8, 14),
            token="secret-token",
            router=router,
        )

    with pytest.raises(ValueError, match="token"):
        fetch_daily_earnings_payloads(
            "NVDA",
            warm_start=date(2024, 1, 1),
            end=date(2026, 8, 14),
            token="",
            router=router,
        )


def test_rows_preserve_daily_and_earnings_provenance_separately():
    calls = 0

    def router(primary_url, fallback_url, **kwargs):
        nonlocal calls
        calls += 1
        if "dailies" in primary_url:
            return HistoricalRouteResult(
                payload={
                    "data": [
                        {
                            "ticker": "NVDA",
                            "tradeDate": "2026-08-14",
                            "source": "SPOOFED_PAYLOAD_SOURCE",
                        }
                    ]
                },
                source="ORATS_DATA_API",
                used_compatibility_fallback=False,
            )
        return HistoricalRouteResult(
            payload=[
                {
                    "ticker": "NVDA",
                    "earnDate": "2026-07-30",
                    "source": "SPOOFED_PAYLOAD_SOURCE",
                }
            ],
            source="ORATS_DATAV2_API",
            used_compatibility_fallback=True,
        )

    result = fetch_daily_earnings_rows(
        "NVDA",
        warm_start=date(2024, 1, 1),
        end=date(2026, 8, 14),
        token="secret-token",
        router=router,
    )

    assert calls == 2
    assert result.daily_rows[0]["source"] == "ORATS_DATA_API"
    assert result.earnings_rows[0]["source"] == "ORATS_DATAV2_API"
    assert result.daily_source == "ORATS_DATA_API"
    assert result.earnings_source == "ORATS_DATAV2_API"
    assert result.daily_used_compatibility_fallback is False
    assert result.earnings_used_compatibility_fallback is True


def test_rows_reject_unexpected_payload_shape():
    def router(primary_url, fallback_url, **kwargs):
        return HistoricalRouteResult(
            payload={"unexpected": []},
            source="ORATS_DATA_API",
            used_compatibility_fallback=False,
        )

    with pytest.raises(RuntimeError, match="Unexpected ORATS response shape"):
        fetch_daily_earnings_rows(
            "NVDA",
            warm_start=date(2024, 1, 1),
            end=date(2026, 8, 14),
            token="secret-token",
            router=router,
        )
