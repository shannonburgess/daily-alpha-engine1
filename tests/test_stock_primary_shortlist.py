from datetime import UTC, datetime

from daily_alpha.models import OptionCandidate
from daily_alpha.orats import OratsChain
from daily_alpha.sources import OratsBatchResult
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


def chain(symbol):
    contract = OptionCandidate(
        symbol=symbol,
        expiration="2026-10-16",
        strike=100,
        option_type="CALL",
        dte=56,
        bid=5.0,
        ask=5.2,
        open_interest=1500,
        volume=1800,
        delta=0.55,
    )
    return OratsChain(symbol, (contract,), NOW, "delayed")


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


class ExplodingSource:
    def fetch(self, symbols, *, as_of):
        raise RuntimeError("provider unavailable")


def test_non_optionable_stock_is_retained_and_does_not_consume_orats_quota(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        ["AAA,Hold,2026-08-20,Technology,Software,Up,Rising,No,100,2500000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        ["AAA,Buy,2026-08-21,Technology,Software,Up,Accelerating,No,101,2500000"],
    )
    source = FakeSource()
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=source,
        company_symbols=frozenset({"AAA"}),
    )

    assert [item.symbol for item in result.items] == ["AAA"]
    assert source.requested == ()
    assert result.items[0].orats_status == "RESEARCH_NOT_APPLICABLE"
    assert result.items[0].orats_reason == "OVTLYR_NOT_OPTIONABLE_STOCK_RETAINED"
    assert result.summary["excluded_not_optionable"] == 0
    assert result.summary["research_non_optionable_count"] == 1
    assert result.summary["orats_stock_eligibility_authority"] is False
    assert result.summary["trading_authorized"] is False
    assert result.summary["live_trading_enabled"] is False


def test_orats_no_dte_and_provider_error_never_remove_stock_candidates(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        [
            "AAA,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,100,2500000",
            "BBB,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,100,2500000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        [
            "AAA,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,101,2500000",
            "BBB,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,101,2500000",
        ],
    )
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=FakeSource(no_options=("AAA",), failed=("BBB",)),
        company_symbols=frozenset({"AAA", "BBB"}),
    )

    assert {item.symbol for item in result.items} == {"AAA", "BBB"}
    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["AAA"].orats_reason == "ORATS_NO_45_75_DTE_OPTIONS_STOCK_RETAINED"
    assert by_symbol["BBB"].orats_reason == "ORATS_DATA_ERROR_STOCK_RETAINED"
    assert result.summary["excluded_orats_no_45_75_dte_options"] == 0
    assert result.summary["research_orats_no_45_75_dte_count"] == 1
    assert result.summary["orats_data_error_count"] == 1


def test_missing_orats_provider_keeps_stock_shortlist_available(tmp_path):
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
        orats_source=None,
        company_symbols=frozenset({"AAA"}),
    )

    assert [item.symbol for item in result.items] == ["AAA"]
    assert result.items[0].orats_status == "SOURCE_UNAVAILABLE"
    assert result.items[0].orats_reason == "ORATS_NOT_CONFIGURED_STOCK_RETAINED"
    assert result.summary["orats_requests"] == 0


def test_wholesale_orats_provider_exception_keeps_stock_candidate(tmp_path):
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
        orats_source=ExplodingSource(),
        company_symbols=frozenset({"AAA"}),
    )

    assert [item.symbol for item in result.items] == ["AAA"]
    assert result.items[0].orats_status == "DATA_ERROR"
    assert result.items[0].orats_reason == "ORATS_PROVIDER_RUNTIMEERROR_STOCK_RETAINED"
    assert result.summary["orats_data_error_count"] == 1


def test_option_quality_does_not_change_stock_score_or_rank(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        [
            "AAA,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,100,2500000",
            "BBB,Hold,2026-08-20,Technology,Software,Up,Rising,Yes,100,2500000",
        ],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        [
            "AAA,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,101,2500000",
            "BBB,Buy,2026-08-21,Technology,Software,Up,Accelerating,Yes,101,2500000",
        ],
    )
    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=FakeSource(no_options=("BBB",)),
        company_symbols=frozenset({"AAA", "BBB"}),
    )

    by_symbol = {item.symbol: item for item in result.items}
    assert by_symbol["AAA"].orats_reason == "QUALIFIED_OPTION_RESEARCH_ONLY"
    assert by_symbol["BBB"].orats_reason == "ORATS_NO_45_75_DTE_OPTIONS_STOCK_RETAINED"
    assert by_symbol["AAA"].score == by_symbol["BBB"].score
    assert result.summary["orats_changes_stock_score"] is False


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
        orats_source=None,
        company_symbols=frozenset({"LOW"}),
    )

    assert [item.symbol for item in result.items] == ["ETF"]
    assert result.summary["excluded_company_price_floor"] == 1


def test_active_buy_continuity_is_retained_without_orats(tmp_path):
    previous = write_csv(
        tmp_path / "OVTLYR_2026-08-20.csv",
        ["AAA,Buy,2026-08-20,Technology,Software,Up,Stable,Yes,100,2500000"],
    )
    current = write_csv(
        tmp_path / "OVTLYR_2026-08-21.csv",
        ["AAA,Buy,2026-08-20,Technology,Software,Up,Stable,Yes,101,2500000"],
    )

    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=None,
        company_symbols=frozenset({"AAA"}),
    )

    assert [item.symbol for item in result.items] == ["AAA"]
    assert result.items[0].ovtlyr_status == "ACTIVE_BUY"
    assert result.items[0].display_label == "ACTIVE BUY"
    assert (
        result.items[0].classification_reason
        == "BUY remains active without a higher-priority setup"
    )
    assert result.items[0].orats_status == "SOURCE_UNAVAILABLE"
    assert result.items[0].orats_reason == "ORATS_NOT_CONFIGURED_STOCK_RETAINED"
    assert result.summary["classification_counts"]["ACTIVE_BUY"] == 1
    assert result.summary["trading_authorized"] is False
    assert result.summary["live_trading_enabled"] is False
