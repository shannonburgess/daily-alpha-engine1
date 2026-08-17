from datetime import date, timedelta

import pytest

from daily_alpha import backtest
from daily_alpha.orats_historical_transport import (
    HistoricalOratsAuthError,
    HistoricalOratsDataError,
    HistoricalOratsHttpError,
    HistoricalOratsRateLimitedError,
)


def daily_rows(count=100):
    start = date(2023, 1, 2)
    return {
        "data": [
            {
                "ticker": "TEST",
                "tradeDate": (start + timedelta(days=i)).isoformat(),
                "clsPx": 100 + i * 0.1,
                "hiPx": 101 + i * 0.1,
                "loPx": 99 + i * 0.1,
                "open": 100 + i * 0.1,
                "stockVolume": 1_000_000,
            }
            for i in range(count)
        ]
    }


def test_404_primary_endpoint_can_use_datav2_compatibility_fallback(monkeypatch):
    calls = []
    effects = [
        HistoricalOratsHttpError(404, "primary route unavailable"),
        daily_rows(),
        {"data": []},
    ]

    def fake_request(url, *, token, header_auth):
        calls.append((url, header_auth))
        effect = effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    monkeypatch.setattr(backtest, "_request_json", fake_request)

    bars, earnings = backtest.fetch_orats_history(
        "TEST",
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        token="secret",
    )

    assert len(bars) == 100
    assert earnings == []
    assert len(calls) == 3
    assert calls[0][1] is True
    assert calls[1][1] is False
    assert "/datav2/hist/dailies" in calls[1][0]


@pytest.mark.parametrize(
    "error",
    [
        HistoricalOratsRateLimitedError("rate limited"),
        HistoricalOratsAuthError("auth failed"),
        HistoricalOratsDataError("invalid JSON"),
        HistoricalOratsHttpError(418, "not a compatibility status"),
    ],
)
def test_non_compatibility_failures_never_trigger_fallback(monkeypatch, error):
    calls = []

    def fake_request(url, *, token, header_auth):
        calls.append((url, header_auth))
        raise error

    monkeypatch.setattr(backtest, "_request_json", fake_request)

    with pytest.raises(type(error)):
        backtest.fetch_orats_history(
            "TEST",
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
            token="secret",
        )

    assert len(calls) == 1
    assert "/data/hist/dailies" in calls[0][0]
    assert calls[0][1] is True
