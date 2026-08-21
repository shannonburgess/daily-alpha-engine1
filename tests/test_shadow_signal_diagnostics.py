from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from daily_alpha.backtest import Bar
from daily_alpha.orats_history_fetch import HistoricalDailyEarningsRows
from scripts.shadow_signal_diagnostics import (
    PINE_SOURCE_PATH,
    TargetBarUnavailable,
    _fetch_sh24_history,
    _history_date,
    _received_symbols,
    diagnose_sh24_history,
    diagnose_sh24_point,
    reconcile_universe,
    run_orats_diagnostic,
    validate_pine_contract,
)


def _bar(close: float = 100.0, *, trade_date: date = date(2026, 8, 19)) -> Bar:
    return Bar(
        trade_date=trade_date,
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        volume=5_000_000,
    )


def _normal_row(**overrides):
    row = {
        "fresh_breakout": True,
        "trend_state": 1,
        "normal_trend_mature": True,
        "is_earnings_up_gap": False,
        "gap_go": False,
        "efficiency": 0.35,
        "rsi": 65.0,
        "adx": 30.0,
    }
    row.update(overrides)
    return row


def _history_rows(*, zero_earnings_date: bool = False) -> HistoricalDailyEarningsRows:
    end = date(2026, 8, 19)
    daily_rows = []
    for offset in range(100, -1, -1):
        trade_date = end - timedelta(days=offset)
        daily_rows.append(
            {
                "ticker": "AAPL",
                "tradeDate": trade_date.isoformat(),
                "open": 100.0,
                "hiPx": 102.0,
                "loPx": 99.0,
                "clsPx": 101.0,
                "stockVolume": 5_000_000,
            }
        )
    earnings_rows = (
        ({"ticker": "AAPL", "earnDate": "0000-00-00"},)
        if zero_earnings_date
        else ({"ticker": "AAPL", "earnDate": "2026-08-01"},)
    )
    return HistoricalDailyEarningsRows(
        daily_rows=tuple(daily_rows),
        earnings_rows=earnings_rows,
        daily_source="ORATS_DATAV2_API",
        earnings_source="ORATS_DATAV2_API",
        daily_used_compatibility_fallback=False,
        earnings_used_compatibility_fallback=False,
    )


def test_current_v24_pine_source_matches_diagnostic_contract():
    pine = Path(PINE_SOURCE_PATH).read_text()

    assert validate_pine_contract(pine) == ()


def test_normal_breakout_passes_exact_sh24_defaults():
    diagnostic = diagnose_sh24_point(
        symbol="AAPL",
        bar=_bar(),
        indicator_row=_normal_row(adx=25.0, efficiency=0.20, rsi=80.0),
    )

    assert diagnostic.status == "ENTRY_EXPECTED"
    assert diagnostic.entry_type == "NORMAL_BREAKOUT"
    assert diagnostic.primary_reason == "SH24_ENTRY_GATES_PASSED"
    assert diagnostic.blockers == ()
    assert diagnostic.trading_authorized is False
    assert diagnostic.live_trading_enabled is False


def test_adx_below_25_blocks_sh24_even_though_old_backtest_threshold_was_lower():
    diagnostic = diagnose_sh24_point(
        symbol="AAPL",
        bar=_bar(),
        indicator_row=_normal_row(adx=24.99),
    )

    assert diagnostic.status == "NO_ENTRY_EXPECTED"
    assert diagnostic.primary_reason == "ADX_BELOW_SH24_MIN"
    assert diagnostic.blockers == ("ADX_BELOW_SH24_MIN",)


def test_no_fresh_breakout_is_reported_as_primary_upstream_blocker():
    diagnostic = diagnose_sh24_point(
        symbol="NVDA",
        bar=_bar(),
        indicator_row=_normal_row(fresh_breakout=False),
    )

    assert diagnostic.status == "NO_ENTRY_EXPECTED"
    assert diagnostic.primary_reason == "NO_FRESH_20D_BREAKOUT"
    assert "NO_FRESH_20D_BREAKOUT" in diagnostic.blockers


def test_full_earnings_gap_go_bypasses_normal_adx_and_efficiency_gates():
    diagnostic = diagnose_sh24_point(
        symbol="NFLX",
        bar=_bar(),
        indicator_row=_normal_row(
            is_earnings_up_gap=True,
            gap_go=True,
            adx=10.0,
            efficiency=0.05,
            rsi=84.0,
        ),
    )

    assert diagnostic.status == "ENTRY_EXPECTED"
    assert diagnostic.entry_type == "EARNINGS_GAP_GO"


