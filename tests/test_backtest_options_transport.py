import pytest

from daily_alpha import backtest_options
from daily_alpha.orats_historical_transport import HistoricalOratsRateLimitedError


def test_fetch_chain_uses_strict_historical_transport(monkeypatch):
    calls = []

    def fake_request(url, *, token, header_auth):
        calls.append((url, token, header_auth))
        return {"data": [{"ticker": "NVDA"}]}

    monkeypatch.setattr(backtest_options, "request_json", fake_request)

    rows = backtest_options.fetch_chain("NVDA", "2026-08-18", "secret")

    assert rows == [{"ticker": "NVDA"}]
    assert len(calls) == 1
    url, token, header_auth = calls[0]
    assert "/datav2/hist/strikes?" in url
    assert token == "secret"
    assert header_auth is False


def test_fetch_contract_uses_strict_historical_transport(monkeypatch):
    calls = []

    def fake_request(url, *, token, header_auth):
        calls.append((url, token, header_auth))
        return {"data": [{"tradeDate": "2026-08-18", "callBidPrice": 2.0}]}

    monkeypatch.setattr(backtest_options, "request_json", fake_request)

    row = backtest_options.fetch_contract(
        "NVDA", "2026-10-16", 200.0, "2026-08-18", "secret"
    )

    assert row is not None
    assert row["callBidPrice"] == 2.0
    assert len(calls) == 1
    assert "/datav2/hist/strikes/options?" in calls[0][0]
    assert calls[0][2] is False


def test_rate_limit_propagates_instead_of_becoming_missing_option(monkeypatch):
    def rate_limited(*args, **kwargs):
        raise HistoricalOratsRateLimitedError("rate limited")

    monkeypatch.setattr(backtest_options, "request_json", rate_limited)

    with pytest.raises(HistoricalOratsRateLimitedError, match="rate limited"):
        backtest_options.fetch_chain("NVDA", "2026-08-18", "secret")

    with pytest.raises(HistoricalOratsRateLimitedError, match="rate limited"):
        backtest_options.fetch_contract(
            "NVDA", "2026-10-16", 200.0, "2026-08-18", "secret"
        )
