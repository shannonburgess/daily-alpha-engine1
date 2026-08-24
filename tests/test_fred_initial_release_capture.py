from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import staging_lambda_handlers.data_feed_ingest as ingest
from daily_alpha.fred_initial_release import parse_fred_initial_release_history


class _S3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}

    def put_object(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["ServerSideEncryption"] == "AES256"
        assert kwargs["IfNoneMatch"] == "*"
        self.objects[str(kwargs["Key"])] = kwargs
        return {}


def _fred_initial_release_body() -> bytes:
    return json.dumps(
        {
            "realtime_start": "1776-07-04",
            "realtime_end": "2026-08-24",
            "observation_start": "2026-07-01",
            "observation_end": "2026-07-31",
            "units": "lin",
            "output_type": 4,
            "file_type": "json",
            "order_by": "observation_date",
            "sort_order": "asc",
            "count": 2,
            "offset": 0,
            "limit": 1000,
            "observations": [
                {
                    "realtime_start": "2026-07-02",
                    "realtime_end": "9999-12-31",
                    "date": "2026-07-01",
                    "value": "4.33",
                },
                {
                    "realtime_start": "2026-07-03",
                    "realtime_end": "9999-12-31",
                    "date": "2026-07-02",
                    "value": "4.34",
                },
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_fred_historical_request_uses_provider_initial_release_contract() -> None:
    as_of = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    url, _ = ingest._request_spec(
        "fred",
        "DFF",
        "secret",
        as_of,
        capture_mode="HISTORICAL_BACKFILL",
        start_date=as_of.date().replace(month=7, day=1),
        end_date=as_of.date().replace(month=7, day=31),
    )

    query = parse_qs(urlparse(url).query)
    assert query["observation_start"] == ["2026-07-01"]
    assert query["observation_end"] == ["2026-07-31"]
    assert query["realtime_start"] == ["1776-07-04"]
    assert query["realtime_end"] == ["2026-08-24"]
    assert query["output_type"] == ["4"]
    assert query["sort_order"] == ["asc"]
    assert query["limit"] == ["1000"]


def test_fred_current_window_does_not_silently_switch_to_initial_release_history() -> None:
    as_of = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    url, _ = ingest._request_spec("fred", "DFF", "secret", as_of)
    query = parse_qs(urlparse(url).query)

    assert "output_type" not in query
    assert "realtime_start" not in query
    assert "realtime_end" not in query
    assert query["sort_order"] == ["desc"]
    assert query["limit"] == ["5"]


def test_fred_historical_lambda_capture_is_directly_parseable_as_pit_evidence(monkeypatch) -> None:
    s3 = _S3()
    seen_urls: list[str] = []
    captured_at = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    raw_body = _fred_initial_release_body()

    monkeypatch.setenv("RAW_EVIDENCE_BUCKET", "unit-bucket")
    monkeypatch.setattr(ingest, "_now", lambda: captured_at)
    monkeypatch.setattr(ingest, "_load_secret", lambda provider: "secret")

    def _fake_http(url: str, headers: dict[str, str], timeout_seconds: int = 15):
        del headers, timeout_seconds
        seen_urls.append(url)
        return raw_body, "application/json"

    monkeypatch.setattr(ingest, "_http_get", _fake_http)
    monkeypatch.setattr(
        ingest,
        "_aws_client",
        lambda service: s3 if service == "s3" else None,
    )

    result = ingest.lambda_handler(
        {
            "provider": "fred",
            "targets": ["DFF"],
            "capture_mode": "HISTORICAL_BACKFILL",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        },
        SimpleNamespace(aws_request_id="fred-pit-1"),
    )

    query = parse_qs(urlparse(seen_urls[0]).query)
    assert query["output_type"] == ["4"]
    assert query["realtime_end"] == ["2026-08-24"]
    assert result["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert result["historical_known_at_backdating_authorized"] is False
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False

    raw_key = next(key for key in s3.objects if "/raw/" in key)
    receipt_key = next(key for key in s3.objects if "/receipts/" in key)
    archived_raw = s3.objects[raw_key]["Body"]
    receipt = json.loads(s3.objects[receipt_key]["Body"])

    batch = parse_fred_initial_release_history(
        raw_body=archived_raw,
        receipt=receipt,
    )
    assert batch.output_type == 4
    assert tuple(item.value for item in batch.observations) == (4.33, 4.34)
    assert batch.observations[0].known_at < captured_at
    assert batch.research_only is True
    assert batch.promotion_authorized is False
    assert batch.paper_mutation_authorized is False
    assert batch.trading_authorized is False
    assert batch.live_trading_enabled is False


def test_smoke_contract_advertises_fred_initial_release_output_type() -> None:
    smoke = ingest._smoke_result()
    assert smoke["fred_historical_output_type"] == 4
    assert smoke["known_at_basis"] == "CAPTURED_AT_ONLY"
    assert smoke["historical_known_at_backdating_authorized"] is False
    assert smoke["trading_authorized"] is False
    assert smoke["live_trading_enabled"] is False
