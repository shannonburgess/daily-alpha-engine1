import json

import pytest

from daily_alpha.buy_continuity import (
    apply_liquidity_snapshot,
    build_buy_continuity_from_csv_directory,
    write_buy_continuity_output,
)

HEADER = (
    "Ticker,Signal,Sector,Industry,Trend,Momentum,Optionable,Partial Data Stocks,"
    "30-Day Avg. Volume\n"
)


def _write_flat(root, date, rows, *, suffix=""):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"OVTLYR_{date}{suffix}.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _liquidity_snapshot(rows, *, source_file="OVTLYR_2026-08-19.csv"):
    return {
        "source_file": source_file,
        "company_min_average_volume": 1_500_000.0,
        "company_threshold_semantics": "STRICTLY_GREATER_THAN",
        "rows": rows,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def test_buy_continuity_tracks_persistent_buy_state(tmp_path):
    incoming = tmp_path / "incoming"
    _write_flat(
        incoming,
        "2026-08-17",
        ["AAA,Buy,Technology,Software,Up,Rising,Yes,No,2200000"],
    )
    _write_flat(
        incoming,
        "2026-08-18",
        ["AAA,Buy,Technology,Software,Up,Rising,Yes,No,2250000"],
    )
    _write_flat(
        incoming,
        "2026-08-19",
        ["AAA,Buy,Technology,Software,Up,Accelerating,Yes,No,2300000"],
    )

    states = build_buy_continuity_from_csv_directory(incoming)

    assert len(states) == 1
    state = states[0]
    assert state.symbol == "AAA"
    assert state.active_buy is True
    assert state.current_buy_streak_start == "2026-08-17"
    assert state.consecutive_buy_observations == 3
    assert state.last_meaningful_change_date == "2026-08-19"
    assert state.research_eligibility == "ACTIVE_BUY_ELIGIBLE"
    assert state.average_volume == 2_300_000
    assert state.trading_authorized is False
    assert state.live_trading_enabled is False


def test_active_buy_consumes_canonical_company_liquidity_contract(tmp_path):
    incoming = tmp_path / "incoming"
    _write_flat(
        incoming,
        "2026-08-18",
        [
            "PASS,Buy,Technology,Software,Up,Rising,Yes,No,2000000",
            "EDGE,Buy,Technology,Software,Up,Rising,Yes,No,1500000",
            "ETF1,Buy,Financials,ETF,Up,Rising,Yes,No,900000",
        ],
    )
    _write_flat(
        incoming,
        "2026-08-19",
        [
            "PASS,Buy,Technology,Software,Up,Rising,Yes,No,2000000",
            "EDGE,Buy,Technology,Software,Up,Rising,Yes,No,1500000",
            "ETF1,Buy,Financials,ETF,Up,Rising,Yes,No,900000",
        ],
    )
    states = build_buy_continuity_from_csv_directory(incoming)
    snapshot = _liquidity_snapshot(
        [
            {
                "symbol": "PASS",
                "security_type": "COMPANY_EQUITY",
                "status": "ELIGIBLE",
                "detail": "ABOVE_THRESHOLD",
                "average_daily_share_volume_30d": 2_000_000,
            },
            {
                "symbol": "EDGE",
                "security_type": "COMPANY_EQUITY",
                "status": "LIQUIDITY_FILTERED",
                "detail": "AT_OR_BELOW_THRESHOLD",
                "average_daily_share_volume_30d": 1_500_000,
            },
            {
                "symbol": "ETF1",
                "security_type": "ETF",
                "status": "ETF_SEPARATE_RULES",
                "detail": "COMPANY_SHARE_VOLUME_GATE_NOT_APPLIED",
                "average_daily_share_volume_30d": 900_000,
            },
        ]
    )

    reconciled = {
        state.symbol: state
        for state in apply_liquidity_snapshot(
            states,
            snapshot,
            expected_source_file="OVTLYR_2026-08-19.csv",
        )
    }

    assert reconciled["PASS"].research_eligibility == "ACTIVE_BUY_ELIGIBLE"
    assert reconciled["PASS"].liquidity_status == "ELIGIBLE"
    assert reconciled["EDGE"].research_eligibility == "ACTIVE_BUY_LIQUIDITY_FILTERED"
    assert reconciled["EDGE"].liquidity_status == "LIQUIDITY_FILTERED"
    assert reconciled["ETF1"].research_eligibility == "ACTIVE_BUY_ELIGIBLE"
    assert reconciled["ETF1"].liquidity_status == "ETF_SEPARATE_RULES"


def test_active_buy_liquidity_evidence_fails_closed_on_contract_drift(tmp_path):
    incoming = tmp_path / "incoming"
    _write_flat(
        incoming,
        "2026-08-19",
        ["AAA,Buy,Technology,Software,Up,Rising,Yes,No,2000000"],
    )
    states = build_buy_continuity_from_csv_directory(incoming)
    snapshot = _liquidity_snapshot([])
    snapshot["company_min_average_volume"] = 1_499_999

    with pytest.raises(
        ValueError,
        match="BUY_CONTINUITY_LIQUIDITY_THRESHOLD_CONTRACT_MISMATCH",
    ):
        apply_liquidity_snapshot(
            states,
            snapshot,
            expected_source_file="OVTLYR_2026-08-19.csv",
        )


def test_buy_continuity_output_surfaces_liquidity_counts(tmp_path):
    incoming = tmp_path / "incoming"
    _write_flat(
        incoming,
        "2026-08-19",
        [
            "PASS,Buy,Technology,Software,Up,Rising,Yes,No,2000000",
            "EDGE,Buy,Technology,Software,Up,Rising,Yes,No,1500000",
        ],
    )
    states = build_buy_continuity_from_csv_directory(incoming)
    states = apply_liquidity_snapshot(
        states,
        _liquidity_snapshot(
            [
                {
                    "symbol": "PASS",
                    "security_type": "COMPANY_EQUITY",
                    "status": "ELIGIBLE",
                    "detail": "ABOVE_THRESHOLD",
                    "average_daily_share_volume_30d": 2_000_000,
                },
                {
                    "symbol": "EDGE",
                    "security_type": "COMPANY_EQUITY",
                    "status": "LIQUIDITY_FILTERED",
                    "detail": "AT_OR_BELOW_THRESHOLD",
                    "average_daily_share_volume_30d": 1_500_000,
                },
            ]
        ),
        expected_source_file="OVTLYR_2026-08-19.csv",
    )

    output = write_buy_continuity_output(tmp_path / "buy_continuity.json", states)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["summary"]["active_buy"] == 2
    assert payload["summary"]["eligible_active_buy"] == 1
    assert payload["summary"]["liquidity_filtered_active_buy"] == 1
    assert payload["summary"]["company_min_average_volume"] == 1_500_000.0
    assert payload["summary"]["trading_authorized"] is False
    assert payload["summary"]["live_trading_enabled"] is False


def test_downloaded_dated_csvs_fail_closed_on_duplicate_date(tmp_path):
    incoming = tmp_path / "incoming"
    _write_flat(
        incoming,
        "2026-08-19",
        ["AAA,Buy,Technology,Software,Up,Rising,Yes,No,2000000"],
    )
    _write_flat(
        incoming,
        "2026-08-19",
        ["AAA,Buy,Technology,Software,Up,Rising,Yes,No,2000000"],
        suffix="_copy",
    )

    with pytest.raises(ValueError, match="BUY_CONTINUITY_DUPLICATE_DATE"):
        build_buy_continuity_from_csv_directory(incoming)
