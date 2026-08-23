import json
from datetime import UTC, datetime

from daily_alpha.models import OptionCandidate
from daily_alpha.orats import OratsChain
from daily_alpha.prospect_staging_runtime import AwsProspectStagingRuntimePublisher
from daily_alpha.research_shortlist import write_research_shortlist_outputs
from daily_alpha.sources import OratsBatchResult
from daily_alpha.stock_primary_shortlist import build_stock_primary_shortlist

NOW = datetime(2026, 8, 24, 13, 5, tzinfo=UTC)


def _write_csv(path, rows):
    path.write_text(
        "Ticker,Signal,Overlay Start Date,Sector,Industry,Trend,Momentum,Optionable,"
        "Last Close Price ($),30-Day Avg. Vol.\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def _chain(symbol: str) -> OratsChain:
    contract = OptionCandidate(
        symbol=symbol,
        expiration="2026-10-16",
        strike=100,
        option_type="CALL",
        dte=53,
        bid=5.0,
        ask=5.2,
        open_interest=1000,
        volume=1200,
        delta=0.55,
    )
    return OratsChain(symbol, (contract,), NOW, "delayed")


class _RecordingOratsSource:
    def __init__(self) -> None:
        self.requested: tuple[str, ...] = ()

    def fetch(self, symbols, *, as_of):
        assert as_of == NOW
        self.requested = tuple(symbols)
        return OratsBatchResult(
            tuple(_chain(symbol) for symbol in self.requested),
            (),
        )


class _Body:
    def __init__(self, value: bytes):
        self.value = value

    def read(self) -> bytes:
        return self.value


class _S3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_object(self, *, Bucket, Key):
        assert Bucket == "unit-bucket"
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, ServerSideEncryption):
        assert Bucket == "unit-bucket"
        assert ContentType
        assert ServerSideEncryption == "AES256"
        self.objects[Key] = bytes(Body)
        return {}


def test_orats_request_limit_never_truncates_canonical_prospect_universe(tmp_path):
    symbols = tuple(f"S{i:02d}" for i in range(50))
    previous = _write_csv(
        tmp_path / "OVTLYR_2026-08-23.csv",
        [
            f"{symbol},Hold,2026-08-23,Technology,Semiconductors,Up,Rising,Yes,100,2500000"
            for symbol in symbols
        ],
    )
    current = _write_csv(
        tmp_path / "OVTLYR_2026-08-24.csv",
        [
            f"{symbol},Buy,2026-08-24,Technology,Semiconductors,Up,Accelerating,Yes,101,2500000"
            for symbol in symbols
        ],
    )
    source = _RecordingOratsSource()

    result = build_stock_primary_shortlist(
        previous,
        current,
        as_of=NOW,
        orats_source=source,
        request_limit=20,
        company_symbols=frozenset(symbols),
    )

    assert len(source.requested) == 20
    assert len(result.items) == 50
    assert result.summary["actionable_ranked_count"] == 50
    assert result.summary["orats_request_limit"] == 20
    assert result.summary["orats_requests"] == 20
    assert {item.symbol for item in result.items} == set(symbols)
    assert sum(item.orats_status == "NOT_REQUESTED" for item in result.items) == 30
    assert all(
        item.orats_reason == "RESEARCH_API_LIMIT_STOCK_RETAINED"
        for item in result.items
        if item.orats_status == "NOT_REQUESTED"
    )

    outputs = write_research_shortlist_outputs(tmp_path / "shortlist", result)
    shortlist_bytes = outputs["shortlist_json"].read_bytes()
    classifications_bytes = outputs["classifications_json"].read_bytes()
    published_rows = json.loads(shortlist_bytes)
    assert len(published_rows) == 50
    assert [row["rank"] for row in published_rows] == list(range(1, 51))
    assert {row["symbol"] for row in published_rows} == set(symbols)

    s3 = _S3()
    s3.objects["ovtlyr/shortlist/latest/shortlist.json"] = shortlist_bytes
    s3.objects["ovtlyr/shortlist/latest/classifications.json"] = classifications_bytes
    s3.objects["daily-alpha/outputs/latest/newsletter.html"] = (
        b"<!doctype html><html><body><main>"
        b"<section>Existing governed research</section></main></body></html>"
    )
    publisher = AwsProspectStagingRuntimePublisher(s3_client=s3, bucket="unit-bucket")

    prepared = publisher.prepare(
        history_prefix="daily-alpha/outputs/history/2026-08-24/full-universe-proof",
        as_of=NOW,
    )

    assert prepared.board.total_qualifying == 50
    assert len(prepared.board.top_picks) == 3
    assert len(prepared.board.additional_opportunities) == 47
    assert {item.symbol for item in prepared.board.opportunities} == set(symbols)
    assert all(
        item.evidence_lineage == (prepared.board.source_revision,)
        for item in prepared.board.opportunities
    )
    assert "shortlist=" in prepared.board.source_revision
    assert "classifications=" in prepared.board.source_revision

    first = prepared.board.opportunities[0]
    assert first.thesis
    assert first.industry == "Semiconductors"
    assert first.theme == "Semiconductors"
    assert first.price == 101.0
    assert first.average_volume == 2_500_000.0
    assert first.average_daily_dollar_volume == 252_500_000.0
    assert first.instrument_selected == "OPTION"
    assert first.invalidation == ""

    api_payload = json.loads(s3.objects["daily-alpha/outputs/latest/prospect_api.json"])
    assert api_payload["total_qualifying"] == 50
    assert len(api_payload["complete_qualifying"]) == 50
    assert api_payload["complete_qualifying"][0]["evidence_lineage"] == [
        prepared.board.source_revision
    ]
    assert api_payload["trading_authorized"] is False
    assert api_payload["live_trading_enabled"] is False
