from urllib.error import HTTPError, URLError

import pytest

from daily_alpha.orats_historical_transport import (
    HistoricalOratsAuthError,
    HistoricalOratsDataError,
    HistoricalOratsRateLimitedError,
    HistoricalOratsRequestError,
    request_json,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def sequence_opener(effects, calls):
    queue = list(effects)

    def opener(request, timeout):
        calls.append((request, timeout))
        effect = queue.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    return opener


def http_error(code, headers=None):
    return HTTPError(
        "https://api.orats.io/example",
        code,
        "error",
        headers or {},
        None,
    )


def test_rate_limit_then_success_retries_with_retry_after():
    calls = []
    sleeps = []
    opener = sequence_opener(
        [http_error(429, {"Retry-After": "2"}), FakeResponse(b'{"data": []}')],
        calls,
    )

    payload = request_json(
        "https://api.orats.io/example?token=secret",
        token="secret",
        header_auth=False,
        max_retries=2,
        sleep=sleeps.append,
        opener=opener,
    )

    assert payload == {"data": []}
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_rate_limit_exhaustion_has_explicit_classification():
    calls = []
    sleeps = []
    opener = sequence_opener([http_error(429), http_error(429)], calls)

    with pytest.raises(HistoricalOratsRateLimitedError, match="rate limited"):
        request_json(
            "https://api.orats.io/example?token=secret",
            token="secret",
            header_auth=False,
            max_retries=1,
            retry_base_seconds=0.25,
            sleep=sleeps.append,
            opener=opener,
        )

    assert len(calls) == 2
    assert sleeps == [0.25]


def test_transient_503_then_success_retries():
    calls = []
    sleeps = []
    opener = sequence_opener(
        [http_error(503), FakeResponse(b'{"data": [{"ticker": "NVDA"}]}')],
        calls,
    )

    payload = request_json(
        "https://api.orats.io/example",
        token="secret",
        header_auth=True,
        max_retries=1,
        sleep=sleeps.append,
        opener=opener,
    )

    assert payload["data"][0]["ticker"] == "NVDA"
    assert len(calls) == 2
    assert sleeps == [0.5]
    assert calls[0][0].get_header("Authorization") == "secret"


def test_401_fails_immediately_without_retry():
    calls = []
    sleeps = []
    opener = sequence_opener([http_error(401)], calls)

    with pytest.raises(HistoricalOratsAuthError, match="authentication"):
        request_json(
            "https://api.orats.io/example",
            token="secret",
            header_auth=True,
            max_retries=3,
            sleep=sleeps.append,
            opener=opener,
        )

    assert len(calls) == 1
    assert sleeps == []


def test_invalid_json_fails_immediately_without_retry():
    calls = []
    sleeps = []
    opener = sequence_opener([FakeResponse(b"not-json")], calls)

    with pytest.raises(HistoricalOratsDataError, match="invalid JSON"):
        request_json(
            "https://api.orats.io/example",
            token="secret",
            header_auth=False,
            max_retries=3,
            sleep=sleeps.append,
            opener=opener,
        )

    assert len(calls) == 1
    assert sleeps == []


def test_network_exhaustion_is_request_error_not_missing_data():
    calls = []
    sleeps = []
    opener = sequence_opener(
        [URLError("temporary"), URLError("temporary")],
        calls,
    )

    with pytest.raises(HistoricalOratsRequestError, match="network error"):
        request_json(
            "https://api.orats.io/example",
            token="secret",
            header_auth=False,
            max_retries=1,
            sleep=sleeps.append,
            opener=opener,
        )

    assert len(calls) == 2
    assert sleeps == [0.5]


def test_missing_token_fails_before_network_call():
    calls = []

    with pytest.raises(HistoricalOratsAuthError, match="token"):
        request_json(
            "https://api.orats.io/example",
            token="",
            header_auth=False,
            opener=sequence_opener([], calls),
        )

    assert calls == []
