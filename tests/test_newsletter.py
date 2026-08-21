from datetime import UTC, datetime

from daily_alpha.models import InstrumentSelected
from daily_alpha.newsletter import NewsletterRenderer
from daily_alpha.research_report import (
    DailyResearchPacket,
    ResearchCandidate,
    ResearchDisposition,
)
from daily_alpha.smart_money import (
    CongressionalAccumulation,
    InstitutionalAccumulation,
    build_smart_money_snapshot,
)
from daily_alpha.staging_reporting import AwsStagingReportPublisher


def candidate(symbol, disposition, instrument=InstrumentSelected.STOCK):
    return ResearchCandidate(
        symbol=symbol,
        disposition=disposition,
        instrument=instrument,
        signal_label="ENTRY_WATCH",
        thesis="Trend < momentum & risk evidence.",
        reasons=("PINE_CONFIRMED", "RISK_APPROVED"),
        risk_status="APPROVED"
        if disposition == ResearchDisposition.PAPER_CANDIDATE
        else "WATCH",
        data_status="PASS",
        sector="TECHNOLOGY",
        option_contract="AAPL 2026-10-16 250C"
        if instrument == InstrumentSelected.OPTION
        else None,
        user_directed_option=instrument == InstrumentSelected.OPTION,
    )


def smart_money_snapshot():
    congress = CongressionalAccumulation(
        rank=1,
        symbol="IBM",
        issuer="IBM",
        score=49.83,
        unique_politicians=2,
        purchase_count=2,
        estimated_purchase_value=50000.0,
        latest_transaction_date="2026-08-01",
        latest_disclosure_date="2026-08-12",
        average_disclosure_lag_days=11.0,
        politicians=("Member A", "Member B"),
    )
    institution = InstitutionalAccumulation(
        rank=1,
        symbol="MPWR",
        cusip="TICKER:MPWR",
        issuer="Monolithic Power Systems",
        score=100.0,
        managers_increasing=13,
        new_manager_positions=7,
        shares_added=100000.0,
        estimated_value_added=50000000.0,
        period_of_report="2026-06-30",
        top_managers=("Fund A", "Fund B"),
    )
    return build_smart_money_snapshot(
        generated_at=datetime(2026, 8, 17, 12, 30, tzinfo=UTC),
        congressional=(congress,),
        institutional=(institution,),
        coverage={"provider": "TEST"},
    )


def packet(*, include_smart_money=False):
    return DailyResearchPacket(
        "2026-08-17",
        "run-1",
        "daily-alpha-v2",
        "2026-08-17T12:35:00+00:00",
        "RISK_ON",
        (
            candidate("AAPL", ResearchDisposition.PAPER_CANDIDATE),
            candidate("MSFT", ResearchDisposition.WATCHLIST),
            candidate("TSLA", ResearchDisposition.NO_TRADE),
        ),
        smart_money=smart_money_snapshot() if include_smart_money else None,
    )


def test_renderer_includes_all_candidate_sections_and_disclosures():
    result = NewsletterRenderer().render(packet())
    assert result.candidate_count == 3
    assert result.sections == (
        "PAPER_CANDIDATE",
        "WATCHLIST",
        "NO_TRADE",
    )
    assert all(symbol in result.html for symbol in ("AAPL", "MSFT", "TSLA"))
    assert "No live order execution is authorized." in result.html
    assert "Options are user-directed" in result.html
    assert result.quality_passed is True


def test_renderer_includes_smart_money_confirmation_section():
    result = NewsletterRenderer().render(packet(include_smart_money=True))
    assert result.sections[0] == "SMART_MONEY"
    assert "Smart Money Accumulation" in result.html
    assert "Congressional accumulation" in result.html
    assert "Institutional accumulation" in result.html
    assert "IBM" in result.html
    assert "MPWR" in result.html
    assert "not trade-timing signals" in result.html
    assert result.quality_passed is True


