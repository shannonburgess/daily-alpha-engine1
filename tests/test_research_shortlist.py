from datetime import UTC, datetime

from daily_alpha.research_shortlist import (
    build_research_shortlist,
    discover_daily_pair,
    write_research_shortlist_outputs,
)
from daily_alpha.smart_money import InstitutionalAccumulation
from daily_alpha.trump_policy import TrumpPolicyCompany

NOW = datetime(2026, 8, 16, 7, 0, tzinfo=UTC)


def write_csv(path, rows):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Vol.\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def institutional_rank_one(symbol):
    return InstitutionalAccumulation(
        rank=1,
        symbol=symbol,
        cusip=f"TICKER:{symbol}",
        issuer=symbol,
        score=100.0,
        managers_increasing=13,
        new_manager_positions=8,
        shares_added=1000.0,
        estimated_value_added=1000000.0,
        period_of_report="2026-06-30",
        top_managers=("Fund A",),
    )


def policy_rank_one(symbol):
    return TrumpPolicyCompany(
        rank=1,
        symbol=symbol,
        company=symbol,
        score=99.0,
        investment_usd=250_000_000_000,
        sector="Technology",
        investment_focus="U.S. investment",
        source_type="WHITE_HOUSE_INVESTMENTS",
        source_url="https://www.whitehouse.gov/investments/",
        administration_beneficiary=True,
    )


def test_discover_daily_pair_uses_filename_date_not_mtime(tmp_path):
    newest = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        ["AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,100,1000000"],
    )
    older = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        ["AAA,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,99,900000"],
    )
    previous, current = discover_daily_pair(tmp_path)
    assert previous == older
    assert current == newest


def test_ranked_shortlist_keeps_non_optionable_stock_research(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        [
            "AAA,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,100,1000000",
            "BBB,Buy,2026-08-10,Industrials,Aerospace,Up,Rising,Yes,50,1000000",
            "CCC,Hold,2026-08-13,Technology,Hardware,Up,Rising,No,40,1000000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        [
            "AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,101,1000000",
            "BBB,Buy,2026-08-10,Industrials,Aerospace,Up,Accelerating,Yes,51,1000000",
            "CCC,Buy,2026-08-14,Technology,Hardware,Up,Accelerating,No,41,1000000",
        ],
    )
    result = build_research_shortlist(previous, current, as_of=NOW)

    assert {item.symbol for item in result.items} == {"AAA", "BBB", "CCC"}
    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["CCC"].optionable is False
    assert result.summary["non_optionable_metadata_count"] == 1
    assert result.summary["options_affect_stock_eligibility"] is False
    assert result.summary["options_affect_stock_score"] is False
    assert result.summary["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"
    assert result.summary["trading_authorized"] is False


def test_smart_money_bonus_prioritizes_stock_research_only(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        [
            "AAA,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,100,1000000",
            "BBB,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,100,1000000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        [
            "AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,101,1000000",
            "BBB,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,101,1000000",
        ],
    )
    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        institutional=(institutional_rank_one("BBB"),),
    )
    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["BBB"].smart_money_bonus == 10.0
    assert by_symbol["BBB"].institutional_rank == 1
    assert by_symbol["AAA"].smart_money_bonus == 0.0
    assert result.items[0].symbol == "BBB"
    assert result.summary["smart_money_research_ranking_only"] is True
    assert result.summary["trading_authorized"] is False


def test_policy_bonus_prioritizes_research_but_never_authorizes_trade(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        [
            "AAA,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,100,1000000",
            "BBB,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,100,1000000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        [
            "AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,101,1000000",
            "BBB,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,101,1000000",
        ],
    )
    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        trump_policy=(policy_rank_one("BBB"),),
    )
    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["BBB"].trump_policy_bonus > 0
    assert by_symbol["BBB"].trump_policy_rank == 1
    assert by_symbol["AAA"].trump_policy_bonus == 0.0
    assert result.items[0].symbol == "BBB"
    assert result.summary["trump_policy_research_ranking_only"] is True
    assert result.summary["trading_authorized"] is False
    assert result.summary["paper_execution_triggered"] is False


def test_optionability_metadata_never_creates_data_error_or_stock_fallback_logic(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        ["AAA,Hold,2026-08-13,Technology,Software,Up,Rising,,100,1000000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        ["AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,,101,1000000"],
    )
    result = build_research_shortlist(previous, current, as_of=NOW)

    assert [item.symbol for item in result.items] == ["AAA"]
    assert result.items[0].options_mode == "USER_DIRECTED_BROKER_CHAIN"
    assert result.summary["options_affect_stock_eligibility"] is False


def test_write_outputs_includes_rotation_and_confirmation_files(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        ["AAA,Hold,2026-08-13,Technology,Software,Up,Rising,Yes,100,1000000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        ["AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,Yes,101,1000000"],
    )
    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        institutional=(institutional_rank_one("AAA"),),
        trump_policy=(policy_rank_one("AAA"),),
    )
    outputs = write_research_shortlist_outputs(tmp_path / "out", result)
    assert set(outputs) == {
        "shortlist_json",
        "shortlist_csv",
        "classifications_json",
        "sector_rotation_json",
        "smart_money_json",
        "trump_policy_json",
        "summary_json",
    }
    assert all(path.exists() for path in outputs.values())
    assert '"research_ranking_only": true' in outputs["smart_money_json"].read_text()
    assert '"not_presidential_stock_recommendations": true' in outputs[
        "trump_policy_json"
    ].read_text()
    assert '"options_mode": "USER_DIRECTED_BROKER_CHAIN"' in outputs[
        "summary_json"
    ].read_text()
