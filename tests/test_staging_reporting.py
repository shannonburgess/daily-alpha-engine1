import io
import json
from datetime import UTC, datetime

from daily_alpha.staging_reporting import AwsStagingReportPublisher


NOW = datetime(2026, 8, 17, 13, 5, tzinfo=UTC)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        assert Bucket == "unit-bucket"
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, ServerSideEncryption):
        assert Bucket == "unit-bucket"
        assert ContentType
        assert ServerSideEncryption == "AES256"
        self.objects[Key] = bytes(Body)
        return {}


class FakeDynamo:
    def scan(self, **kwargs):
        assert kwargs["TableName"] == "unit-ledger"
        return {
            "Items": [
                {
                    "pk": {"S": "ACCOUNT#paper-unit#POSITION#OPTION#AAPL"},
                    "sk": {"S": "OPEN"},
                    "signal_id": {"S": "sig-entry"},
                    "symbol": {"S": "AAPL"},
                    "instrument": {"S": "OPTION"},
                    "state": {"S": "OPEN"},
                    "trade_json": {"S": '{"quantity":2,"entry_price":2.2}'},
                },
                {
                    "pk": {"S": "ACCOUNT#paper-unit#PINE_EVENT#sig-entry"},
                    "sk": {"S": "RECEIVED"},
                    "action": {"S": "ENTRY_LONG"},
                    "disposition": {"S": "EXECUTED_PAPER"},
                    "reason": {"S": "PAPER_POSITION_OPENED"},
                },
            ]
        }


def seed_s3(client):
    shortlist = [
        {
            "rank": 1,
            "symbol": "AAPL",
            "ovtlyr_status": "LEADER",
            "display_label": "🚀 LEADER",
            "classification_reason": "Leadership and momentum remain strong.",
            "score": 92.5,
            "sector": "Technology",
            "orats_status": "ENRICHED",
            "orats_reason": "QUALIFIED_OPTION_FOUND",
            "selected_expiration": "2026-10-16",
            "selected_strike": 250.0,
            "selected_option_type": "CALL",
            "smart_money_bonus": 5.0,
            "trump_policy_bonus": 0.0,
        },
        {
            "rank": 2,
            "symbol": "XYZ",
            "ovtlyr_status": "ENTRY_WATCH",
            "display_label": "🎯 ENTRY WATCH",
            "classification_reason": "Required ORATS data did not pass validation.",
            "score": 70.0,
            "sector": "Industrials",
            "orats_status": "DATA_ERROR",
            "orats_reason": "ORATS_DATA_STALE",
            "selected_expiration": "",
            "selected_strike": 0.0,
            "selected_option_type": "",
            "smart_money_bonus": 0.0,
            "trump_policy_bonus": 0.0,
        },
    ]
    summary = {"qualified_option_count": 1}
    sector = [
        {"sector": "Technology", "new_buys": 3, "leaders": 5, "net_score": 8},
        {"sector": "Industrials", "new_buys": 1, "leaders": 2, "net_score": 3},
    ]
    client.objects["ovtlyr/shortlist/latest/shortlist.json"] = json.dumps(shortlist).encode()
    client.objects["ovtlyr/shortlist/latest/summary.json"] = json.dumps(summary).encode()
    client.objects["ovtlyr/shortlist/latest/sector_rotation.json"] = json.dumps(sector).encode()
    client.objects["ovtlyr/shortlist/latest/shortlist.csv"] = b"rank,symbol\n1,AAPL\n2,XYZ\n"


def test_publish_writes_readable_newsletter_csvs_and_manifest():
    s3 = FakeS3()
    seed_s3(s3)
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=FakeDynamo(),
        bucket="unit-bucket",
        table_name="unit-ledger",
        account_id="paper-unit",
    )

    result = publisher.publish(session="MORNING", now=NOW, run_id="run-123")

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["manifest"]["research_candidate_count"] == 2
    assert result["manifest"]["open_paper_position_count"] == 1
    assert result["manifest"]["newsletter_quality_passed"] is True
    assert result["live_trading_enabled"] is False

    latest = "daily-alpha/outputs/latest/"
    html = s3.objects[latest + "newsletter.html"].decode()
    ledger_csv = s3.objects[latest + "paper_ledger.csv"].decode()
    sector_csv = s3.objects[latest + "sector_rotation.csv"].decode()
    manifest = json.loads(s3.objects[latest + "report_manifest.json"].decode())

    assert "Daily Alpha &amp; Risk" in html
    assert "AAPL" in html
    assert "XYZ" in html
    assert "DATA ERROR" in html
    assert "ACCOUNT#paper-unit#POSITION#OPTION#AAPL" in ledger_csv
    assert "Technology" in sector_csv
    assert manifest["session"] == "MORNING"
    assert manifest["live_trading_enabled"] is False


def test_publish_keeps_history_and_latest_copies():
    s3 = FakeS3()
    seed_s3(s3)
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=FakeDynamo(),
        bucket="unit-bucket",
        table_name="unit-ledger",
        account_id="paper-unit",
    )

    result = publisher.publish(session="POST_MARKET", now=NOW, run_id="run-456")

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
