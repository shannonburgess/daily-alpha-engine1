"""Metric-separated YouTube video statistics for Behavioral Change research.

This sidecar intentionally stays separate from the current video-count source scorer.
Views, likes and comments are different units and must never be summed into the same
source level. Callers supply a deduplicated entity-level video-ID set (for example,
from the bounded trailing-24h search transport) and receive metric-specific canonical
observations that can be validated independently before any factor promotion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from .behavioral_change import BehavioralEntity, BehavioralObservation, BehavioralSource
from .behavioral_youtube import (
    HttpGet,
    YouTubeQuotaBudgetExceeded,
    YouTubeTransportError,
    _default_http_get,
)

YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
_MAX_PROVIDER_IDS_PER_CALL = 50


@dataclass(frozen=True)
class YouTubeStatisticsCoverage:
    requested_unique_video_ids: int
    returned_video_ids: int
    missing_video_ids: int
    statistics_calls_used: int
    cache_hits: int


@dataclass
class YouTubeVideoStatisticsFetcher:
    """Fetch public video statistics with bounded calls and same-day caching.

    The output is a research sidecar only. It does not plug into
    ``YouTubeDataAdapter`` because the current source scorer aggregates one metric
    family at a time. Mixing counts, views, likes and comments would violate the
    Behavioral Change noise-control contract.
    """

    api_key: str
    max_statistics_calls_per_run: int = 4
    max_video_ids_per_call: int = _MAX_PROVIDER_IDS_PER_CALL
    timeout_seconds: float = 10.0
    http_get: HttpGet | None = None
    _statistics_calls_used: int = field(default=0, init=False, repr=False)
    _cache: dict[
        tuple[str, tuple[str, ...]], dict[str, dict[str, int | None]]
    ] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.api_key = self.api_key.strip()
        if not self.api_key:
            raise ValueError("YouTube API key is required")
        if self.max_statistics_calls_per_run <= 0:
            raise ValueError("max_statistics_calls_per_run must be positive")
        if not 1 <= self.max_video_ids_per_call <= _MAX_PROVIDER_IDS_PER_CALL:
            raise ValueError("max_video_ids_per_call must be between 1 and 50")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.http_get is None:
            self.http_get = _default_http_get

    @property
    def statistics_calls_used(self) -> int:
        return self._statistics_calls_used

    def collect(
        self,
        entity: BehavioralEntity,
        video_ids: tuple[str, ...],
        *,
        as_of: datetime,
    ) -> tuple[tuple[BehavioralObservation, ...], YouTubeStatisticsCoverage]:
        """Collect metric-separated statistics for one unique entity-level video set."""
        _require_aware(as_of)
        timestamp = as_of.astimezone(UTC)
        unique_ids = _dedupe_video_ids(video_ids)
        if not unique_ids:
            coverage = YouTubeStatisticsCoverage(0, 0, 0, 0, 0)
            return (), coverage

        batches = tuple(
            unique_ids[index : index + self.max_video_ids_per_call]
            for index in range(0, len(unique_ids), self.max_video_ids_per_call)
        )
        day_key = timestamp.date().isoformat()
        uncached_batches = [
            batch for batch in batches if (day_key, tuple(batch)) not in self._cache
        ]
        remaining = self.max_statistics_calls_per_run - self._statistics_calls_used
        if len(uncached_batches) > remaining:
            raise YouTubeQuotaBudgetExceeded(
                "YOUTUBE_STATISTICS_CALL_BUDGET_EXCEEDED:"
                f"needed={len(uncached_batches)}:remaining={remaining}"
            )

        by_video: dict[str, dict[str, int | None]] = {}
        cache_hits = 0
        calls_before = self._statistics_calls_used
        for batch in batches:
            cache_key = (day_key, tuple(batch))
            cached = self._cache.get(cache_key)
            if cached is not None:
                cache_hits += 1
                by_video.update(cached)
                continue
            fetched = self._fetch_batch(tuple(batch))
            self._cache[cache_key] = fetched
            self._statistics_calls_used += 1
            by_video.update(fetched)

        returned_ids = tuple(video_id for video_id in unique_ids if video_id in by_video)
        missing = len(unique_ids) - len(returned_ids)
        calls_used = self._statistics_calls_used - calls_before
        coverage = YouTubeStatisticsCoverage(
            requested_unique_video_ids=len(unique_ids),
            returned_video_ids=len(returned_ids),
            missing_video_ids=missing,
            statistics_calls_used=calls_used,
            cache_hits=cache_hits,
        )

        metric_fields = {
            "VIDEO_VIEW_TOTAL_SELECTED_SET": "view_count",
            "VIDEO_LIKE_TOTAL_SELECTED_SET": "like_count",
            "VIDEO_COMMENT_TOTAL_SELECTED_SET": "comment_count",
        }
        totals: dict[str, int] = {}
        missing_metric_counts: dict[str, int] = {}
        for metric, field_name in metric_fields.items():
            values = [by_video[video_id][field_name] for video_id in returned_ids]
            missing_metric_counts[metric] = sum(value is None for value in values)
            if values and all(value is not None for value in values):
                totals[metric] = sum(int(value) for value in values if value is not None)

        provenance = json.dumps(
            {
                "provider": "YOUTUBE_DATA_API_V3",
                "method": "videos.list",
                "selection_contract": "caller_supplied_deduplicated_entity_video_ids",
                "metric_units_kept_separate": True,
                "missing_metric_counts": missing_metric_counts,
                "requested_unique_video_ids": coverage.requested_unique_video_ids,
                "returned_video_ids": coverage.returned_video_ids,
                "missing_video_ids": coverage.missing_video_ids,
                "statistics_calls_used": coverage.statistics_calls_used,
                "cache_hits": coverage.cache_hits,
                "max_video_ids_per_call": self.max_video_ids_per_call,
                "api_key_persisted": False,
                "research_only": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        observations = tuple(
            BehavioralObservation(
                source=BehavioralSource.YOUTUBE,
                entity_id=entity.entity_id,
                ticker=entity.ticker,
                query_key="ENTITY_UNIQUE_VIDEO_SET",
                metric=metric,
                observed_at=timestamp,
                source_timestamp=timestamp,
                raw_level=float(value),
                provenance=provenance,
            )
            for metric, value in totals.items()
        )
        return observations, coverage

    def _fetch_batch(
        self,
        video_ids: tuple[str, ...],
    ) -> dict[str, dict[str, int | None]]:
        params = {
            "part": "statistics",
            "id": ",".join(video_ids),
            "key": self.api_key,
        }
        assert self.http_get is not None
        try:
            raw = self.http_get(
                f"{YOUTUBE_VIDEOS_ENDPOINT}?{urlencode(params)}",
                timeout_seconds=self.timeout_seconds,
            )
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise YouTubeTransportError(
                f"YOUTUBE_STATISTICS_REQUEST_FAILED:{type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise YouTubeTransportError("YOUTUBE_STATISTICS_RESPONSE_INVALID")

        result: dict[str, dict[str, int | None]] = {}
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "").strip()
            statistics = item.get("statistics")
            if not video_id or video_id not in video_ids or not isinstance(statistics, dict):
                continue
            result[video_id] = {
                "view_count": _optional_count(statistics.get("viewCount")),
                "like_count": _optional_count(statistics.get("likeCount")),
                "comment_count": _optional_count(statistics.get("commentCount")),
            }
        return result


def _dedupe_video_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        video_id = str(value or "").strip()
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        result.append(video_id)
    return tuple(result)


def _optional_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise YouTubeTransportError("YOUTUBE_STATISTICS_COUNT_INVALID") from exc
    if number < 0:
        raise YouTubeTransportError("YOUTUBE_STATISTICS_COUNT_INVALID")
    return number


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
