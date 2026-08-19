import io
import json
from datetime import UTC, datetime

import pytest

from daily_alpha.staging_reporting import AwsStagingReportPublisher, StagingReportError

NOW = datetime(2026, 8, 19, 13, 30, tzinfo=UTC)


class _S3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.puts = {}

    def get_object(self, *, Bucket, Key):
        assert Bucket == "bucket"
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, ServerSideEncryption):
        assert Bucket == "bucket"
        assert ServerSideEncryption == "AES256"
        self.puts[Key] = (bytes(Body), ContentType)
        return {}


class _Dynamo:
    def scan(self, **kwargs):
        assert kwargs["TableName"] == "table"
        return {"Items": []}


def _objects():
    prefix = "ovtlyr/shortlist/latest"
    classifications = [
        {
            "symbol": "NFLX",
            "status": "ACTIVE_BUY",
            "display_label": "ACTIVE BUY",
            "signal": "BUY",
            "previous_signal": "BUY",
            "signal_date": "2026-08-10",
            "sector": "Communication Services",
            "industry": "Entertainment",
            "trend": "UP",
            "momentum": "RISING",
            "optionable": True,
            "reason": "BUY remains active without a higher-priority setup",
        }
    ]
    return {
        f"{prefix}/shortlist.json": b"[]",
        f"{prefix}/summary.json": json.dumps({"qualified_option_count": 0}).encode(),
        f"{prefix}/sector_rotation.json": b"[]",
        f"{prefix}/classifications.json": json.dumps(classifications).encode(),
        f"{prefix}/shortlist.csv": b"rank,symbol\n",
    }


def _watchlist(tmp_path, *, valid=True):
    path = tmp_path / "manual_watchlist.json"
    if valid:
        path.write_text(
            json.dumps(
                {
                    "schema_version": "2026-08-19-v1",
                    "entries": [
                        {
                            "symbol": "NFLX",
                            "label": "Netflix",
                            "reason": "USER_PINNED",
                            "enabled": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    else:
        path.write_text("{not-json", encoding="utf-8")
    return path


def test_staging_newsletter_publishes_pinned_nflx_outside_shortlist(tmp_path):
    s3 = _S3(_objects())
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=_Dynamo(),
        bucket="bucket",
        table_name="table",
        account_id="paper-staging",
        manual_watchlist_path=str(_watchlist(tmp_path)),
    )

    result = publisher.publish(session="MORNING", now=NOW, run_id="watch-run")

    newsletter_key = "daily-alpha/outputs/latest/newsletter.html"
    newsletter = s3.puts[newsletter_key][0].decode("utf-8")
    assert "Persistent Manual Watch" in newsletter
    assert "NFLX" in newsletter
    assert "ACTIVE_BUY" in newsletter
    assert "Pinned visibility is not a trade signal" in newsletter

    watch_key = "daily-alpha/outputs/latest/manual_watchlist.json"
    watch_rows = json.loads(s3.puts[watch_key][0])
    assert watch_rows[0]["symbol"] == "NFLX"
    assert watch_rows[0]["orats_status"] == "NOT_ENRICHED_THIS_RUN"
    assert watch_rows[0]["trading_authorized"] is False
    assert watch_rows[0]["live_trading_enabled"] is False

    manifest = result["manifest"]
    assert manifest["research_candidate_count"] == 0
    assert manifest["manual_watch_count"] == 1
    assert manifest["manual_watch_symbols"] == ["NFLX"]
    assert manifest["manual_watch_data_error_count"] == 0
    assert "MANUAL_WATCH" in manifest["newsletter_sections"]
    assert manifest["trading_authorized"] is False
    assert manifest["live_trading_enabled"] is False


def test_manual_watch_missing_classification_stays_visible_as_data_error(tmp_path):
    objects = _objects()
    objects["ovtlyr/shortlist/latest/classifications.json"] = b"[]"
    s3 = _S3(objects)
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=_Dynamo(),
        bucket="bucket",
        table_name="table",
        account_id="paper-staging",
        manual_watchlist_path=str(_watchlist(tmp_path)),
    )

    result = publisher.publish(now=NOW, run_id="missing-classification")

    rows = json.loads(s3.puts["daily-alpha/outputs/latest/manual_watchlist.json"][0])
    assert rows[0]["symbol"] == "NFLX"
    assert rows[0]["data_status"] == "DATA_ERROR"
    assert rows[0]["status_reason"] == "CURRENT_CLASSIFICATION_MISSING"
    assert result["manifest"]["manual_watch_data_error_count"] == 1


def test_malformed_manual_watchlist_fails_report_before_publication(tmp_path):
    s3 = _S3(_objects())
    publisher = AwsStagingReportPublisher(
        s3_client=s3,
        dynamodb_client=_Dynamo(),
        bucket="bucket",
        table_name="table",
        account_id="paper-staging",
        manual_watchlist_path=str(_watchlist(tmp_path, valid=False)),
    )

    with pytest.raises(StagingReportError, match="MANUAL_WATCHLIST_INVALID"):
        publisher.publish(now=NOW, run_id="bad-watchlist")

    assert s3.puts == {}
