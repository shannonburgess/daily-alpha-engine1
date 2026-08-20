from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daily_alpha.behavioral_artifacts import BehavioralArtifactBundle
from daily_alpha.behavioral_change import (
    BehavioralObservation,
    BehavioralSnapshot,
    BehavioralSource,
    ProviderFetchResult,
    SourceStatus,
)
from daily_alpha.behavioral_collection_lineage import (
    BehavioralProviderDependency,
    bind_collection_receipt,
    build_collection_lineage,
)

AS_OF = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _dictionary(tmp_path: Path, *, version: str = "2026-08-20-v1") -> Path:
    path = tmp_path / "behavioral_entities.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "research_only": True,
                "entities": [
                    {
                        "entity_id": f"NVDA:{version}",
                        "ticker": "NVDA",
                        "company_name": "Nvidia",
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _providers() -> tuple[BehavioralProviderDependency, ...]:
    return (
        BehavioralProviderDependency(
            source=BehavioralSource.GOOGLE_TRENDS,
            adapter_version="google-trends-alpha-v1",
            access_mode="DISABLED",
            configured=False,
            max_queries_per_run=8,
            cache_scope="SAME_UTC_DAY",
        ),
        BehavioralProviderDependency(
            source=BehavioralSource.YOUTUBE,
            adapter_version="youtube-data-v3-search-v1",
            access_mode="PUBLIC_API_KEY",
            configured=True,
            max_queries_per_run=8,
            cache_scope="SAME_UTC_DAY",
            credential_reference="aws-secretsmanager://daily-alpha/youtube-api-key",
        ),
        BehavioralProviderDependency(
            source=BehavioralSource.SIMILARWEB,
            adapter_version="similarweb-optional-v1",
            access_mode="OPTIONAL_API",
            configured=False,
            max_queries_per_run=4,
            cache_scope="SAME_UTC_DAY",
        ),
    )


def _observation(*, observed_at: datetime = AS_OF) -> BehavioralObservation:
    return BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA:2026-08-20-v1",
        ticker="NVDA",
        query_key="NVIDIA",
        metric="NEW_VIDEO_COUNT_24H",
        observed_at=observed_at,
        source_timestamp=observed_at,
        raw_level=12.0,
        provenance="youtube-data-api-v3:test",
    )


def _snapshot() -> BehavioralSnapshot:
    return BehavioralSnapshot(
        entity_id="NVDA:2026-08-20-v1",
        ticker="NVDA",
        as_of=AS_OF,
        source_signals=(),
        cross_source_confirmation=0.0,
        behavioral_change_score=None,
        information_imbalance_score=None,
        information_imbalance_reason="WALL_STREET_RECOGNITION_NOT_CONNECTED",
    )


def _artifacts(tmp_path: Path) -> BehavioralArtifactBundle:
    return BehavioralArtifactBundle(
        directory=tmp_path,
        observations_path=tmp_path / "behavioral_observations.jsonl",
        snapshot_path=tmp_path / "behavioral_snapshot.json",
        manifest_path=tmp_path / "behavioral_manifest.json",
        observations_sha256="a" * 64,
        snapshot_sha256="b" * 64,
    )


def _results(observation: BehavioralObservation) -> tuple[ProviderFetchResult, ...]:
    return (
        ProviderFetchResult(
            source=BehavioralSource.GOOGLE_TRENDS,
            status=SourceStatus.SOURCE_UNAVAILABLE,
            reason="PROVIDER_ACCESS_NOT_CONFIGURED",
        ),
        ProviderFetchResult(
            source=BehavioralSource.YOUTUBE,
            status=SourceStatus.COMPLETE,
            observations=(observation,),
        ),
        ProviderFetchResult(
            source=BehavioralSource.SIMILARWEB,
            status=SourceStatus.SOURCE_UNAVAILABLE,
            reason="PROVIDER_ACCESS_NOT_CONFIGURED",
        ),
    )


def test_lineage_is_deterministic_and_provider_order_independent(tmp_path: Path):
    path = _dictionary(tmp_path)
    providers = _providers()

    first = build_collection_lineage(path, as_of=AS_OF, providers=providers)
    second = build_collection_lineage(path, as_of=AS_OF, providers=tuple(reversed(providers)))

    assert first.lineage_id == second.lineage_id
    assert [item.source for item in first.providers] == sorted(
        (item.source for item in providers), key=lambda item: item.value
    )
    assert first.research_only is True
    assert first.trading_authorized is False
    assert first.live_trading_enabled is False


def test_exact_entity_dictionary_bytes_are_part_of_lineage_identity(tmp_path: Path):
    path = _dictionary(tmp_path)
    first = build_collection_lineage(path, as_of=AS_OF, providers=_providers())

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    second = build_collection_lineage(path, as_of=AS_OF, providers=_providers())

    assert first.entity_dictionary_version == second.entity_dictionary_version
    assert first.entity_dictionary_sha256 != second.entity_dictionary_sha256
    assert first.lineage_id != second.lineage_id


def test_duplicate_provider_dependency_fails_closed(tmp_path: Path):
    path = _dictionary(tmp_path)
    youtube = _providers()[1]

    with pytest.raises(ValueError, match="BEHAVIORAL_PROVIDER_DEPENDENCY_DUPLICATE"):
        build_collection_lineage(path, as_of=AS_OF, providers=(youtube, youtube))


def test_raw_credential_value_is_rejected_from_lineage():
    with pytest.raises(ValueError, match="BEHAVIORAL_CREDENTIAL_REFERENCE_MUST_BE_OPAQUE_REFERENCE"):
        BehavioralProviderDependency(
            source=BehavioralSource.YOUTUBE,
            adapter_version="youtube-v1",
            access_mode="PUBLIC_API_KEY",
            configured=True,
            max_queries_per_run=8,
            credential_reference="AIza-not-a-reference",
        )


def test_unconfigured_provider_cannot_silently_report_complete(tmp_path: Path):
    lineage = build_collection_lineage(_dictionary(tmp_path), as_of=AS_OF, providers=_providers())
    observation = _observation()
    results = list(_results(observation))
    results[0] = ProviderFetchResult(
        source=BehavioralSource.GOOGLE_TRENDS,
        status=SourceStatus.COMPLETE,
        observations=(),
    )

    with pytest.raises(ValueError, match="BEHAVIORAL_UNCONFIGURED_PROVIDER_RETURNED_COMPLETE"):
        bind_collection_receipt(
            lineage,
            fetch_results=tuple(results),
            observations=(observation,),
            snapshot=_snapshot(),
            artifacts=_artifacts(tmp_path),
        )


def test_collection_receipt_binds_all_provider_status_and_hashes(tmp_path: Path):
    lineage = build_collection_lineage(_dictionary(tmp_path), as_of=AS_OF, providers=_providers())
    observation = _observation()

    first = bind_collection_receipt(
        lineage,
        fetch_results=_results(observation),
        observations=(observation,),
        snapshot=_snapshot(),
        artifacts=_artifacts(tmp_path),
    )
    second = bind_collection_receipt(
        lineage,
        fetch_results=tuple(reversed(_results(observation))),
        observations=(observation,),
        snapshot=_snapshot(),
        artifacts=_artifacts(tmp_path),
    )

    assert first.receipt_id == second.receipt_id
    assert first.lineage_id == lineage.lineage_id
    assert first.observations_sha256 == "a" * 64
    assert first.snapshot_sha256 == "b" * 64
    assert [item.source for item in first.provider_status] == [
        BehavioralSource.GOOGLE_TRENDS,
        BehavioralSource.SIMILARWEB,
        BehavioralSource.YOUTUBE,
    ]
    assert first.trading_authorized is False
    assert first.live_trading_enabled is False


def test_missing_provider_result_fails_closed(tmp_path: Path):
    lineage = build_collection_lineage(_dictionary(tmp_path), as_of=AS_OF, providers=_providers())
    observation = _observation()

    with pytest.raises(ValueError, match="BEHAVIORAL_COLLECTION_PROVIDER_RESULT_SET_MISMATCH"):
        bind_collection_receipt(
            lineage,
            fetch_results=_results(observation)[:-1],
            observations=(observation,),
            snapshot=_snapshot(),
            artifacts=_artifacts(tmp_path),
        )


def test_future_observation_is_rejected_at_collection_boundary(tmp_path: Path):
    lineage = build_collection_lineage(_dictionary(tmp_path), as_of=AS_OF, providers=_providers())
    future = _observation(observed_at=AS_OF + timedelta(seconds=1))

    with pytest.raises(ValueError, match="BEHAVIORAL_COLLECTION_LOOKAHEAD_REJECTED"):
        bind_collection_receipt(
            lineage,
            fetch_results=_results(future),
            observations=(future,),
            snapshot=_snapshot(),
            artifacts=_artifacts(tmp_path),
        )
