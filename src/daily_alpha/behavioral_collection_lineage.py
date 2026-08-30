"""Storage/dependency lineage contract for scheduled Behavioral Change research collection.

This module deliberately stops before any deployment or scheduler integration. It freezes
what a collection run is allowed to depend on, hashes the exact entity dictionary, and
binds resulting point-in-time evidence to that lineage without persisting credentials.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .behavioral_artifacts import BehavioralArtifactBundle
from .behavioral_change import (
    BehavioralObservation,
    BehavioralSnapshot,
    BehavioralSource,
    ProviderFetchResult,
    SourceStatus,
)

COLLECTION_SCHEMA_VERSION = "2026-08-20-v1"
ARTIFACT_SCHEMA_VERSION = "2026-08-19-v1"
_ALLOWED_ACCESS_MODES = {"DISABLED", "PUBLIC_API_KEY", "OPTIONAL_API"}
_ALLOWED_CACHE_SCOPES = {"SAME_UTC_DAY", "NONE"}
_ALLOWED_CREDENTIAL_PREFIXES = (
    "aws-secretsmanager://",
    "github-actions://",
)


@dataclass(frozen=True)
class BehavioralProviderDependency:
    source: BehavioralSource
    adapter_version: str
    access_mode: str
    configured: bool
    max_queries_per_run: int
    cache_scope: str = "SAME_UTC_DAY"
    credential_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.adapter_version.strip():
            raise ValueError("BEHAVIORAL_PROVIDER_ADAPTER_VERSION_REQUIRED")
        if self.access_mode not in _ALLOWED_ACCESS_MODES:
            raise ValueError("BEHAVIORAL_PROVIDER_ACCESS_MODE_INVALID")
        if self.cache_scope not in _ALLOWED_CACHE_SCOPES:
            raise ValueError("BEHAVIORAL_PROVIDER_CACHE_SCOPE_INVALID")
        if self.max_queries_per_run <= 0:
            raise ValueError("BEHAVIORAL_PROVIDER_QUERY_LIMIT_INVALID")
        if self.access_mode == "DISABLED" and self.configured:
            raise ValueError("BEHAVIORAL_DISABLED_PROVIDER_CANNOT_BE_CONFIGURED")
        if self.configured and self.access_mode != "DISABLED" and not self.credential_reference:
            raise ValueError("BEHAVIORAL_CONFIGURED_PROVIDER_CREDENTIAL_REFERENCE_REQUIRED")
        if self.credential_reference is not None:
            reference = self.credential_reference.strip()
            if not reference.startswith(_ALLOWED_CREDENTIAL_PREFIXES):
                raise ValueError("BEHAVIORAL_CREDENTIAL_REFERENCE_MUST_BE_OPAQUE_REFERENCE")
            if any(marker in reference for marker in ("AIza", "BEGIN PRIVATE KEY", "Bearer ")):
                raise ValueError("BEHAVIORAL_CREDENTIAL_VALUE_FORBIDDEN")


@dataclass(frozen=True)
class BehavioralCollectionLineage:
    schema_version: str
    as_of: datetime
    entity_dictionary_version: str
    entity_dictionary_sha256: str
    artifact_schema_version: str
    artifact_root_contract: str
    providers: tuple[BehavioralProviderDependency, ...]
    lineage_id: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class BehavioralProviderRunStatus:
    source: BehavioralSource
    configured: bool
    status: SourceStatus
    reason: str
    observation_count: int


@dataclass(frozen=True)
class BehavioralCollectionReceipt:
    schema_version: str
    lineage_id: str
    as_of: datetime
    entity_id: str
    ticker: str
    provider_status: tuple[BehavioralProviderRunStatus, ...]
    observations_sha256: str
    snapshot_sha256: str
    receipt_id: str
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def build_collection_lineage(
    entity_dictionary_path: str | Path,
    *,
    as_of: datetime,
    providers: tuple[BehavioralProviderDependency, ...],
    artifact_root_contract: str = "<date>/<entity_id>/",
) -> BehavioralCollectionLineage:
    """Freeze the exact dependencies allowed for one point-in-time collection run."""
    _require_aware(as_of, "as_of")
    if not artifact_root_contract.strip():
        raise ValueError("BEHAVIORAL_ARTIFACT_ROOT_CONTRACT_REQUIRED")
    if not providers:
        raise ValueError("BEHAVIORAL_PROVIDER_DEPENDENCIES_REQUIRED")

    raw_dictionary = Path(entity_dictionary_path).read_bytes()
    payload = json.loads(raw_dictionary)
    if not isinstance(payload, dict):
        raise TypeError("BEHAVIORAL_ENTITY_DICTIONARY_INVALID")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise ValueError("BEHAVIORAL_ENTITY_DICTIONARY_VERSION_REQUIRED")
    if payload.get("research_only") is not True:
        raise ValueError("BEHAVIORAL_ENTITY_DICTIONARY_RESEARCH_ONLY_REQUIRED")

    ordered = tuple(sorted(providers, key=lambda item: item.source.value))
    if len({item.source for item in ordered}) != len(ordered):
        raise ValueError("BEHAVIORAL_PROVIDER_DEPENDENCY_DUPLICATE")

    dictionary_sha = hashlib.sha256(raw_dictionary).hexdigest()
    canonical = {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "as_of": as_of.astimezone(UTC).isoformat(),
        "entity_dictionary_version": version,
        "entity_dictionary_sha256": dictionary_sha,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_root_contract": artifact_root_contract,
        "providers": [_provider_payload(item) for item in ordered],
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    lineage_id = _sha256_json(canonical)
    return BehavioralCollectionLineage(
        schema_version=COLLECTION_SCHEMA_VERSION,
        as_of=as_of.astimezone(UTC),
        entity_dictionary_version=version,
        entity_dictionary_sha256=dictionary_sha,
        artifact_schema_version=ARTIFACT_SCHEMA_VERSION,
        artifact_root_contract=artifact_root_contract,
        providers=ordered,
        lineage_id=lineage_id,
    )


def bind_collection_receipt(
    lineage: BehavioralCollectionLineage,
    *,
    fetch_results: tuple[ProviderFetchResult, ...],
    observations: tuple[BehavioralObservation, ...],
    snapshot: BehavioralSnapshot,
    artifacts: BehavioralArtifactBundle,
) -> BehavioralCollectionReceipt:
    """Bind collected evidence to the frozen dependency lineage, failing closed on drift."""
    _require_aware(lineage.as_of, "lineage.as_of")
    _require_aware(snapshot.as_of, "snapshot.as_of")
    if snapshot.as_of.astimezone(UTC) != lineage.as_of.astimezone(UTC):
        raise ValueError("BEHAVIORAL_COLLECTION_AS_OF_MISMATCH")
    if snapshot.research_only is not True:
        raise ValueError("BEHAVIORAL_COLLECTION_RESEARCH_ONLY_REQUIRED")
    if snapshot.trading_authorized is not False or snapshot.live_trading_enabled is not False:
        raise ValueError("BEHAVIORAL_COLLECTION_SAFETY_FLAG_VIOLATION")
    if not artifacts.observations_sha256 or not artifacts.snapshot_sha256:
        raise ValueError("BEHAVIORAL_COLLECTION_ARTIFACT_HASH_REQUIRED")

    dependencies = {item.source: item for item in lineage.providers}
    results: dict[BehavioralSource, ProviderFetchResult] = {}
    for result in fetch_results:
        if result.source in results:
            raise ValueError("BEHAVIORAL_COLLECTION_DUPLICATE_PROVIDER_RESULT")
        if result.source not in dependencies:
            raise ValueError("BEHAVIORAL_COLLECTION_UNDECLARED_PROVIDER_RESULT")
        dependency = dependencies[result.source]
        if not dependency.configured and result.status == SourceStatus.COMPLETE:
            raise ValueError("BEHAVIORAL_UNCONFIGURED_PROVIDER_RETURNED_COMPLETE")
        if result.status == SourceStatus.COMPLETE and result.reason:
            raise ValueError("BEHAVIORAL_COMPLETE_PROVIDER_CANNOT_HAVE_REASON")
        for row in result.observations:
            _validate_observation(row, lineage=lineage, source=result.source)
        results[result.source] = result

    if set(results) != set(dependencies):
        raise ValueError("BEHAVIORAL_COLLECTION_PROVIDER_RESULT_SET_MISMATCH")

    for row in observations:
        if row.source not in dependencies:
            raise ValueError("BEHAVIORAL_COLLECTION_UNDECLARED_OBSERVATION_SOURCE")
        _validate_observation(row, lineage=lineage, source=row.source)
        if row.entity_id != snapshot.entity_id or row.ticker.upper() != snapshot.ticker.upper():
            raise ValueError("BEHAVIORAL_COLLECTION_OBSERVATION_ENTITY_MISMATCH")

    statuses = tuple(
        BehavioralProviderRunStatus(
            source=source,
            configured=dependencies[source].configured,
            status=results[source].status,
            reason=results[source].reason,
            observation_count=len(results[source].observations),
        )
        for source in sorted(results, key=lambda item: item.value)
    )
    payload = {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "lineage_id": lineage.lineage_id,
        "as_of": lineage.as_of.astimezone(UTC).isoformat(),
        "entity_id": snapshot.entity_id,
        "ticker": snapshot.ticker.upper(),
        "provider_status": [
            {
                "source": item.source.value,
                "configured": item.configured,
                "status": item.status.value,
                "reason": item.reason,
                "observation_count": item.observation_count,
            }
            for item in statuses
        ],
        "observations_sha256": artifacts.observations_sha256,
        "snapshot_sha256": artifacts.snapshot_sha256,
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return BehavioralCollectionReceipt(
        schema_version=COLLECTION_SCHEMA_VERSION,
        lineage_id=lineage.lineage_id,
        as_of=lineage.as_of.astimezone(UTC),
        entity_id=snapshot.entity_id,
        ticker=snapshot.ticker.upper(),
        provider_status=statuses,
        observations_sha256=artifacts.observations_sha256,
        snapshot_sha256=artifacts.snapshot_sha256,
        receipt_id=_sha256_json(payload),
    )


def _validate_observation(
    row: BehavioralObservation,
    *,
    lineage: BehavioralCollectionLineage,
    source: BehavioralSource,
) -> None:
    if row.source != source:
        raise ValueError("BEHAVIORAL_COLLECTION_PROVIDER_OBSERVATION_SOURCE_MISMATCH")
    if row.observed_at > lineage.as_of or row.source_timestamp > lineage.as_of:
        raise ValueError("BEHAVIORAL_COLLECTION_LOOKAHEAD_REJECTED")


def _provider_payload(item: BehavioralProviderDependency) -> dict[str, Any]:
    return {
        "source": item.source.value,
        "adapter_version": item.adapter_version,
        "access_mode": item.access_mode,
        "configured": item.configured,
        "max_queries_per_run": item.max_queries_per_run,
        "cache_scope": item.cache_scope,
        "credential_reference": item.credential_reference,
    }


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