def test_reconcile_flags_expected_entry_missing_only_when_alert_coverage_is_verified():
    expected = diagnose_sh24_point(
        symbol="AAPL",
        bar=_bar(),
        indicator_row=_normal_row(),
    )
    blocked = diagnose_sh24_point(
        symbol="NVDA",
        bar=_bar(),
        indicator_row=_normal_row(fresh_breakout=False),
    )

    result = reconcile_universe(
        [expected, blocked],
        received_strategy_symbols=[],
        covered_symbols=["AAPL"],
    )

    assert result["interpretation"] == "EXPECTED_SH24_ENTRY_NOT_OBSERVED_AT_AWS_BOUNDARY"
    assert result["tradingview_coverage_known"] is True
    assert result["expected_entry_symbols"] == ["AAPL"]
    assert result["expected_but_not_received"] == ["AAPL"]
    assert result["expected_without_verifiable_coverage"] == []
    assert result["blocker_counts"]["NO_FRESH_20D_BREAKOUT"] == 1
    assert result["promotion_authorized"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_reconcile_does_not_call_unknown_tradingview_coverage_a_missed_alert():
    expected = diagnose_sh24_point(
        symbol="AAPL",
        bar=_bar(),
        indicator_row=_normal_row(),
    )

    result = reconcile_universe([expected], received_strategy_symbols=[])

    assert (
        result["interpretation"]
        == "SH24_SOURCE_EXPECTATIONS_FOUND_TRADINGVIEW_COVERAGE_UNVERIFIABLE"
    )
    assert result["tradingview_coverage_known"] is False
    assert result["expected_but_not_received"] == []
    assert result["expected_without_verifiable_coverage"] == ["AAPL"]
    assert result["ok"] is True


def test_reconcile_can_state_no_sh24_entry_expected_without_claiming_sh25():
    blocked = diagnose_sh24_point(
        symbol="NVDA",
        bar=_bar(),
        indicator_row=_normal_row(fresh_breakout=False),
    )

    result = reconcile_universe([blocked])

    assert result["interpretation"] == "NO_SH24_ENTRY_EXPECTED_FROM_APPROVED_DAILY_BARS"
    assert result["expected_entry_count"] == 0
    assert any("SH25" in note for note in result["coverage_limitations"])
    assert any("TradingView" in note for note in result["coverage_limitations"])


def test_received_symbols_only_reads_the_sh24_isolated_book():
    status = {
        "accounts": {
            "PAPER_SHADOW_V24": {
                "session_strategy_events": [{"symbol": "AAPL"}],
            },
            "PAPER_SHADOW_V25": {
                "session_strategy_events": [{"symbol": "NVDA"}],
            },
        }
    }

    assert _received_symbols(status) == {"AAPL"}


def test_year_zero_orats_date_is_explicit_unavailable_sentinel():
    assert _history_date("0000-00-00", field="earnDate", symbol="AAPL") is None


def test_non_sentinel_malformed_orats_date_still_fails_closed():
    with pytest.raises(ValueError, match="invalid ORATS earnDate"):
        _history_date("2026-99-99", field="earnDate", symbol="AAPL")


def test_sh24_history_ignores_and_audits_orats_zero_earnings_date(monkeypatch):
    history = _history_rows(zero_earnings_date=True)
    monkeypatch.setattr(
        "scripts.shadow_signal_diagnostics.fetch_daily_earnings_rows",
        lambda *args, **kwargs: history,
    )

    bars, audit = _fetch_sh24_history(
        "AAPL",
        start=date(2026, 8, 19),
        end=date(2026, 8, 19),
        token="token",
    )

    assert len(bars) >= 80
    assert bars[-1].trade_date == date(2026, 8, 19)
    assert bars[-1].earnings_event is False
    assert audit == {
        "ignored_zero_date_earnings_rows": 1,
        "ignored_zero_date_daily_rows": 0,
    }


def test_missing_target_bar_with_valid_prior_history_is_provider_pending():
    bars = [
        _bar(trade_date=date(2026, 8, 19) - timedelta(days=offset))
        for offset in range(79, -1, -1)
    ]

    with pytest.raises(TargetBarUnavailable) as caught:
        diagnose_sh24_history("AAPL", bars, target_date=date(2026, 8, 20))

    assert caught.value.latest_date == date(2026, 8, 19)


def test_uniform_missing_target_bars_are_pending_provider_publication(monkeypatch):
    def pending(symbol, *, start, end, token):
        del start, token
        raise TargetBarUnavailable(symbol, end, date(2026, 8, 19))

    monkeypatch.setattr("scripts.shadow_signal_diagnostics._fetch_sh24_history", pending)

    result = run_orats_diagnostic(
        ["AAPL", "NVDA"],
        target_date=date(2026, 8, 20),
        token="token",
    )

    assert result["ok"] is True
    assert result["source_diagnostic_complete"] is False
    assert result["source_data_status"] == "PENDING_PROVIDER_PUBLICATION"
    assert result["interpretation"] == "SH24_SOURCE_DATA_NOT_YET_PUBLISHED"
    assert result["target_bar_unavailable_count"] == 2
    assert result["symbols_evaluated"] == 0


def test_partial_target_bar_publication_fails_closed(monkeypatch):
    good_bars = [
        _bar(trade_date=date(2026, 8, 20) - timedelta(days=offset))
        for offset in range(79, -1, -1)
    ]

    def partial(symbol, *, start, end, token):
        del start, token
        if symbol == "NVDA":
            raise TargetBarUnavailable(symbol, end, date(2026, 8, 19))
        return good_bars, {
            "ignored_zero_date_earnings_rows": 0,
            "ignored_zero_date_daily_rows": 0,
        }

    monkeypatch.setattr("scripts.shadow_signal_diagnostics._fetch_sh24_history", partial)
    monkeypatch.setattr(
        "scripts.shadow_signal_diagnostics.indicators",
        lambda bars: [_normal_row(fresh_breakout=False) for _ in bars],
    )

    result = run_orats_diagnostic(
        ["AAPL", "NVDA"],
        target_date=date(2026, 8, 20),
        token="token",
    )

    assert result["ok"] is False
    assert result["source_diagnostic_complete"] is False
    assert result["source_data_status"] == "PARTIAL_PROVIDER_PUBLICATION"
    assert result["interpretation"] == "INCOMPLETE_SH24_SOURCE_DIAGNOSTIC"
