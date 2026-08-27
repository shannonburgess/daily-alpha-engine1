from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError

import pytest

import daily_alpha.orats as orats_module
from daily_alpha.orats import (
    OratsClient,
    OratsConfigurationError,
    OratsDataError,
    OratsNoOptionsError,
    OratsRateLimitedError,
    OratsRequestError,
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


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def _http_error(code, *, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return HTTPError(
        url="https://api.orats.io/datav2/strikes",
        code=code,
        msg="test",
        hdrs=headers,
        fp=BytesIO(b""),
    )


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


def test_rate_limit_retries_then_recovers(monkeypatch):
    calls = [
        _http_error(429, retry_after=1.0),
        FakeResponse(orats_module.json.dumps(payload()).encode("utf-8")),
    ]
    sleeps = []

    def fake_urlopen(request, timeout):
        result = calls.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(orats_module, "urlopen", fake_urlopen)
    client = OratsClient(
        token="secret",
        max_retries=2,
        retry_base_seconds=0.1,
        sleep=sleeps.append,
    )

    chain = client.fetch_chain(
        "AAPL",
        as_of=datetime(2026, 8, 15, 17, 30, tzinfo=UTC),
    )

    assert chain.ticker == "AAPL"
    assert sleeps == [1.0]
    assert calls == []


def test_rate_limit_is_distinct_after_bounded_retries(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        raise _http_error(429)

    monkeypatch.setattr(orats_module, "urlopen", fake_urlopen)
    client = OratsClient(
        token="secret",
        max_retries=2,
        retry_base_seconds=0.1,
        sleep=sleeps.append,
    )

    with pytest.raises(OratsRateLimitedError, match="3 attempts"):
        client.fetch_chain("AAPL")

    assert attempts == 3
    assert sleeps == pytest.approx([0.1, 0.2])


def test_transient_server_error_retries_then_recovers(monkeypatch):
    calls = [
        _http_error(503),
        FakeResponse(orats_module.json.dumps(payload()).encode("utf-8")),
    ]
    sleeps = []

    def fake_urlopen(request, timeout):
        result = calls.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(orats_module, "urlopen", fake_urlopen)
    client = OratsClient(
        token="secret",
        max_retries=1,
        retry_base_seconds=0.25,
        sleep=sleeps.append,
    )

    client.fetch_chain(
        "AAPL",
        as_of=datetime(2026, 8, 15, 17, 30, tzinfo=UTC),
    )

    assert sleeps == [0.25]
    assert calls == []


def test_authentication_error_fails_closed_without_retry(monkeypatch):
    attempts = 0
    sleeps = []

    def fake_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        raise _http_error(401)

    monkeypatch.setattr(orats_module, "urlopen", fake_urlopen)
    client = OratsClient(token="secret", max_retries=3, sleep=sleeps.append)

    with pytest.raises(OratsRequestError, match="authentication/authorization"):
        client.fetch_chain("AAPL")

    assert attempts == 1
    assert sleeps == []
