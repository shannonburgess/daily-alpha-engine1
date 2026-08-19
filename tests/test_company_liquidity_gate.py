from datetime import UTC, datetime

from daily_alpha.models import OptionCandidate
from daily_alpha.orats import OratsChain
from daily_alpha.research_shortlist import (
    CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
    build_research_shortlist,
)
from daily_alpha.sources import OratsBatchResult

NOW = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)


def _write_csv(path, rows):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Vol.\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def _chain(symbol):
    contract = OptionCandidate(
        symbol=symbol,
        expiration="2026-10-16",
        strike=100,
        option_type="CALL",
        dte=58,
        bid=5.0,
        ask=5.2,
        open_interest=1000,
        volume=1200,
        delta=0.55,
    )
    return OratsChain(symbol, (contract,), NOW, "delayed")


class RecordingSource:
    def __init__(self):
        self.requested = ()

    def fetch(self, symbols, *, as_of):
        assert as_of == NOW
        self.requested = tuple(symbols)
        return OratsBatchResult(
            tuple(_chain(symbol) for symbol in symbols),
            (),
        )


def test_company_volume_gate_is_strict_and_runs_before_orats(tmp_path):
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
    source = RecordingSource()

    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=source,
        request_limit=20,
        min_company_average_volume=CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
    )

    assert source.requested == ("ABOVE",)
    assert [item.symbol for item in result.items] == ["ABOVE"]
    assert result.items[0].average_volume == 1_500_001
    assert result.summary["company_average_volume_gate_enabled"] is True
    assert result.summary["company_min_average_volume"] == 1_500_000
    assert result.summary["excluded_liquidity_filtered"] == 2
    assert result.summary["excluded_liquidity_missing"] == 1
    assert result.summary["trading_authorized"] is False
    assert result.summary["paper_execution_triggered"] is False
    assert result.summary["live_trading_enabled"] is False


def test_company_volume_gate_can_be_omitted_for_separate_non_company_workflows(tmp_path):
    previous = _write_csv(
        tmp_path / "OVTLYR_2026-08-18.csv",
        ["ETF1,Hold,2026-08-18,Technology,ETF,Up,Rising,Yes,100,500000"],
    )
    current = _write_csv(
        tmp_path / "OVTLYR_2026-08-19.csv",
        ["ETF1,Buy,2026-08-19,Technology,ETF,Up,Accelerating,Yes,101,500000"],
    )
    source = RecordingSource()

    result = build_research_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=source,
        request_limit=20,
    )

    assert source.requested == ("ETF1",)
    assert [item.symbol for item in result.items] == ["ETF1"]
    assert result.summary["company_average_volume_gate_enabled"] is False
