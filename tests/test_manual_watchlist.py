import json

import pytest

from daily_alpha.manual_watchlist import (
    ManualWatchlistError,
    build_manual_watch_snapshots,
    load_manual_watchlist,
    render_manual_watch_section,
)


def test_seeded_watchlist_keeps_nflx_pinned():
    specs = load_manual_watchlist("config/manual_watchlist.json")
    assert [spec.symbol for spec in specs] == ["NFLX"]
    assert specs[0].reason == "USER_PINNED"


def test_manual_watch_uses_full_classification_even_when_not_shortlisted():
    specs = load_manual_watchlist("config/manual_watchlist.json")
    classifications = [
        {
            "symbol": "NFLX",
            "status": "ACTIVE_BUY",
            "signal": "BUY",
            "signal_date": "2026-08-10",
            "trend": "UP",
            "momentum": "RISING",
            "sector": "Communication Services",
            "industry": "Entertainment",
            "optionable": True,
            "reason": "BUY remains active without a higher-priority setup",
        }
    ]
    snapshots = build_manual_watch_snapshots(
        specs,
        classifications=classifications,
        shortlist=(),
    )

    item = snapshots[0]
    assert item.symbol == "NFLX"
    assert item.current_daily_alpha_status == "ACTIVE_BUY"
    assert item.signal == "BUY"
    assert item.orats_status == "NOT_ENRICHED_THIS_RUN"
    assert item.data_status == "PASS"
    assert item.trading_authorized is False
    assert item.live_trading_enabled is False


def test_manual_watch_preserves_orats_data_error_instead_of_implying_setup():
    specs = load_manual_watchlist("config/manual_watchlist.json")
    classifications = [
        {
            "symbol": "NFLX",
            "status": "ENTRY_WATCH",
            "signal": "BUY",
            "trend": "UP",
            "momentum": "RISING",
            "sector": "Communication Services",
            "industry": "Entertainment",
            "optionable": True,
            "reason": "Approaching entry",
        }
    ]
    shortlist = [
        {
            "symbol": "NFLX",
            "orats_status": "DATA_ERROR",
            "orats_reason": "ORATS_RATE_LIMITED",
        }
    ]
    item = build_manual_watch_snapshots(
        specs,
        classifications=classifications,
        shortlist=shortlist,
    )[0]

    assert item.current_daily_alpha_status == "ENTRY_WATCH"
    assert item.data_status == "DATA_ERROR"
    assert item.orats_reason == "ORATS_RATE_LIMITED"
    assert item.selected_option_contract == ""


def test_manual_watch_missing_current_classification_stays_visible_as_data_error():
    specs = load_manual_watchlist("config/manual_watchlist.json")
    item = build_manual_watch_snapshots(
        specs,
        classifications=(),
        shortlist=(),
    )[0]

    assert item.symbol == "NFLX"
    assert item.current_daily_alpha_status == "UNKNOWN"
    assert item.data_status == "DATA_ERROR"
    assert item.status_reason == "CURRENT_CLASSIFICATION_MISSING"


def test_manual_watch_section_explicitly_separates_visibility_from_signal():
    specs = load_manual_watchlist("config/manual_watchlist.json")
    item = build_manual_watch_snapshots(
        specs,
        classifications=[
            {
                "symbol": "NFLX",
                "status": "LEADER",
                "signal": "BUY",
                "trend": "UP",
                "momentum": "ACCELERATING",
                "sector": "Communication Services",
                "industry": "Entertainment",
                "optionable": True,
                "reason": "Sustained leadership",
            }
        ],
        shortlist=[
            {
                "symbol": "NFLX",
                "orats_status": "ENRICHED",
                "orats_reason": "QUALIFIED_OPTION_FOUND",
                "selected_expiration": "2026-10-16",
                "selected_option_type": "CALL",
                "selected_strike": 1300,
            }
        ],
    )[0]
    html = render_manual_watch_section((item,))

    assert "Manual Watch — Research Only" in html
    assert "NFLX" in html
    assert "MANUAL WATCH" in html
    assert "LEADER" in html
    assert "2026-10-16 CALL 1300" in html
    assert "cannot bypass Pine" in html


def test_duplicate_watch_symbols_fail_closed(tmp_path):
    path = tmp_path / "watch.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "entries": [
                    {"symbol": "NFLX", "enabled": True},
                    {"symbol": "nflx", "enabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManualWatchlistError, match="MANUAL_WATCH_DUPLICATE_SYMBOL"):
        load_manual_watchlist(path)
