from datetime import UTC, datetime

from daily_alpha.research_shortlist import build_research_shortlist
from daily_alpha.sources import OratsBatchResult

NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


class DataErrorSource:
    def fetch(self, symbols, *, as_of):
        assert as_of == NOW
        return OratsBatchResult(
            (),
            tuple((symbol, "ORATS_DATA_ERROR") for symbol in symbols),
        )


def _write_csv(path, rows):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Volume\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_persistent_buy_above_liquidity_gate_remains_visible_as_active_buy(tmp_path):
    previous = _write_csv(
        tmp_path / "OVTLYR_2026-08-18.csv",
        ["AAA,Buy,2026-08-10,Technology,Software,Sideways,Flat,Yes,100,2000000"],
    )
    current = _write_csv(
        tmp_path / "OVTLYR_2026-08-19.csv",
        ["AAA,Buy,2026-08-10,Technology,Software,Sideways,Flat,Yes,101,2100000"],
    )

    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=DataErrorSource(),
        request_limit=1,
        min_company_average_volume=1_500_000,
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert item.symbol == "AAA"
    assert item.ovtlyr_status == "ACTIVE_BUY"
    assert item.display_label == "ACTIVE BUY"
    assert item.orats_status == "DATA_ERROR"
    assert result.summary["persistent_active_buy_count"] == 1
    assert result.summary["company_average_volume_gate_enabled"] is True
    assert result.summary["trading_authorized"] is False
    assert result.summary["paper_execution_triggered"] is False
    assert result.summary["live_trading_enabled"] is False


def test_persistent_buy_at_liquidity_threshold_is_filtered_before_orats(tmp_path):
    previous = _write_csv(
        tmp_path / "OVTLYR_2026-08-18.csv",
        ["AAA,Buy,2026-08-10,Technology,Software,Sideways,Flat,Yes,100,1500000"],
    )
    current = _write_csv(
        tmp_path / "OVTLYR_2026-08-19.csv",
        ["AAA,Buy,2026-08-10,Technology,Software,Sideways,Flat,Yes,101,1500000"],
    )

    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=DataErrorSource(),
        request_limit=1,
        min_company_average_volume=1_500_000,
    )

    assert result.items == ()
    assert result.summary["persistent_active_buy_count"] == 0
    assert result.summary["excluded_liquidity_filtered"] == 1
    assert result.summary["orats_requests"] == 0
