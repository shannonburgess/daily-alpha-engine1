from datetime import UTC, datetime

import pytest

from daily_alpha.orats import (
    OratsClient,
    OratsConfigurationError,
    OratsDataError,
    OratsNoOptionsError,
)


def payload(updated_at="2026-08-15T16:00:00Z"):
    return {
        "data": [
            {
                "ticker": "AAPL",
                "expirDate": "2026-10-16",
                "dte": 62,
                "strike": 250,
                "stockPrice": 220.25,
                "callBidPrice": 5.0,
                "callAskPrice": 5.4,
                "callOpenInterest": 900,
                "callVolume": 120,
                "putBidPrice": 4.8,
                "putAskPrice": 5.2,
                "putOpenInterest": 800,
                "putVolume": 100,
                "delta": 0.55,
                "updatedAt": updated_at,
            }
        ]
    }


def test_token_is_required(monkeypatch):
    monkeypatch.delenv("ORATS_TOKEN", raising=False)
    with pytest.raises(OratsConfigurationError):
        OratsClient()


def test_delayed_chain_uses_standard_strikes_and_is_normalized():
    seen_urls = []

    def transport(url, timeout):
        seen_urls.append(url)
        assert timeout == 20.0
        return payload()

    client = OratsClient(token="secret", transport=transport)
    chain = client.fetch_chain(
        "aapl",
        as_of=datetime(2026, 8, 15, 17, 30, tzinfo=UTC),
    )

    assert chain.ticker == "AAPL"
    assert chain.stock_price == 220.25
    assert len(chain.candidates) == 2
    assert {item.option_type for item in chain.candidates} == {"CALL", "PUT"}
    deltas = sorted(item.delta for item in chain.candidates if item.delta is not None)
    assert deltas == pytest.approx([-0.45, 0.55])
    assert "/datav2/strikes?" in seen_urls[0]
    assert "one-minute" not in seen_urls[0]
    assert "dte=45%2C75" in seen_urls[0]
    assert "secret" in seen_urls[0]
    assert "AAPL" in seen_urls[0]


def test_empty_45_75_chain_is_explicit_no_options_error():
    client = OratsClient(token="secret", transport=lambda url, timeout: {"data": []})

    with pytest.raises(OratsNoOptionsError, match="45-75 DTE"):
        client.fetch_chain(
            "AAPL",
            as_of=datetime(2026, 8, 15, 17, 30, tzinfo=UTC),
        )


def test_delayed_chain_allows_post_market_research_window():
    client = OratsClient(token="secret", transport=lambda url, timeout: payload())

    chain = client.fetch_chain(
        "AAPL",
        as_of=datetime(2026, 8, 15, 17, 59, tzinfo=UTC),
    )

    assert chain.source_mode == "delayed"


def test_stale_chain_raises_data_error():
    client = OratsClient(token="secret", transport=lambda url, timeout: payload())

    with pytest.raises(OratsDataError, match="stale"):
        client.fetch_chain(
            "AAPL",
            as_of=datetime(2026, 8, 15, 18, 1, tzinfo=UTC),
        )


def test_live_mode_uses_live_strikes_endpoint():
    seen_urls = []

    def transport(url, timeout):
        seen_urls.append(url)
        return payload("2026-08-15T16:29:00Z")

    client = OratsClient(token="secret", mode="live", transport=transport)
    client.fetch_chain(
        "AAPL",
        as_of=datetime(2026, 8, 15, 16, 30, tzinfo=UTC),
    )

    assert "/live/strikes?" in seen_urls[0]
    assert "one-minute" not in seen_urls[0]


def test_scheduled_earnings_within_seven_days_is_event_risk():
    seen_urls = []

    def transport(url, timeout):
        seen_urls.append(url)
        return {
            "data": [
                {
                    "ticker": "SJM",
                    "tradeDate": "2026-08-20",
                    "assetType": 3,
                    "nextErn": "2026-08-26",
                }
            ]
        }

    client = OratsClient(token="secret", transport=transport)
    schedule = client.fetch_earnings_schedule(
        "SJM",
        as_of=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert schedule.next_earnings_date.isoformat() == "2026-08-26"
    assert schedule.days_until_earnings == 6
    assert schedule.event_risk is True
    assert schedule.block_days == 7
    assert "/datav2/cores?" in seen_urls[0]
    assert "nextErn" in seen_urls[0]


def test_scheduled_earnings_beyond_seven_days_is_clear():
    client = OratsClient(
        token="secret",
        transport=lambda url, timeout: {
            "data": [
                {
                    "ticker": "PR",
                    "tradeDate": "2026-08-20",
                    "assetType": 3,
                    "nextErn": "2026-11-04",
                }
            ]
        },
    )

    schedule = client.fetch_earnings_schedule(
        "PR",
        as_of=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert schedule.event_risk is False
    assert schedule.days_until_earnings > 7


def test_missing_company_next_earnings_fails_closed():
    client = OratsClient(
        token="secret",
        transport=lambda url, timeout: {
            "data": [
                {
                    "ticker": "SJM",
                    "tradeDate": "2026-08-20",
                    "assetType": 3,
                    "nextErn": None,
                }
            ]
        },
    )

    with pytest.raises(OratsDataError, match="do not assume EVENT_RISK_CLEAR"):
        client.fetch_earnings_schedule(
            "SJM",
            as_of=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
        )


def test_etf_does_not_require_company_earnings_date():
    client = OratsClient(
        token="secret",
        transport=lambda url, timeout: {
            "data": [
                {
                    "ticker": "XLK",
                    "tradeDate": "2026-08-20",
                    "assetType": 5,
                    "nextErn": None,
                }
            ]
        },
    )

    schedule = client.fetch_earnings_schedule(
        "XLK",
        as_of=datetime(2026, 8, 20, 20, 15, tzinfo=UTC),
    )

    assert schedule.is_non_company_security is True
    assert schedule.next_earnings_date is None
    assert schedule.event_risk is False
