import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from daily_alpha.behavioral_change import BehavioralEntity
from daily_alpha.behavioral_youtube import YouTubePublicSearchFetcher, YouTubeQuotaBudgetExceeded
from daily_alpha.behavioral_youtube_statistics import (
    YouTubeVideoStatisticsFetcher,
    collect_youtube_research_bundle,
)

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
    assert "maxResults" not in params
    assert params["key"] == ["secret-key"]


def test_research_bundle_reuses_exact_search_selection_without_second_search():
    search_http = RecordingHttp(
        [
            {
                "items": [
                    {"id": {"kind": "youtube#video", "videoId": "v1"}},
                    {"id": {"kind": "youtube#video", "videoId": "v2"}},
                ]
            },
            {
                "items": [
                    {"id": {"kind": "youtube#video", "videoId": "v2"}},
                    {"id": {"kind": "youtube#video", "videoId": "v3"}},
                ]
            },
        ]
    )
    statistics_http = RecordingHttp(
        [
            _stats_response(
                ("v1", 1000, 100, 10),
                ("v2", 2000, 150, 20),
                ("v3", 3000, 200, 30),
            )
        ]
    )
    search_fetcher = YouTubePublicSearchFetcher(
        api_key="key",
        max_search_calls_per_run=2,
        timeout_seconds=5.0,
        http_get=search_http,
    )
    statistics_fetcher = YouTubeVideoStatisticsFetcher(
        api_key="key",
        max_statistics_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=statistics_http,
    )

    bundle = collect_youtube_research_bundle(
        ENTITY,
        ("NVIDIA", "Blackwell"),
        as_of=NOW,
        search_fetcher=search_fetcher,
        statistics_fetcher=statistics_fetcher,
    )

    assert bundle.selected_video_ids == ("v1", "v2", "v3")
    assert [row.raw_level for row in bundle.video_count_observations] == [2.0, 1.0]
    assert {row.metric: row.raw_level for row in bundle.statistics_observations} == {
        "VIDEO_VIEW_TOTAL_SELECTED_SET": 6000.0,
        "VIDEO_LIKE_TOTAL_SELECTED_SET": 450.0,
        "VIDEO_COMMENT_TOTAL_SELECTED_SET": 60.0,
    }
    assert len(search_http.urls) == 2
    assert len(statistics_http.urls) == 1
    assert search_fetcher.search_calls_used == 2
    assert statistics_fetcher.statistics_calls_used == 1
    assert bundle.research_only is True
    assert bundle.trading_authorized is False
    assert bundle.live_trading_enabled is False


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


def test_missing_provider_video_is_visible_without_fabricated_video_row():
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


def test_missing_metric_field_omits_that_aggregate_instead_of_fabricating_zero():
    http = RecordingHttp(
        [
            {
                "items": [
                    {
                        "id": "v1",
                        "statistics": {
                            "viewCount": "1000",
                            "likeCount": "100",
                            "commentCount": "10",
                        },
                    },
                    {
                        "id": "v2",
                        "statistics": {
                            "viewCount": "2000",
                            "likeCount": "150",
                        },
                    },
                ]
            }
        ]
    )
    fetcher = YouTubeVideoStatisticsFetcher(
        api_key="key",
        max_statistics_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )

    rows, coverage = fetcher.collect(ENTITY, ("v1", "v2"), as_of=NOW)
    metrics = {row.metric: row.raw_level for row in rows}

    assert coverage.returned_video_ids == 2
    assert metrics == {
        "VIDEO_VIEW_TOTAL_SELECTED_SET": 3000.0,
        "VIDEO_LIKE_TOTAL_SELECTED_SET": 250.0,
    }
    assert "VIDEO_COMMENT_TOTAL_SELECTED_SET" not in metrics
    provenance = json.loads(rows[0].provenance)
    assert provenance["missing_metric_counts"]["VIDEO_COMMENT_TOTAL_SELECTED_SET"] == 1
