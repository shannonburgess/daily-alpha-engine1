import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from daily_alpha.behavioral_change import BehavioralEntity
from daily_alpha.behavioral_youtube import YouTubeQuotaBudgetExceeded
from daily_alpha.behavioral_youtube_statistics import YouTubeVideoStatisticsFetcher

NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
ENTITY = BehavioralEntity(
    entity_id="NVDA",
    ticker="NVDA",
    version="2026-08-19-v1",
    company_name="NVIDIA",
)


class RecordingHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, *, timeout_seconds):
        assert timeout_seconds == 5.0
        self.urls.append(url)
        return json.dumps(self.responses.pop(0)).encode("utf-8")


def _stats_response(*rows):
    return {
        "items": [
            {
                "id": video_id,
                "statistics": {
                    "viewCount": str(views),
                    "likeCount": str(likes),
                    "commentCount": str(comments),
                },
            }
            for video_id, views, likes, comments in rows
        ]
    }


def test_statistics_fetcher_keeps_metric_units_separate_and_dedupes_ids():
    http = RecordingHttp(
        [
            _stats_response(
                ("v1", 1000, 100, 10),
                ("v2", 2000, 150, 20),
            )
        ]
    )
    fetcher = YouTubeVideoStatisticsFetcher(
        api_key="secret-key",
        max_statistics_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )

    rows, coverage = fetcher.collect(
        ENTITY,
        ("v1", "v2", "v2"),
        as_of=NOW,
    )

    assert {row.metric: row.raw_level for row in rows} == {
        "VIDEO_VIEW_TOTAL_SELECTED_SET": 3000.0,
        "VIDEO_LIKE_TOTAL_SELECTED_SET": 250.0,
        "VIDEO_COMMENT_TOTAL_SELECTED_SET": 30.0,
    }
    assert all(row.query_key == "ENTITY_UNIQUE_VIDEO_SET" for row in rows)
    assert coverage.requested_unique_video_ids == 2
    assert coverage.returned_video_ids == 2
    assert coverage.missing_video_ids == 0
    assert coverage.statistics_calls_used == 1
    assert fetcher.statistics_calls_used == 1
    assert "secret-key" not in rows[0].provenance
    assert json.loads(rows[0].provenance)["metric_units_kept_separate"] is True

    params = parse_qs(urlparse(http.urls[0]).query)
    assert params["part"] == ["statistics"]
    assert params["id"] == ["v1,v2"]
    assert params["maxResults"] == ["2"]
    assert params["key"] == ["secret-key"]


def test_same_day_statistics_cache_uses_no_additional_call():
    http = RecordingHttp([_stats_response(("v1", 1000, 100, 10))])
    fetcher = YouTubeVideoStatisticsFetcher(
        api_key="key",
        max_statistics_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )

    first, first_coverage = fetcher.collect(ENTITY, ("v1",), as_of=NOW)
    second, second_coverage = fetcher.collect(
        ENTITY,
        ("v1",),
        as_of=NOW.replace(hour=21),
    )

    assert first == second
    assert first_coverage.statistics_calls_used == 1
    assert second_coverage.statistics_calls_used == 0
    assert second_coverage.cache_hits == 1
    assert fetcher.statistics_calls_used == 1
    assert len(http.urls) == 1


def test_statistics_quota_fails_before_partial_fetch():
    http = RecordingHttp([])
    fetcher = YouTubeVideoStatisticsFetcher(
        api_key="key",
        max_statistics_calls_per_run=1,
        max_video_ids_per_call=2,
        timeout_seconds=5.0,
        http_get=http,
    )

    with pytest.raises(
        YouTubeQuotaBudgetExceeded,
        match="YOUTUBE_STATISTICS_CALL_BUDGET_EXCEEDED",
    ):
        fetcher.collect(ENTITY, ("v1", "v2", "v3"), as_of=NOW)

    assert fetcher.statistics_calls_used == 0
    assert http.urls == []


def test_missing_provider_statistics_are_visible_without_fabricated_video_rows():
    http = RecordingHttp([_stats_response(("v1", 1000, 100, 10))])
    fetcher = YouTubeVideoStatisticsFetcher(
        api_key="key",
        max_statistics_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )

    rows, coverage = fetcher.collect(ENTITY, ("v1", "missing"), as_of=NOW)

    assert coverage.requested_unique_video_ids == 2
    assert coverage.returned_video_ids == 1
    assert coverage.missing_video_ids == 1
    assert {row.metric: row.raw_level for row in rows}[
        "VIDEO_VIEW_TOTAL_SELECTED_SET"
    ] == 1000.0
    provenance = json.loads(rows[0].provenance)
    assert provenance["missing_video_ids"] == 1
    assert provenance["research_only"] is True
