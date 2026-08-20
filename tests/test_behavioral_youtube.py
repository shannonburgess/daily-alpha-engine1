import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from daily_alpha.behavioral_change import BehavioralEntity, SourceStatus
from daily_alpha.behavioral_youtube import (
    YouTubePublicSearchFetcher,
    YouTubeQuotaBudgetExceeded,
    build_youtube_data_adapter,
)

NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
ENTITY = BehavioralEntity(
    entity_id="NVDA",
    ticker="NVDA",
    version="2026-08-19-v1",
    company_name="NVIDIA",
    products=("Blackwell",),
)


class RecordingHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, *, timeout_seconds):
        assert timeout_seconds == 5.0
        self.urls.append(url)
        return json.dumps(self.responses.pop(0)).encode("utf-8")


def _response(*video_ids):
    return {
        "items": [
            {"id": {"kind": "youtube#video", "videoId": video_id}}
            for video_id in video_ids
        ]
    }


def test_youtube_fetcher_is_bounded_deduped_and_does_not_persist_key():
    http = RecordingHttp(
        [
            _response("v1", "v2", "v2"),
            _response("v2", "v3"),
        ]
    )
    fetcher = YouTubePublicSearchFetcher(
        api_key="secret-api-key",
        max_search_calls_per_run=2,
        max_results_per_query=50,
        timeout_seconds=5.0,
        http_get=http,
    )

    rows = fetcher(ENTITY, ("NVIDIA", "Blackwell"), NOW)

    assert [row.raw_level for row in rows] == [2.0, 1.0]
    assert [row.metric for row in rows] == ["NEW_VIDEO_COUNT_24H", "NEW_VIDEO_COUNT_24H"]
    assert fetcher.search_calls_used == 2
    assert len(http.urls) == 2
    assert "secret-api-key" not in rows[0].provenance
    assert "secret-api-key" not in rows[1].provenance

    first = parse_qs(urlparse(http.urls[0]).query)
    assert first["part"] == ["snippet"]
    assert first["type"] == ["video"]
    assert first["order"] == ["date"]
    assert first["q"] == ["NVIDIA"]
    assert first["maxResults"] == ["50"]
    assert first["key"] == ["secret-api-key"]
    assert first["publishedAfter"][0].endswith("Z")
    assert first["publishedBefore"][0].endswith("Z")


def test_search_collection_exposes_same_unique_ids_without_extra_search_calls():
    http = RecordingHttp(
        [
            _response("v1", "v2"),
            _response("v2", "v3"),
        ]
    )
    fetcher = YouTubePublicSearchFetcher(
        api_key="key",
        max_search_calls_per_run=2,
        timeout_seconds=5.0,
        http_get=http,
    )

    collection = fetcher.collect_with_video_ids(
        ENTITY,
        ("NVIDIA", "Blackwell"),
        NOW,
    )

    assert collection.unique_video_ids == ("v1", "v2", "v3")
    assert [row.raw_level for row in collection.observations] == [2.0, 1.0]
    assert fetcher.search_calls_used == 2
    assert len(http.urls) == 2

    repeated = fetcher.collect_with_video_ids(
        ENTITY,
        ("NVIDIA", "Blackwell"),
        NOW.replace(hour=21),
    )
    assert repeated.unique_video_ids == ("v1", "v2", "v3")
    assert fetcher.search_calls_used == 2
    assert len(http.urls) == 2


def test_same_day_fetcher_cache_uses_no_additional_search_calls():
    http = RecordingHttp([_response("v1")])
    fetcher = YouTubePublicSearchFetcher(
        api_key="key",
        max_search_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )

    first = fetcher(ENTITY, ("NVIDIA",), NOW)
    second = fetcher(ENTITY, ("NVIDIA",), NOW.replace(hour=21))

    assert first[0].raw_level == 1.0
    assert second[0].raw_level == 1.0
    assert fetcher.search_calls_used == 1
    assert len(http.urls) == 1
    assert json.loads(second[0].provenance)["cache_hit"] is True


def test_quota_budget_fails_before_partial_provider_fetch():
    http = RecordingHttp([])
    fetcher = YouTubePublicSearchFetcher(
        api_key="key",
        max_search_calls_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )

    with pytest.raises(YouTubeQuotaBudgetExceeded, match="YOUTUBE_SEARCH_CALL_BUDGET_EXCEEDED"):
        fetcher(ENTITY, ("NVIDIA", "Blackwell"), NOW)

    assert fetcher.search_calls_used == 0
    assert http.urls == []


def test_adapter_exposes_complete_public_video_count_without_trade_authorization():
    http = RecordingHttp([_response("v1", "v2")])
    adapter = build_youtube_data_adapter(
        "key",
        max_queries_per_run=1,
        timeout_seconds=5.0,
        http_get=http,
    )
    entity = BehavioralEntity(
        entity_id="NVDA",
        ticker="NVDA",
        version="2026-08-19-v1",
        company_name="NVIDIA",
    )

    result = adapter.collect(entity, as_of=NOW)

    assert result.status == SourceStatus.COMPLETE
    assert len(result.observations) == 1
    assert result.observations[0].raw_level == 2.0
    assert result.observations[0].metric == "NEW_VIDEO_COUNT_24H"
