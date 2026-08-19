from datetime import date, datetime, timezone

import pytest

from daily_alpha.orats_history_route import HistoricalRouteResult
from daily_alpha.strategy_forensics_observations import DecisionObservation
from daily_alpha.strategy_forensics_orats import (
    build_forensics_path_from_orats,
    fetch_orats_forensics_bars,
    price_bars_from_orats_daily_rows,
)


def _daily_rows() -> list[dict[str, object]]:
    return [
        {
            "ticker": "AMD",
            "tradeDate": "2026-08-17",
            "hiPx": 181.0,
            "loPx": 176.0,
            "clsPx": 180.0,
        },
        {
            "ticker": "AMD",
            "tradeDate": "2026-08-18",
            "hiPx": 186.0,
            "loPx": 179.0,
            "clsPx": 185.0,
        },
        {
            "ticker": "AMD",
            "tradeDate": "2026-08-19",
            "hiPx": 188.0,
            "loPx": 183.0,
            "clsPx": 187.0,
        },
    ]


def _router(*, source: str = "ORATS_DATAV2_API", fallback: bool = False):
    def route(primary_url: str, fallback_url: str, **_: object) -> HistoricalRouteResult:
        del fallback_url
        payload = {"data": _daily_rows()} if "/dailies?" in primary_url else {"data": []}
        return HistoricalRouteResult(
            payload=payload,
            source=source,
            used_compatibility_fallback=fallback,
        )

    return route


def test_fetch_orats_forensics_bars_preserves_provenance_and_identity() -> None:
    evidence = fetch_orats_forensics_bars(
        "amd",
        start=date(2026, 8, 17),
        end=date(2026, 8, 19),
        token="test-token",
        router=_router(),
    )

    assert evidence.symbol == "AMD"
    assert evidence.source == "ORATS_DATAV2_API"
    assert evidence.used_compatibility_fallback is False
    assert evidence.market_close_timezone == "America/New_York"
    assert len(evidence.rows_sha256) == 64
    assert [bar.close for bar in evidence.bars] == [180.0, 185.0, 187.0]
    assert all(bar.observed_at.utcoffset() is not None for bar in evidence.bars)
    assert evidence.trading_authorized is False
    assert evidence.live_trading_enabled is False


def test_orats_forensics_row_hash_is_order_independent() -> None:
    forward = fetch_orats_forensics_bars(
        "AMD",
        start=date(2026, 8, 17),
        end=date(2026, 8, 19),
        token="test-token",
        router=_router(),
    )

    def reverse_router(
        primary_url: str,
        fallback_url: str,
        **_: object,
    ) -> HistoricalRouteResult:
        del fallback_url
        payload = (
            {"data": list(reversed(_daily_rows()))}
            if "/dailies?" in primary_url
            else {"data": []}
        )
        return HistoricalRouteResult(
            payload=payload,
            source="ORATS_DATAV2_API",
            used_compatibility_fallback=False,
        )

    reverse = fetch_orats_forensics_bars(
        "AMD",
        start=date(2026, 8, 17),
        end=date(2026, 8, 19),
        token="test-token",
        router=reverse_router,
    )

    assert forward.rows_sha256 == reverse.rows_sha256
    assert forward.bars == reverse.bars


def test_build_forensics_path_from_orats_respects_decision_and_cutoff() -> None:
    decision = DecisionObservation(
        decision_id="signal-1",
        symbol="AMD",
        strategy_version="v2.4",
        decision="ENTRY",
        reason="QUALIFIED",
        observed_at=datetime(2026, 8, 17, 20, 0, tzinfo=timezone.utc),
        reference_price=180.0,
        stop_price=174.0,
        executed=True,
    )

    path, evidence = build_forensics_path_from_orats(
        decision,
        evaluation_cutoff=datetime(2026, 8, 18, 21, 0, tzinfo=timezone.utc),
        token="test-token",
        router=_router(),
    )

    assert path.bars_used == 1
    assert path.ignored_predecision_bars == 1
    assert path.ignored_after_cutoff_bars == 0
    assert path.path.max_price_after == 186.0
    assert path.path.min_price_after == 179.0
    assert path.path.terminal_price == 185.0
    assert evidence.requested_start == "2026-08-17"
    assert evidence.requested_end == "2026-08-18"


def test_fetch_orats_forensics_bars_preserves_compatibility_fallback_status() -> None:
    evidence = fetch_orats_forensics_bars(
        "AMD",
        start=date(2026, 8, 17),
        end=date(2026, 8, 19),
        token="test-token",
        router=_router(source="ORATS_DATA_API", fallback=True),
    )

    assert evidence.source == "ORATS_DATA_API"
    assert evidence.used_compatibility_fallback is True


def test_price_bars_fail_closed_on_symbol_source_and_duplicate_date() -> None:
    with pytest.raises(ValueError, match="FORENSICS_ORATS_SYMBOL_MISMATCH"):
        price_bars_from_orats_daily_rows(
            [
                {
                    "ticker": "NVDA",
                    "tradeDate": "2026-08-18",
                    "hiPx": 10,
                    "loPx": 9,
                    "clsPx": 9.5,
                    "source": "ORATS_DATAV2_API",
                }
            ],
            symbol="AMD",
            source="ORATS_DATAV2_API",
        )

    with pytest.raises(ValueError, match="FORENSICS_ORATS_SOURCE_MISMATCH"):
        price_bars_from_orats_daily_rows(
            [
                {
                    "ticker": "AMD",
                    "tradeDate": "2026-08-18",
                    "hiPx": 10,
                    "loPx": 9,
                    "clsPx": 9.5,
                    "source": "OTHER",
                }
            ],
            symbol="AMD",
            source="ORATS_DATAV2_API",
        )

    duplicate = [
        {
            "ticker": "AMD",
            "tradeDate": "2026-08-18",
            "hiPx": 10,
            "loPx": 9,
            "clsPx": 9.5,
            "source": "ORATS_DATAV2_API",
        },
        {
            "ticker": "AMD",
            "tradeDate": "2026-08-18",
            "hiPx": 10.2,
            "loPx": 9.1,
            "clsPx": 9.8,
            "source": "ORATS_DATAV2_API",
        },
    ]
    with pytest.raises(ValueError, match="FORENSICS_ORATS_DUPLICATE_TRADE_DATE"):
        price_bars_from_orats_daily_rows(
            duplicate,
            symbol="AMD",
            source="ORATS_DATAV2_API",
        )
