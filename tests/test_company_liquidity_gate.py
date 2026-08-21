from datetime import UTC, datetime

from daily_alpha.equity_liquidity import CANONICAL_COMPANY_MIN_AVERAGE_VOLUME
from daily_alpha.research_shortlist import build_research_shortlist

NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


def _write_csv(path, rows):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg Volume\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_company_volume_gate_is_strict_and_vendor_independent(tmp_path):
    previous = _write_csv(
        tmp_path / "OVTLYR_2026-08-18.csv",
        [
            "ABOVE,Hold,2026-08-18,Technology,Software,Up,Rising,Yes,100,1500001",
            "EQUAL,Hold,2026-08-18,Technology,Software,Up,Rising,Yes,100,1500000",
            "BELOW,Hold,2026-08-18,Technology,Software,Up,Rising,Yes,100,1499999",
            "MISSING,Hold,2026-08-18,Technology,Software,Up,Rising,Yes,100,0",
        ],
    )
    current = _write_csv(
        tmp_path / "OVTLYR_2026-08-19.csv",
        [
            "ABOVE,Buy,2026-08-19,Technology,Software,Up,Accelerating,Yes,101,1500001",
            "EQUAL,Buy,2026-08-19,Technology,Software,Up,Accelerating,Yes,101,1500000",
            "BELOW,Buy,2026-08-19,Technology,Software,Up,Accelerating,Yes,101,1499999",
            "MISSING,Buy,2026-08-19,Technology,Software,Up,Accelerating,Yes,101,0",
        ],
    )

    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        min_company_average_volume=CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
    )

    assert [item.symbol for item in result.items] == ["ABOVE"]
    assert result.items[0].average_volume == 1_500_001
    assert result.summary["company_average_volume_gate_enabled"] is True
    assert result.summary["company_min_average_volume"] == 1_500_000
    assert result.summary["excluded_liquidity_filtered"] == 2
    assert result.summary["excluded_liquidity_missing"] == 1
    assert result.summary["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"
    assert result.summary["trading_authorized"] is False
    assert result.summary["paper_execution_triggered"] is False
    assert result.summary["live_trading_enabled"] is False


def test_volume_gate_can_be_omitted_for_separate_etf_workflow(tmp_path):
    previous = _write_csv(
        tmp_path / "OVTLYR_2026-08-18.csv",
        ["ETF1,Hold,2026-08-18,Technology,ETF,Up,Rising,No,100,500000"],
    )
    current = _write_csv(
        tmp_path / "OVTLYR_2026-08-19.csv",
        ["ETF1,Buy,2026-08-19,Technology,ETF,Up,Accelerating,No,101,500000"],
    )

    result = build_research_shortlist(previous, current, as_of=NOW)

    assert [item.symbol for item in result.items] == ["ETF1"]
    assert result.items[0].optionable is False
    assert result.summary["company_average_volume_gate_enabled"] is False
    assert result.summary["options_affect_stock_eligibility"] is False
