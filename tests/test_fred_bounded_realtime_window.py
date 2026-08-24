from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import staging_lambda_handlers.data_feed_ingest as ingest


def test_fred_historical_initial_release_bounds_realtime_window_to_requested_start():
    now = datetime(2026, 8, 24, 11, 0, tzinfo=UTC)
    _, start_date, end_date = ingest._capture_window(
        {
            "capture_mode": "HISTORICAL_BACKFILL",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        },
        now,
    )

    url, _ = ingest._request_spec(
        "fred",
        "DFF",
        "secret",
        now,
        capture_mode="HISTORICAL_BACKFILL",
        start_date=start_date,
        end_date=end_date,
    )
    query = parse_qs(urlparse(url).query)

    assert query["observation_start"] == ["2026-07-01"]
    assert query["observation_end"] == ["2026-07-31"]
    assert query["realtime_start"] == ["2026-07-01"]
    assert query["realtime_end"] == ["2026-08-24"]
    assert query["output_type"] == ["4"]
    assert query["sort_order"] == ["asc"]
    assert query["limit"] == ["1000"]


def test_fred_historical_request_never_reopens_centuries_wide_realtime_range():
    now = datetime(2026, 8, 24, 11, 0, tzinfo=UTC)
    _, start_date, end_date = ingest._capture_window(
        {
            "capture_mode": "HISTORICAL_BACKFILL",
            "start_date": "2026-08-01",
            "end_date": "2026-08-20",
        },
        now,
    )

    url, _ = ingest._request_spec(
        "fred",
        "DGS10",
        "secret",
        now,
        capture_mode="HISTORICAL_BACKFILL",
        start_date=start_date,
        end_date=end_date,
    )
    query = parse_qs(urlparse(url).query)

    assert query["realtime_start"] == [start_date.isoformat()]
    assert query["realtime_start"] != ["1776-07-04"]
