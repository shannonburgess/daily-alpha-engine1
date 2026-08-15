from datetime import UTC, datetime

import pytest

from daily_alpha.orats import (
    OratsClient,
    OratsConfigurationError,
    OratsDataError,
)


def payload(updated_at="2026-08-15T16:00:00Z"):
    return {
        "data": [
            {
                "ticker": "AAPL",
                "expirDate": "2026-10-16",
                "dte": 62,
                "strike": 250,
                "callBidPrice": 5.0,
                "callAskPrice": 5.4,
                "callOpenInterest": 900,
                "callVolume": 120,
                "putBidPrice": 4.8,
                "putAskPrice": 5.2,
                "putOpenInterest": 800,
                "putVolume": 100,
                "updatedAt": updated_at,
            }
        ]
    }


def test_token_is_required(monkeypatch):
    monkeypatch.delenv("ORATS_TOKEN", raising=False)
    with pytest.raises(OratsConfigurationError):
        OratsClient()


def test_delayed_chain_is_normalized():
    seen_urls = []

    def transport(url, timeout):
        seen_urls.append(url)
        assert timeout == 20.0
        return payload()

    client = OratsClient(token="secret", transport=transport)
    chain = client.fetch_chain(
        "aapl",
        as_of=datetime(2026, 8, 15, 16, 20, tzinfo=UTC),
    )

    assert chain.ticker == "AAPL"
    assert len(chain.candidates) == 2
    assert {item.option_type for item in chain.candidates} == {"CALL", "PUT"}
    assert "secret" in seen_urls[0]
    assert "AAPL" in seen_urls[0]


def test_stale_chain_raises_data_error():
    client = OratsClient(token="secret", transport=lambda url, timeout: payload())

    with pytest.raises(OratsDataError, match="stale"):
        client.fetch_chain(
            "AAPL",
            as_of=datetime(2026, 8, 15, 17, 0, tzinfo=UTC),
        )


def test_live_mode_uses_live_endpoint():
    seen_urls = []

    def transport(url, timeout):
        seen_urls.append(url)
        return payload("2026-08-15T16:29:00Z")

    client = OratsClient(token="secret", mode="live", transport=transport)
    client.fetch_chain(
        "AAPL",
        as_of=datetime(2026, 8, 15, 16, 30, tzinfo=UTC),
    )

    assert "/live/one-minute/" in seen_urls[0]
