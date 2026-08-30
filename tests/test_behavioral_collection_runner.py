from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_change import (
    BehavioralEntity,
    BehavioralObservation,
    BehavioralSource,
    ProviderFetchResult,
    SourceStatus,
)
from daily_alpha.behavioral_collection_lineage import (
    BehavioralProviderDependency,
    build_collection_lineage,
)
from daily_alpha.behavioral_collection_runner import (
    load_behavioral_history,
    run_behavioral_collection,
)

AS_OF = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
VERSION = "2026-08-20-test"


def _entity() -> BehavioralEntity:
    return BehavioralEntity(
        entity_id="NVDA:behavioral",
        ticker="NVDA",
        version=VERSION,
        company_name="NVIDIA",
    )


def _dictionary(tmp_path):
    path = tmp_path / "entities.json"
    path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "research_only": True,
                "entities": [
                    {
                        "entity_id": "NVDA:behavioral",
                        "ticker": "NVDA",
                        "company_name": "NVIDIA",
                    }
                ],
            }
        )
    )
    return path


def _lineage(tmp_path):
    return build_collection_lineage(
        _dictionary(tmp_path),
        as_of=AS_OF,
        providers=(
            BehavioralProviderDependency(
                source=BehavioralSource.GOOGLE_TRENDS,
                adapter_version="test-google-v1",
                access_mode="OPTIONAL_API",
                configured=True,
                max_queries_per_run=4,
                credential_reference="github-actions://GOOGLE_TEST",
            ),
            BehavioralProviderDependency(
                source=BehavioralSource.YOUTUBE,
                adapter_version="test-youtube-v1",
                access_mode="PUBLIC_API_KEY",
                configured=True,
                max_queries_per_run=4,
                credential_reference="aws-secretsmanager://daily-alpha/youtube-api-key",
            ),
            BehavioralProviderDependency(
                source=BehavioralSource.SIMILARWEB,
                adapter_version="test-similarweb-v1",
                access_mode="OPTIONAL_API",
                configured=False,
                max_queries_per_run=4,
            ),
        ),
    )


def _observation(
    source: BehavioralSource,
    timestamp: datetime,
    level: float,
    *,
    metric: str,
    query_key: str,
) -> BehavioralObservation:
    return BehavioralObservation(
        source=source,
        entity_id="NVDA:behavioral",
        ticker="NVDA",
        query_key=query_key,
        metric=metric,
        observed_at=timestamp,
        source_timestamp=timestamp,
        raw_level=level,
        provenance="test-fixture",
    )


def _history() -> tuple[BehavioralObservation, ...]:
    rows: list[BehavioralObservation] = []
    for days_ago in range(1, 28):
        timestamp = AS_OF - timedelta(days=days_ago)
        rows.extend(
            [
                _observation(
                    BehavioralSource.GOOGLE_TRENDS,
                    timestamp,
                    100.0 + (28 - days_ago),
                    metric="SEARCH_INTEREST",
                    query_key="NVIDIA",
                ),
                _observation(
                    BehavioralSource.YOUTUBE,
                    timestamp,
                    50.0 + (28 - days_ago),
                    metric="NEW_VIDEO_COUNT_24H",
                    query_key="NVIDIA",
                ),
            ]
        )
    return tuple(rows)


def _provider_results(*, youtube_timestamp: datetime = AS_OF):
    return (
        ProviderFetchResult(
            source=BehavioralSource.GOOGLE_TRENDS,
            status=SourceStatus.COMPLETE,
            observations=(
                _observation(
                    BehavioralSource.GOOGLE_TRENDS,
                    AS_OF,
                    128.0,
                    metric="SEARCH_INTEREST",
                    query_key="NVIDIA",
                ),
            ),
        ),
        ProviderFetchResult(
            source=BehavioralSource.YOUTUBE,
            status=SourceStatus.COMPLETE,
            observations=(
                _observation(
                    BehavioralSource.YOUTUBE,
                    youtube_timestamp,
                    78.0,
                    metric="NEW_VIDEO_COUNT_24H",
                    query_key="NVIDIA",
                ),
            ),
        ),
        ProviderFetchResult(
            source=BehavioralSource.SIMILARWEB,
            status=SourceStatus.SOURCE_UNAVAILABLE,
            reason="PROVIDER_ACCESS_NOT_CONFIGURED",
        ),
    )


