from datetime import UTC, datetime

from daily_alpha.models import OptionCandidate
from daily_alpha.orats import OratsChain
from daily_alpha.research_shortlist import (
    build_research_shortlist,
    discover_daily_pair,
    write_research_shortlist_outputs,
)
from daily_alpha.smart_money import InstitutionalAccumulation
from daily_alpha.sources import OratsBatchResult

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


def chain(symbol, *, oi=1000, volume=1200, delta=0.55):
    contract = OptionCandidate(
        symbol=symbol,
        expiration="2026-10-16",
        strike=100,
        option_type="CALL",
        dte=61,
        bid=5.0,
        ask=5.2,
        open_interest=oi,
        volume=volume,
        delta=delta,
    )
    return OratsChain(symbol, (contract,), NOW, "delayed")


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


class FakeSource:
    def __init__(self, *, failed=(), no_options=()):
        self.failed = set(failed)
        self.no_options = set(no_options)
        self.requested = ()

    def fetch(self, symbols, *, as_of):
        assert as_of == NOW
        self.requested = symbols
        return OratsBatchResult(
            tuple(
                chain(symbol)
                for symbol in symbols
                if symbol not in self.failed and symbol not in self.no_options
            ),
            tuple(
                (symbol, "ORATS_NO_45_75_DTE_OPTIONS")
                for symbol in symbols
                if symbol in self.no_options
            )
            + tuple(
                (symbol, "ORATS_DATA_ERROR")
                for symbol in symbols
                if symbol in self.failed
            ),
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


def test_ranked_shortlist_enriches_best_and_excludes_non_optionable(tmp_path):
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
    source = FakeSource()
    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=source,
        request_limit=1,
    )
    assert source.requested == ("AAA",)
    assert [item.symbol for item in result.items] == ["AAA", "BBB"]
    assert result.items[0].orats_reason == "QUALIFIED_OPTION_FOUND"
    assert result.items[0].optionable is True
    assert result.items[0].unusual_options_activity is True
    assert result.items[1].orats_reason == "API_LIMIT_REACHED"
    assert result.summary["excluded_not_optionable"] == 1
    assert result.summary["trading_authorized"] is False


def test_smart_money_bonus_can_prioritize_scarce_orats_research_request(tmp_path):
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
    source = FakeSource()
    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=source,
        request_limit=1,
        institutional=(institutional_rank_one("BBB"),),
    )
    assert source.requested == ("BBB",)
    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["BBB"].smart_money_bonus == 10.0
    assert by_symbol["BBB"].institutional_rank == 1
    assert by_symbol["AAA"].smart_money_bonus == 0.0
    assert result.summary["smart_money_matched_candidates"] == 1
    assert result.summary["smart_money_research_ranking_only"] is True
    assert result.summary["trading_authorized"] is False


def test_orats_no_dte_chain_is_filtered_from_shortlist(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-13.csv",
        ["AAA,Hold,2026-08-13,Technology,Software,Up,Rising,,100,1000000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-14.csv",
        ["AAA,Buy,2026-08-14,Technology,Software,Up,Accelerating,,101,1000000"],
    )
    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=FakeSource(no_options=("AAA",)),
    )
    assert result.items == ()
    assert result.summary["excluded_orats_no_45_75_dte_options"] == 1
    assert result.summary["optionability_authority"] == "ORATS_FOR_ENRICHED_SYMBOLS"


def test_orats_error_never_creates_stock_fallback(tmp_path):
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
        orats_source=FakeSource(failed=("AAA",)),
    )
    item = result.items[0]
    assert item.orats_status == "DATA_ERROR"
    assert item.orats_reason == "ORATS_DATA_ERROR"
    assert item.selected_expiration == ""
    assert result.summary["paper_execution_triggered"] is False


def test_write_outputs_includes_newsletter_rotation_and_smart_money_files(tmp_path):
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
        orats_source=FakeSource(),
        institutional=(institutional_rank_one("AAA"),),
    )
    outputs = write_research_shortlist_outputs(tmp_path / "out", result)
    assert set(outputs) == {
        "shortlist_json",
        "shortlist_csv",
        "classifications_json",
        "sector_rotation_json",
        "smart_money_json",
        "summary_json",
    }
    assert all(path.exists() for path in outputs.values())
    assert '"research_ranking_only": true' in outputs["smart_money_json"].read_text()
