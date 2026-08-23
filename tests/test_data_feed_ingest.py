import json
from datetime import UTC, datetime
from types import SimpleNamespace

import lambda_handlers.data_feed_ingest as ingest


class _Secrets:
    def __init__(self, value):
        self.value = value

    def get_secret_value(self, **kwargs):
        assert kwargs["VersionStage"] == "AWSCURRENT"
        return {"SecretString": self.value}


class _S3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        assert kwargs["ServerSideEncryption"] == "AES256"
        assert kwargs["IfNoneMatch"] == "*"
        self.objects[kwargs["Key"]] = kwargs
        return {}


def test_secret_parser_accepts_raw_and_single_json_value():
    assert ingest._safe_secret_value("abc") == "abc"
    assert ingest._safe_secret_value('{"api_key":"abc"}') == "abc"
    assert ingest._safe_secret_value('{"token":"abc","api_key":"abc"}') == "abc"


def test_secret_parser_rejects_ambiguous_json_values():
    try:
        ingest._safe_secret_value('{"token":"abc","api_key":"def"}')
    except ingest.DataFeedIngestionError as exc:
        assert str(exc) == "SECRET_JSON_KEY_AMBIGUOUS_OR_MISSING"
    else:
        raise AssertionError("ambiguous secret must fail closed")


def test_request_specs_keep_massive_and_tiingo_keys_out_of_url():
    now = datetime(2026, 8, 23, 23, 0, tzinfo=UTC)
    massive_url, massive_headers = ingest._request_spec("massive", "DINO", "secret", now)
    assert "secret" not in massive_url
    assert massive_headers["Authorization"] == "Bearer secret"
    tiingo_url, tiingo_headers = ingest._request_spec("tiingo", "DINO", "secret", now)
    assert "secret" not in tiingo_url
    assert tiingo_headers["Authorization"] == "Token secret"
    fred_url, _ = ingest._request_spec("fred", "DGS10", "secret", now)
    assert "api_key=secret" in fred_url


def test_lambda_archives_raw_and_receipt_without_execution_authority(monkeypatch):
    s3 = _S3()
    monkeypatch.setenv("RAW_EVIDENCE_BUCKET", "unit-bucket")
    monkeypatch.setattr(ingest, "_now", lambda: datetime(2026, 8, 23, 23, 0, tzinfo=UTC))
    monkeypatch.setattr(ingest, "_load_secret", lambda provider: "secret")
    monkeypatch.setattr(ingest, "_http_get", lambda *args, **kwargs: (b'{"ok":true}', "application/json"))
    monkeypatch.setattr(ingest, "_aws_client", lambda service: s3 if service == "s3" else None)

    result = ingest.lambda_handler(
        {"provider": "massive", "targets": ["DINO"]},
        SimpleNamespace(aws_request_id="req-1"),
    )

    assert result["ok"] is True
    assert result["provider"] == "MASSIVE"
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert len(s3.objects) == 2
    raw_key = next(key for key in s3.objects if "/raw/" in key)
    receipt_key = next(key for key in s3.objects if "/receipts/" in key)
    assert raw_key.startswith("data-feeds/staging/massive/raw/")
    assert receipt_key.startswith("data-feeds/staging/massive/receipts/")
    raw = s3.objects[raw_key]
    assert raw["Metadata"]["trading-authorized"] == "false"
    assert raw["Metadata"]["live-trading-enabled"] == "false"
    receipt = json.loads(s3.objects[receipt_key]["Body"])
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False


def test_targets_fail_closed_on_duplicates_or_invalid_values():
    for event, code in [
        ({"targets": ["SPY", "SPY"]}, "TARGETS_MUST_BE_UNIQUE"),
        ({"targets": ["SPY;DROP"]}, "TARGET_INVALID"),
    ]:
        try:
            ingest._targets("massive", event)
        except ingest.DataFeedIngestionError as exc:
            assert str(exc) == code
        else:
            raise AssertionError("invalid targets must fail closed")


def test_no_provider_can_be_inferred_or_execution_enabled(monkeypatch):
    monkeypatch.setenv("RAW_EVIDENCE_BUCKET", "unit-bucket")
    try:
        ingest.lambda_handler({"trading_authorized": True}, SimpleNamespace(aws_request_id="x"))
    except ingest.DataFeedIngestionError as exc:
        assert str(exc) == "PROVIDER_UNSUPPORTED"
    else:
        raise AssertionError("provider must be explicit")