def test_collection_binds_two_source_snapshot_to_immutable_receipt(tmp_path) -> None:
    entity = _entity()
    root = tmp_path / "behavioral"
    supplemental = (
        _observation(
            BehavioralSource.YOUTUBE,
            AS_OF,
            1_000_000_000.0,
            metric="VIDEO_VIEW_TOTAL_SELECTED_SET",
            query_key="ENTITY_UNIQUE_VIDEO_SET",
        ),
    )

    run = run_behavioral_collection(
        entity=entity,
        lineage=_lineage(tmp_path),
        provider_results=_provider_results(),
        artifact_root=root,
        historical_observations=_history(),
        supplemental_observations=supplemental,
    )

    assert run.snapshot.behavioral_change_score is not None
    assert run.research_only is True
    assert run.trading_authorized is False
    assert run.live_trading_enabled is False
    assert run.receipt.trading_authorized is False
    assert run.receipt.live_trading_enabled is False
    assert run.receipt_path.exists()
    assert len(run.receipt_sha256) == 64

    youtube_signal = next(
        signal
        for signal in run.snapshot.source_signals
        if signal.source == BehavioralSource.YOUTUBE
    )
    assert youtube_signal.status == SourceStatus.COMPLETE
    assert youtube_signal.level_7d is not None
    assert youtube_signal.level_7d < 10_000

    persisted = load_behavioral_history(root, entity=entity, as_of=AS_OF)
    assert {row.metric for row in persisted} == {
        "SEARCH_INTEREST",
        "NEW_VIDEO_COUNT_24H",
        "VIDEO_VIEW_TOTAL_SELECTED_SET",
    }


def test_collection_is_idempotent_for_identical_evidence(tmp_path) -> None:
    kwargs = {
        "entity": _entity(),
        "lineage": _lineage(tmp_path),
        "provider_results": _provider_results(),
        "artifact_root": tmp_path / "behavioral",
        "historical_observations": _history(),
    }

    first = run_behavioral_collection(**kwargs)
    second = run_behavioral_collection(**kwargs)

    assert first.artifacts.observations_sha256 == second.artifacts.observations_sha256
    assert first.artifacts.snapshot_sha256 == second.artifacts.snapshot_sha256
    assert first.receipt.receipt_id == second.receipt.receipt_id
    assert first.receipt_sha256 == second.receipt_sha256


def test_collection_rejects_lookahead_before_writing_artifacts(tmp_path) -> None:
    future = AS_OF + timedelta(seconds=1)
    root = tmp_path / "behavioral"

    with pytest.raises(ValueError, match="BEHAVIORAL_COLLECTION_LOOKAHEAD_REJECTED"):
        run_behavioral_collection(
            entity=_entity(),
            lineage=_lineage(tmp_path),
            provider_results=_provider_results(youtube_timestamp=future),
            artifact_root=root,
            historical_observations=_history(),
        )

    assert not root.exists()


def test_collection_rejects_entity_dictionary_version_drift(tmp_path) -> None:
    entity = BehavioralEntity(
        entity_id="NVDA:behavioral",
        ticker="NVDA",
        version="different-version",
        company_name="NVIDIA",
    )

    with pytest.raises(
        ValueError,
        match="BEHAVIORAL_COLLECTION_ENTITY_DICTIONARY_VERSION_MISMATCH",
    ):
        run_behavioral_collection(
            entity=entity,
            lineage=_lineage(tmp_path),
            provider_results=_provider_results(),
            artifact_root=tmp_path / "behavioral",
            historical_observations=_history(),
        )
