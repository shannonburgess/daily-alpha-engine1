from datetime import UTC, datetime

from daily_alpha.stock_primary_shortlist import build_stock_primary_shortlist

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def write_csv(path, rows):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Vol.\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_non_optionable_stock_is_retained_as_stock_candidate(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        ["AAA,Hold,2026-08-20,Technology,Software,Up,Rising,No,100,2500000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        ["AAA,Buy,2026-08-21,Technology,Software,Up,Accelerating,No,101,2500000"],
    )
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        company_symbols=frozenset({"AAA"}),
    )

    assert [item.symbol for item in result.items] == ["AAA"]
    assert result.items[0].optionable is False
    assert result.items[0].options_mode == "USER_DIRECTED_BROKER_CHAIN"
    assert result.summary["non_optionable_metadata_count"] == 1
    assert result.summary["options_affect_stock_eligibility"] is False
    assert result.summary["trading_authorized"] is False
    assert result.summary["live_trading_enabled"] is False


def test_optionability_metadata_does_not_change_stock_score_or_rank(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        [
            "AAA,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,100,2500000",
            "BBB,Hold,2026-08-20,Technology,Software,Up,Rising,No,100,2500000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        [
            "AAA,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,101,2500000",
            "BBB,Buy,2026-08-21,Technology,Software,Up,Accelerating,No,101,2500000",
        ],
    )
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        company_symbols=frozenset({"AAA", "BBB"}),
    )

    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["AAA"].score == by_symbol["BBB"].score
    assert result.summary["options_affect_stock_score"] is False
    assert result.summary["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"


def test_company_price_floor_does_not_apply_to_etf_rows(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        [
            "LOW,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,9,2500000",
            "ETF,Hold,2026-08-20,Technology,ETF,Up,Rising,Yes,9,2500000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        [
            "LOW,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,9,2500000",
            "ETF,Buy,2026-08-21,Technology,ETF,Up,Accelerating,Yes,9,2500000",
        ],
    )
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        company_symbols=frozenset({"LOW"}),
    )

    assert [item.symbol for item in result.items] == ["ETF"]
    assert result.summary["excluded_company_price_floor"] == 1


def test_stock_primary_summary_never_authorizes_option_execution(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        ["AAA,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,100,2500000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        ["AAA,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,101,2500000"],
    )
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        company_symbols=frozenset({"AAA"}),
    )

    assert result.summary["stock_primary_execution"] is True
    assert result.summary["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"
    assert result.summary["options_affect_stock_eligibility"] is False
    assert result.summary["options_affect_stock_score"] is False
    assert result.summary["paper_execution_triggered"] is False