def test_renderer_only_shows_options_for_explicit_user_directed_contract():
    explicit = candidate(
        "AAPL",
        ResearchDisposition.WATCHLIST,
        InstrumentSelected.OPTION,
    )
    base = packet()
    result = NewsletterRenderer().render(
        DailyResearchPacket(
            base.report_date,
            base.run_id,
            base.methodology_version,
            base.generated_at,
            base.market_regime,
            (explicit,),
        )
    )
    assert result.sections[0] == "USER_DIRECTED_OPTIONS"
    assert "Explicitly Authorized Option Orders" in result.html
    assert "broker-chain" in result.html.lower()
    assert "AAPL 2026-10-16 250C" in result.html
    assert "unusual options" not in result.html.lower()


def test_renderer_escapes_untrusted_candidate_text():
    result = NewsletterRenderer().render(packet())
    assert "Trend &lt; momentum &amp; risk evidence." in result.html
    assert "Trend < momentum" not in result.html


def test_layout_uses_readable_fonts_and_no_fixed_height_boxes():
    html = NewsletterRenderer().render(packet(include_smart_money=True)).html
    assert "font: 12pt" in html
    assert "font-size: 10.5pt" in html
    assert "height:" not in html
    assert "max-height:" not in html


def test_empty_packet_gets_explicit_no_candidate_message():
    empty = DailyResearchPacket(
        "2026-08-17",
        "run-empty",
        "v2",
        "2026-08-17T12:35:00+00:00",
        "NEUTRAL",
        (),
    )
    result = NewsletterRenderer().render(empty)
    assert "No publishable candidates" in result.html
    assert result.quality_passed is True


class _Body:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        assert Bucket == "unit-bucket"
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, ServerSideEncryption):
        assert Bucket == "unit-bucket"
        assert ContentType
        assert ServerSideEncryption == "AES256"
        self.objects[Key] = bytes(Body)
        return {}


class _FakeDynamo:
    def scan(self, **kwargs):
        assert kwargs["TableName"] == "unit-ledger"
        return {
            "Items": [
                {
                    "pk": {"S": "ACCOUNT#paper-unit#POSITION#STOCK#AAPL"},
                    "sk": {"S": "OPEN"},
                    "signal_id": {"S": "sig-entry"},
                    "symbol": {"S": "AAPL"},
                    "instrument": {"S": "STOCK"},
                    "state": {"S": "OPEN"},
                    "trade_json": {"S": '{"quantity":20,"entry_price":220.0}'},
                },
                {
                    "pk": {"S": "ACCOUNT#paper-unit#PINE_EVENT#sig-entry"},
                    "sk": {"S": "RECEIVED"},
                    "action": {"S": "ENTRY_LONG"},
                    "disposition": {"S": "EXECUTED_PAPER"},
                    "reason": {"S": "PAPER_STOCK_POSITION_OPENED"},
                },
            ]
        }


