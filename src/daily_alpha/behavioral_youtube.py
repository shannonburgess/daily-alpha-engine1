"""Quota-bounded YouTube Data API v3 transport for Behavioral Change research.

The transport uses only public search data and receives its API key by injection.
It never logs or persists the key.  One search request is made per uncached query,
with no pagination, and duplicate video IDs across entity aliases are counted once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .behavioral_change import (
    BehavioralEntity,
    BehavioralObservation,
    BehavioralSource,
    YouTubeDataAdapter,
)

YOUTUBE_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"


class YouTubeTransportError(RuntimeError):
    """Public YouTube transport failed or returned an invalid response."""


class YouTubeQuotaBudgetExceeded(YouTubeTransportError):
    """Configured per-run search-call budget would be exceeded."""


class HttpGet(Protocol):
    def __call__(self, url: str, *, timeout_seconds: float) -> bytes: ...


@dataclass
class YouTubePublicSearchFetcher:
    """Collect one deduplicated trailing-24h video-count observation per query."""

    api_key: str
    max_search_calls_per_run: int = 4
    max_results_per_query: int = 50
    timeout_seconds: float = 10.0
    http_get: HttpGet | None = None
    _search_calls_used: int = field(default=0, init=False, repr=False)
    _cache: dict[tuple[str, str], tuple[str, ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.api_key = self.api_key.strip()
        if not self.api_key:
            raise ValueError("YouTube API key is required")
        if self.max_search_calls_per_run <= 0:
            raise ValueError("max_search_calls_per_run must be positive")
        if not 1 <= self.max_results_per_query <= 50:
            raise ValueError("max_results_per_query must be between 1 and 50")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.http_get is None:
            self.http_get = _default_http_get

    @property
    def search_calls_used(self) -> int:
        return self._search_calls_used

    def __call__(
        self,
        entity: BehavioralEntity,
        query_keys: tuple[str, ...],
        as_of: datetime,
    ) -> tuple[BehavioralObservation, ...]:
        _require_aware(as_of)
        timestamp = as_of.astimezone(UTC)
        day_key = timestamp.date().isoformat()
        normalized_queries = tuple(_dedupe_queries(query_keys))
        uncached = [
            query
            for query in normalized_queries
            if (query.casefold(), day_key) not in self._cache
        ]
        remaining = self.max_search_calls_per_run - self._search_calls_used
        if len(uncached) > remaining:
            raise YouTubeQuotaBudgetExceeded(
                f"YOUTUBE_SEARCH_CALL_BUDGET_EXCEEDED:needed={len(uncached)}:remaining={remaining}"
            )

        seen_video_ids: set[str] = set()
        observations: list[BehavioralObservation] = []
        for query in normalized_queries:
            cache_key = (query.casefold(), day_key)
            video_ids = self._cache.get(cache_key)
            cache_hit = video_ids is not None
            if video_ids is None:
                video_ids = self._search(query, timestamp)
                self._cache[cache_key] = video_ids
                self._search_calls_used += 1

            deduped_ids = tuple(video_id for video_id in video_ids if video_id not in seen_video_ids)
            seen_video_ids.update(deduped_ids)
            provenance = json.dumps(
                {
                    "provider": "YOUTUBE_DATA_API_V3",
                    "method": "search.list",
                    "metric_definition": "unique_matching_videos_published_trailing_24h",
                    "lookback_hours": 24,
                    "max_results": self.max_results_per_query,
                    "provider_result_count": len(video_ids),
                    "cross_query_unique_count": len(deduped_ids),
                    "cache_hit": cache_hit,
                    "pagination_used": False,
                    "result_cap_reached": len(video_ids) >= self.max_results_per_query,
                    "api_key_persisted": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            observations.append(
                BehavioralObservation(
                    source=BehavioralSource.YOUTUBE,
                    entity_id=entity.entity_id,
                    ticker=entity.ticker,
                    query_key=query,
                    metric="NEW_VIDEO_COUNT_24H",
                    observed_at=timestamp,
                    source_timestamp=timestamp,
                    raw_level=float(len(deduped_ids)),
                    provenance=provenance,
                )
            )
        return tuple(observations)

    def _search(self, query: str, as_of: datetime) -> tuple[str, ...]:
        published_after = (as_of - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        published_before = as_of.isoformat().replace("+00:00", "Z")
        params = {
            "part": "snippet",
            "type": "video",
            "order": "date",
            "q": query,
            "publishedAfter": published_after,
            "publishedBefore": published_before,
            "maxResults": str(self.max_results_per_query),
            "key": self.api_key,
        }
        assert self.http_get is not None
        try:
            raw = self.http_get(
                f"{YOUTUBE_SEARCH_ENDPOINT}?{urlencode(params)}",
                timeout_seconds=self.timeout_seconds,
            )
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - provider boundary normalized here
            raise YouTubeTransportError(f"YOUTUBE_SEARCH_REQUEST_FAILED:{type(exc).__name__}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise YouTubeTransportError("YOUTUBE_SEARCH_RESPONSE_INVALID")

        video_ids: list[str] = []
        seen: set[str] = set()
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            identity = item.get("id")
            if not isinstance(identity, dict):
                continue
            video_id = str(identity.get("videoId") or "").strip()
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            video_ids.append(video_id)
        return tuple(video_ids)


def build_youtube_data_adapter(
    api_key: str,
    *,
    max_queries_per_run: int = 4,
    max_results_per_query: int = 50,
    timeout_seconds: float = 10.0,
    http_get: HttpGet | None = None,
) -> YouTubeDataAdapter:
    """Build the canonical adapter with the transport's same hard query ceiling."""
    fetcher = YouTubePublicSearchFetcher(
        api_key=api_key,
        max_search_calls_per_run=max_queries_per_run,
        max_results_per_query=max_results_per_query,
        timeout_seconds=timeout_seconds,
        http_get=http_get,
    )
    return YouTubeDataAdapter(fetcher=fetcher, max_queries_per_run=max_queries_per_run)


def _default_http_get(url: str, *, timeout_seconds: float) -> bytes:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed HTTPS endpoint
        return response.read()


def _dedupe_queries(values: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        query = " ".join(str(value or "").strip().split())
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        result.append(query)
    return result


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
