from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from daily_alpha.stockdata_smart_money import StockDataSmartMoneyClient


def test_congressional_purchases_are_normalized():
    def transport(url, headers):
        assert headers["X-API-Key"] == "secret"
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"].startswith("DailyAlphaResearch/")
        assert headers["Connection"] == "close"
        assert "/congress-trades?" in url
        return {
            "trades": [
                {
                    "ticker": "NVDA",
                    "transaction_type": "purchase",
                    "transaction_date": "2026-07-01",
                    "disclosure_date": "2026-07-20",
                    "amount_min": 15001,
                    "amount_max": 50000,
                    "politician": {"name": "Jane Doe", "chamber": "House"},
                },
                {
                    "ticker": "MSFT",
                    "transaction_type": "sale",
                    "transaction_date": "2026-07-01",
                    "disclosure_date": "2026-07-20",
                    "amount_min": 1001,
                    "amount_max": 15000,
                    "politician": {"name": "Jane Doe", "chamber": "House"},
                },
            ]
        }

    client = StockDataSmartMoneyClient(
        api_key="secret", transport=transport, min_request_interval_seconds=0
    )
    rows = client.fetch_congressional_purchases(days=90)
    assert len(rows) == 1
    assert rows[0].symbol == "NVDA"
    assert rows[0].politician == "Jane Doe"
    assert rows[0].disclosure_lag_days == 19


def test_institutional_pair_uses_latest_reportable_quarters():
    calls = []

    def transport(url, headers):
        calls.append(url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/institutions"):
            assert params["period"] == ["2026-Q2"]
            return {
                "institutions": [
                    {
                        "institution": "Big Fund",
                        "institution_cik": "0001",
                    }
                ]
            }
        if parsed.path.endswith("/institutions/portfolio/0001"):
            period = params["period"][0]
            if period == "2026-Q2":
                return {
                    "holdings": [
                        {
                            "institution": "Big Fund",
                            "ticker": "AAPL",
                            "report_date": "2026-06-30",
                            "shares": 150,
                            "value": 30000,
                        }
                    ]
                }
            assert period == "2026-Q1"
            return {
                "holdings": [
                    {
                        "institution": "Big Fund",
                        "ticker": "AAPL",
                        "report_date": "2026-03-31",
                        "shares": 100,
                        "value": 18000,
                    }
                ]
            }
        raise AssertionError(url)

    client = StockDataSmartMoneyClient(
        api_key="secret", transport=transport, min_request_interval_seconds=0
    )
    current, previous, coverage = client.fetch_institutional_holdings_pair(
        as_of=date(2026, 8, 16), institution_limit=1
    )
    assert coverage.current_period == "2026-Q2"
    assert coverage.previous_period == "2026-Q1"
    assert current[0].symbol == "AAPL"
    assert current[0].shares == 150
    assert previous[0].shares == 100
    assert len(calls) == 3


def test_missing_api_key_fails_closed(monkeypatch):
    monkeypatch.delenv("STOCKDATA_API_KEY", raising=False)
    with pytest.raises(Exception, match="STOCKDATA_API_KEY_MISSING"):
        StockDataSmartMoneyClient()


def test_congressional_rows_without_disclosure_date_are_not_invented():
    client = StockDataSmartMoneyClient(
        api_key="secret",
        min_request_interval_seconds=0,
        transport=lambda url, headers: {
            "trades": [
                {
                    "ticker": "NVDA",
                    "transaction_type": "purchase",
                    "transaction_date": "2026-07-01",
                    "amount_min": 1001,
                    "amount_max": 15000,
                    "politician": {"name": "Jane Doe", "chamber": "House"},
                }
            ]
        },
    )
    assert client.fetch_congressional_purchases() == ()
