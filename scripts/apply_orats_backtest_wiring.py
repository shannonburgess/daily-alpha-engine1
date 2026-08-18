from pathlib import Path

BACKTEST = Path("src/daily_alpha/backtest.py")
TEST = Path("tests/test_backtest_orats_history_wiring.py")

text = BACKTEST.read_text(encoding="utf-8")
import_anchor = "from urllib.request import Request, urlopen\n\nCANONICAL_GAP_GO_CLOSE_LOCATION"
if "from .orats_history_fetch import fetch_daily_earnings_payloads" not in text:
    text = text.replace(
        import_anchor,
        "from urllib.request import Request, urlopen\n\nfrom .orats_history_fetch import fetch_daily_earnings_payloads\n\nCANONICAL_GAP_GO_CLOSE_LOCATION",
        1,
    )

start = text.index("def fetch_orats_history(\n")
end = text.index("\n\ndef sma(", start)
replacement = '''def fetch_orats_history(
    ticker: str,
    *,
    start: date,
    end: date,
    token: str,
) -> tuple[list[Bar], list[dict[str, Any]]]:
    """Fetch point-in-time ORATS daily/earnings history through the strict route policy.

    RATE_LIMITED, AUTH, malformed-data, and exhausted-network failures propagate from
    the hardened historical transport. Compatibility fallback is therefore controlled
    only by ``fetch_daily_earnings_payloads`` and can no longer be triggered by a broad
    ``RuntimeError`` catch in this backtest layer.
    """

    warm_start = start - timedelta(days=730)
    fetched = fetch_daily_earnings_payloads(
        ticker,
        warm_start=warm_start,
        end=end,
        token=token,
    )
    daily_payload = fetched.daily_payload
    earnings_payload = fetched.earnings_payload

    earnings = _rows(earnings_payload)
    earnings_dates = {
        date.fromisoformat(str(row["earnDate"])[:10])
        for row in earnings
        if row.get("earnDate")
    }

    bars: list[Bar] = []
    for row in _rows(daily_payload):
        raw_date = row.get("tradeDate")
        if not raw_date:
            continue
        trade_date = date.fromisoformat(str(raw_date)[:10])
        if trade_date < warm_start or trade_date > end:
            continue
        opn = _number(row.get("open"))
        high = _number(row.get("hiPx"))
        low = _number(row.get("loPx"))
        close = _number(row.get("clsPx"))
        volume = _number(row.get("stockVolume"))
        if min(opn, high, low, close) <= 0:
            continue
        bars.append(
            Bar(
                trade_date=trade_date,
                open=opn,
                high=high,
                low=low,
                close=close,
                volume=volume,
                earnings_event=trade_date in earnings_dates,
            )
        )
    bars.sort(key=lambda b: b.trade_date)
    if len(bars) < 80:
        raise RuntimeError(f"Insufficient ORATS bars for {ticker}: {len(bars)}")

    earnings_with_provenance = [
        {
            **row,
            "source": fetched.earnings_source,
            "daily_source": fetched.daily_source,
            "daily_used_compatibility_fallback": fetched.daily_used_compatibility_fallback,
            "earnings_used_compatibility_fallback": fetched.earnings_used_compatibility_fallback,
        }
        for row in earnings
    ]
    return bars, earnings_with_provenance
'''
text = text[:start] + replacement + text[end:]
BACKTEST.write_text(text, encoding="utf-8")

TEST.write_text(
    '''from datetime import date, timedelta\n\nimport pytest\n\nfrom daily_alpha import backtest\nfrom daily_alpha.orats_historical_transport import HistoricalOratsRateLimitedError\nfrom daily_alpha.orats_history_fetch import HistoricalDailyEarningsPayloads\n\n\ndef _daily_rows(count: int = 100):\n    start = date(2024, 1, 1)\n    rows = []\n    for i in range(count):\n        d = start + timedelta(days=i)\n        rows.append({\n            "ticker": "TEST",\n            "tradeDate": d.isoformat(),\n            "open": 100 + i * 0.1,\n            "hiPx": 101 + i * 0.1,\n            "loPx": 99 + i * 0.1,\n            "clsPx": 100.5 + i * 0.1,\n            "stockVolume": 1_000_000 + i,\n        })\n    return rows\n\n\ndef test_fetch_orats_history_uses_strict_adapter_and_preserves_provenance(monkeypatch):\n    calls = []\n\n    def fake_fetch(ticker, *, warm_start, end, token):\n        calls.append((ticker, warm_start, end, token))\n        return HistoricalDailyEarningsPayloads(\n            daily_payload={"data": _daily_rows()},\n            earnings_payload={"data": [{"ticker": "TEST", "earnDate": "2024-02-15", "anncTod": "After Market"}]},\n            daily_source="ORATS_DATA_API",\n            earnings_source="ORATS_DATAV2_API",\n            daily_used_compatibility_fallback=False,\n            earnings_used_compatibility_fallback=True,\n        )\n\n    monkeypatch.setattr(backtest, "fetch_daily_earnings_payloads", fake_fetch)\n    bars, earnings = backtest.fetch_orats_history(\n        "TEST", start=date(2024, 1, 1), end=date(2024, 5, 1), token="token"\n    )\n\n    assert len(bars) == 100\n    assert bars[45].earnings_event is True\n    assert calls[0][0] == "TEST"\n    assert calls[0][1] == date(2024, 1, 1) - timedelta(days=730)\n    assert earnings == [{\n        "ticker": "TEST",\n        "earnDate": "2024-02-15",\n        "anncTod": "After Market",\n        "source": "ORATS_DATAV2_API",\n        "daily_source": "ORATS_DATA_API",\n        "daily_used_compatibility_fallback": False,\n        "earnings_used_compatibility_fallback": True,\n    }]\n\n\ndef test_fetch_orats_history_does_not_mask_rate_limit(monkeypatch):\n    def rate_limited(*args, **kwargs):\n        raise HistoricalOratsRateLimitedError("exhausted")\n\n    monkeypatch.setattr(backtest, "fetch_daily_earnings_payloads", rate_limited)\n    with pytest.raises(HistoricalOratsRateLimitedError):\n        backtest.fetch_orats_history(\n            "TEST", start=date(2024, 1, 1), end=date(2024, 5, 1), token="token"\n        )\n\n\ndef test_fetch_orats_history_still_fails_closed_on_unexpected_payload(monkeypatch):\n    def malformed_shape(*args, **kwargs):\n        return HistoricalDailyEarningsPayloads(\n            daily_payload={"unexpected": []},\n            earnings_payload={"data": []},\n            daily_source="ORATS_DATA_API",\n            earnings_source="ORATS_DATA_API",\n            daily_used_compatibility_fallback=False,\n            earnings_used_compatibility_fallback=False,\n        )\n\n    monkeypatch.setattr(backtest, "fetch_daily_earnings_payloads", malformed_shape)\n    with pytest.raises(RuntimeError, match="Unexpected ORATS response shape"):\n        backtest.fetch_orats_history(\n            "TEST", start=date(2024, 1, 1), end=date(2024, 5, 1), token="token"\n        )\n''',
    encoding="utf-8",
)