def _seed_staging_s3(client):
    client.objects["ovtlyr/shortlist/latest/shortlist.json"] = b'''[
      {
        "rank": 1,
        "symbol": "AAPL",
        "ovtlyr_status": "LEADER",
        "display_label": "LEADER",
        "classification_reason": "Leadership and momentum remain strong.",
        "score": 92.5,
        "sector": "Technology",
        "options_mode": "USER_DIRECTED_BROKER_CHAIN",
        "smart_money_bonus": 5.0,
        "trump_policy_bonus": 0.0
      },
      {
        "rank": 2,
        "symbol": "XYZ",
        "ovtlyr_status": "ENTRY_WATCH",
        "display_label": "ENTRY WATCH",
        "classification_reason": "Stock setup remains under observation.",
        "score": 70.0,
        "sector": "Industrials",
        "options_mode": "USER_DIRECTED_BROKER_CHAIN",
        "smart_money_bonus": 0.0,
        "trump_policy_bonus": 0.0
      }
    ]'''
    client.objects["ovtlyr/shortlist/latest/summary.json"] = b'{"options_mode":"USER_DIRECTED_BROKER_CHAIN"}'
    client.objects["ovtlyr/shortlist/latest/sector_rotation.json"] = b'''[
      {"sector":"Technology","new_buys":3,"leaders":5,"net_score":8},
      {"sector":"Industrials","new_buys":1,"leaders":2,"net_score":3}
    ]'''
    client.objects["ovtlyr/shortlist/latest/shortlist.csv"] = b"rank,symbol\n1,AAPL\n2,XYZ\n"
    client.objects["ovtlyr/shortlist/latest/classifications.json"] = b'''[
      {"symbol":"AAPL","status":"LEADER","display_label":"LEADER","reason":"Sustained leadership."},
      {"symbol":"NVDA","status":"EMERGING","display_label":"EMERGING","reason":"Momentum accelerating."},
      {"symbol":"META","status":"NEW_BUY","display_label":"NEW BUY","reason":"New BUY transition."},
      {"symbol":"MSFT","status":"ENTRY_WATCH","display_label":"ENTRY WATCH","reason":"Approaching entry."},
      {"symbol":"AMZN","status":"RE_ENTRY","display_label":"RE-ENTRY","reason":"Fresh re-entry setup."},
      {"symbol":"TSLA","status":"DETERIORATING","display_label":"DETERIORATING","reason":"Momentum weakening."},
      {"symbol":"XYZ","status":"REMOVED","display_label":"REMOVED","reason":"No longer BUY."}
    ]'''


def test_staging_publisher_writes_newsletter_csvs_and_manifest():
    s3 = _FakeS3()
    _seed_staging_s3(s3)
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=_FakeDynamo(),
        bucket="unit-bucket",
        table_name="unit-ledger",
        account_id="paper-unit",
    )

    result = publisher.publish(
        session="MORNING",
        now=datetime(2026, 8, 17, 13, 5, tzinfo=UTC),
        run_id="run-123",
    )

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["manifest"]["research_candidate_count"] == 2
    assert result["manifest"]["open_paper_position_count"] == 1
    assert result["manifest"]["newsletter_quality_passed"] is True
    assert result["manifest"]["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"
    assert result["live_trading_enabled"] is False

    latest = "daily-alpha/outputs/latest/"
    html = s3.objects[latest + "newsletter.html"].decode()
    ledger_csv = s3.objects[latest + "paper_ledger.csv"].decode()
    sector_csv = s3.objects[latest + "sector_rotation.csv"].decode()
    manifest = s3.objects[latest + "report_manifest.json"].decode()

    assert "Daily Alpha &amp; Risk" in html
    assert "AAPL" in html
    assert "XYZ" in html
    assert "Complete OVTLYR Classification Universe" in html
    assert "New Buy (1)" in html
    assert "Emerging (1)" in html
    assert "Leaders (1)" in html
    assert "Entry Watch (1)" in html
    assert "Re-entry (1)" in html
    assert "Deteriorating (1)" in html
    assert "Removed (1)" in html
    assert "ACCOUNT#paper-unit#POSITION#STOCK#AAPL" in ledger_csv
    assert "Technology" in sector_csv
    assert '"session": "MORNING"' in manifest
    assert '"live_trading_enabled": false' in manifest


def test_staging_publisher_keeps_history_and_latest_copies():
    s3 = _FakeS3()
    _seed_staging_s3(s3)
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=_FakeDynamo(),
        bucket="unit-bucket",
        table_name="unit-ledger",
        account_id="paper-unit",
    )

    result = publisher.publish(
        session="POST_MARKET",
        now=datetime(2026, 8, 17, 13, 5, tzinfo=UTC),
        run_id="run-456",
    )

    assert result["history_prefix"].startswith(
        "daily-alpha/outputs/history/2026-08-17/post_market-"
    )
    for name in (
        "newsletter.html",
        "research_shortlist.csv",
        "paper_ledger.csv",
        "sector_rotation.csv",
        "report_manifest.json",
    ):
        assert f"daily-alpha/outputs/latest/{name}" in s3.objects
        assert f"{result['history_prefix']}/{name}" in s3.objects
