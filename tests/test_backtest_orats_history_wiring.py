from datetime import date, timedelta

import pytest

from daily_alpha import backtest
from daily_alpha.orats_historical_transport import HistoricalOratsRateLimitedError
from daily_alpha.orats_history_fetch import HistoricalDailyEarningsRows


def _daily_rows(count: int = 90) -> tuple[dict[str, object], ...]:
    first = date(2025, 1, 1)
    rows = []
    for offset in range(count):
        trade_date = first + timedelta(days=offset)
        close = 100.0 + offset * 0.1
        rows.append(
            {
                "ticker": "NVDA",
                "tradeDate": trade_date.isoformat(),
                "open": close - 0.2,
                "hiPx": close + 0.5,
                "loPx": close - 0.5,
                "clsPx": close,
                "stockVolume": 1_000_000,
                "source": "ORATS_DATA_API",
            }
        )
    return tuple(rows)


def test_backtest_fetch_uses_strict_adapter_and_preserves_provenance(monkeypatch):
    earnings_date = date(2025, 2, 10)
    adapter_result = HistoricalDailyEarningsRows(
        daily_rows=_daily_rows(),
        earnings_rows=(
            {
                "ticker": "NVDA",
                "earnDate": earnings_date.isoformat(),
                "anncTod": "AMC",
                "source": "ORATS_DATAV2_API",
            },
        ),
        daily_source="ORATS_DATA_API",
        earnings_source="ORATS_DATAV2_API",
        daily_used_compatibility_fallback=False,
        earnings_used_compatibility_fallback=True,
    )
    calls = []

    def strict_adapter(ticker, *, warm_start, end, token):
        calls.append((ticker, warm_start, end, token))
        return adapter_result

    monkeypatch.setattr(backtest, "fetch_daily_earnings_rows", strict_adapter)

    bars, earnings = backtest.fetch_orats_history(
        "NVDA",
        start=date(2025, 1, 15),
        end=date(2025, 4, 15),
        token="secret",
    )

    assert len(calls) == 1
    assert calls[0][0] == "NVDA"
    assert calls[0][3] == "secret"
    assert len(bars) == 90
    assert any(bar.trade_date == earnings_date and bar.earnings_event for bar in bars)
    assert earnings[0]["source"] == "ORATS_DATAV2_API"
    assert earnings[0]["daily_source"] == "ORATS_DATA_API"
    assert earnings[0]["earnings_source"] == "ORATS_DATAV2_API"
    assert earnings[0]["daily_used_compatibility_fallback"] is False
    assert earnings[0]["earnings_used_compatibility_fallback"] is True


def test_backtest_fetch_does_not_mask_rate_limit_as_compatibility_fallback(monkeypatch):
    def strict_adapter(*args, **kwargs):
        raise HistoricalOratsRateLimitedError("rate limited")

    monkeypatch.setattr(backtest, "fetch_daily_earnings_rows", strict_adapter)

    with pytest.raises(HistoricalOratsRateLimitedError, match="rate limited"):
        backtest.fetch_orats_history(
            "NVDA",
            start=date(2025, 1, 15),
            end=date(2025, 4, 15),
            token="secret",
        )
