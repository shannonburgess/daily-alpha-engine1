import json
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import staging_lambda_handlers.data_feed_ingest as ingest


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


def test_current_window_remains_default_and_rejects_hidden_date_overrides():
    now = datetime(2026, 8, 23, 23, 0, tzinfo=UTC)
    mode, start_date, end_date = ingest._capture_window({}, now)

    assert mode == "CURRENT_WINDOW"
    assert start_date.isoformat() == "2026-08-16"
    assert end_date.isoformat() == "2026-08-23"

    for event in (
        {"start_date": "2026-08-01"},
        {"end_date": "2026-08-02"},
        {
            "capture_mode": "CURRENT_WINDOW",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
        },
    ):
        try:
            ingest._capture_window(event, now)
        except ingest.DataFeedIngestionError as exc:
            assert str(exc) == "CURRENT_WINDOW_DATE_OVERRIDE_NOT_ALLOWED"
        else:
            raise AssertionError("current canary window cannot be silently overridden")


def test_historical_backfill_window_is_explicit_bounded_and_never_future():
    now = datetime(2026, 8, 23, 23, 0, tzinfo=UTC)
    mode, start_date, end_date = ingest._capture_window(
        {
            "capture_mode": "historical_backfill",
            "start_date": "2026-08-01",
            "end_date": "2026-08-20",
        },
        now,
    )
    assert mode == "HISTORICAL_BACKFILL"
    assert start_date.isoformat() == "2026-08-01"
    assert end_date.isoformat() == "2026-08-20"

    invalid = [
        (
            {
                "capture_mode": "HISTORICAL_BACKFILL",
                "start_date": "2026-08-20",
                "end_date": "2026-08-01",
            },
            "BACKFILL_DATE_RANGE_INVALID",
        ),
        (
            {
                "capture_mode": "HISTORICAL_BACKFILL",
                "start_date": "2026-08-01",
                "end_date": "2026-08-24",
            },
            "BACKFILL_END_DATE_IN_FUTURE",
        ),
        (
            {
                "capture_mode": "HISTORICAL_BACKFILL",
                "start_date": "2026-07-01",
                "end_date": "2026-08-01",
            },
            "BACKFILL_DATE_RANGE_TOO_LARGE",
        ),
    ]
    for event, code in invalid:
        try:
            ingest._capture_window(event, now)
        except ingest.DataFeedIngestionError as exc:
            assert str(exc) == code
        else:
            raise AssertionError(f"historical backfill must fail closed: {code}")


def test_historical_request_specs_use_only_requested_bounded_window():
    now = datetime(2026, 8, 23, 23, 0, tzinfo=UTC)
    _, start_date, end_date = ingest._capture_window(
        {
            "capture_mode": "HISTORICAL_BACKFILL",
            "start_date": "2026-08-01",
            "end_date": "2026-08-20",
        },
        now,
    )

    massive_url, _ = ingest._request_spec(
        "massive",
        "DINO",
        "secret",
        now,
        capture_mode="HISTORICAL_BACKFILL",
        start_date=start_date,
        end_date=end_date,
    )
    assert "/2026-08-01/2026-08-20?" in massive_url
    assert "limit=50" in massive_url

    tiingo_url, _ = ingest._request_spec(
        "tiingo",
        "DINO",
        "secret",
        now,
        capture_mode="HISTORICAL_BACKFILL",
        start_date=start_date,
        end_date=end_date,
    )
    tiingo_query = parse_qs(urlparse(tiingo_url).query)
    assert tiingo_query["startDate"] == ["2026-08-01"]
    assert tiingo_query["endDate"] == ["2026-08-20"]

    fred_url, _ = ingest._request_spec(
        "fred",
        "DGS10",
        "secret",
        now,
        capture_mode="HISTORICAL_BACKFILL",
        start_date=start_date,
        end_date=end_date,
    )
    fred_query = parse_qs(urlparse(fred_url).query)
    assert fred_query["observation_start"] == ["2026-08-01"]
    assert fred_query["observation_end"] == ["2026-08-20"]
    assert fred_query["sort_order"] == ["asc"]


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
    assert result["capture_mode"] == "CURRENT_WINDOW"
    assert result["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert result["historical_known_at_backdating_authorized"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
    assert len(s3.objects) == 2
    raw_key = next(key for key in s3.objects if "/raw/" in key)
    receipt_key = next(key for key in s3.objects if "/receipts/" in key)
    assert raw_key.startswith("data-feeds/staging/massive/raw/")
    assert receipt_key.startswith("data-feeds/staging/massive/receipts/")
    raw = s3.objects[raw_key]
    assert raw["Metadata"]["capture-mode"] == "CURRENT_WINDOW"
    assert raw["Metadata"]["known-at-basis"] == "CAPTURED_AT_ONLY"
    assert raw["Metadata"]["historical-known-at-backdating-authorized"] == "false"
    assert raw["Metadata"]["trading-authorized"] == "false"
    assert raw["Metadata"]["live-trading-enabled"] == "false"
    receipt = json.loads(s3.objects[receipt_key]["Body"])
    assert receipt["capture_mode"] == "CURRENT_WINDOW"
    assert receipt["requested_start_date"] == "2026-08-16"
    assert receipt["requested_end_date"] == "2026-08-23"
    assert receipt["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert receipt["historical_known_at_backdating_authorized"] is False
    assert receipt["trading_authorized"] is False
    assert receipt["live_trading_enabled"] is False


def test_lambda_historical_backfill_receipt_cannot_claim_historical_known_at(monkeypatch):
    s3 = _S3()
    seen_urls: list[str] = []
    monkeypatch.setenv("RAW_EVIDENCE_BUCKET", "unit-bucket")
    monkeypatch.setattr(ingest, "_now", lambda: datetime(2026, 8, 23, 23, 0, tzinfo=UTC))
    monkeypatch.setattr(ingest, "_load_secret", lambda provider: "secret")

    def _fake_http(url, headers, timeout_seconds=15):
        del headers, timeout_seconds
        seen_urls.append(url)
        return b'{"historical":true}', "application/json"

    monkeypatch.setattr(ingest, "_http_get", _fake_http)
    monkeypatch.setattr(ingest, "_aws_client", lambda service: s3 if service == "s3" else None)

    result = ingest.lambda_handler(
        {
            "provider": "massive",
            "targets": ["DINO"],
            "capture_mode": "HISTORICAL_BACKFILL",
            "start_date": "2026-08-01",
            "end_date": "2026-08-20",
        },
        SimpleNamespace(aws_request_id="backfill-1"),
    )

    assert result["capture_mode"] == "HISTORICAL_BACKFILL"
    assert result["requested_start_date"] == "2026-08-01"
    assert result["requested_end_date"] == "2026-08-20"
    assert result["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert result["historical_known_at_backdating_authorized"] is False
    assert len(seen_urls) == 1
    assert "/2026-08-01/2026-08-20?" in seen_urls[0]

    receipt_key = next(key for key in s3.objects if "/receipts/" in key)
    receipt = json.loads(s3.objects[receipt_key]["Body"])
    assert receipt["captured_at"] == "2026-08-23T23:00:00+00:00"
    assert receipt["capture_mode"] == "HISTORICAL_BACKFILL"
    assert receipt["requested_start_date"] == "2026-08-01"
    assert receipt["requested_end_date"] == "2026-08-20"
    assert receipt["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert receipt["historical_known_at_backdating_authorized"] is False
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