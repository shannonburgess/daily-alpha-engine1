"""Provider-neutral orchestration for one Behavioral Change collection run.

The runner is deliberately storage-local and scheduler-agnostic. It composes already
validated provider results, prior immutable history and the frozen collection lineage
into one new immutable entity/day evidence bundle plus a deterministic collection
receipt. It never retrieves credentials itself and cannot authorize trading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .behavioral_artifacts import BehavioralArtifactBundle, write_behavioral_daily_artifacts
from .behavioral_change import (
    BehavioralEntity,
    BehavioralObservation,
    BehavioralSnapshot,
    BehavioralSource,
    ProviderFetchResult,
    SourceSignal,
    SourceStatus,
    build_behavioral_snapshot,
    derive_source_signal,
)
from .behavioral_collection_lineage import (
    BehavioralCollectionLineage,
    BehavioralCollectionReceipt,
    bind_collection_receipt,
)
from .behavioral_engagement_baselines import (
    YOUTUBE_ENGAGEMENT_METRICS,
    EngagementBaselineSignal,
    derive_youtube_engagement_baseline,
)

RECEIPT_SCHEMA_VERSION = "2026-08-20-v1"
CANONICAL_SOURCE_METRICS: dict[BehavioralSource, frozenset[str] | None] = {
    BehavioralSource.GOOGLE_TRENDS: None,
    BehavioralSource.YOUTUBE: frozenset({"NEW_VIDEO_COUNT_24H"}),
    BehavioralSource.SIMILARWEB: None,
}


@dataclass(frozen=True)
class BehavioralCollectionRun:
    entity_id: str
    ticker: str
    as_of: datetime
    snapshot: BehavioralSnapshot
    artifacts: BehavioralArtifactBundle
    receipt: BehavioralCollectionReceipt
    receipt_path: Path
    receipt_sha256: str
    engagement_baselines: tuple[EngagementBaselineSignal, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def run_behavioral_collection(
    *,
    entity: BehavioralEntity,
    lineage: BehavioralCollectionLineage,
    provider_results: tuple[ProviderFetchResult, ...],
    artifact_root: str | Path,
    historical_observations: Iterable[BehavioralObservation] = (),
    supplemental_observations: tuple[BehavioralObservation, ...] = (),
) -> BehavioralCollectionRun:
    """Build and persist one immutable point-in-time Behavioral entity/day bundle."""
    _require_aware(lineage.as_of, "lineage.as_of")
    if entity.version != lineage.entity_dictionary_version:
        raise ValueError("BEHAVIORAL_COLLECTION_ENTITY_DICTIONARY_VERSION_MISMATCH")

    current = _validate_current_provider_results(
        entity=entity,
        lineage=lineage,
        provider_results=provider_results,
        supplemental_observations=supplemental_observations,
    )
    history = _validate_history(
        tuple(historical_observations),
        entity=entity,
        as_of=lineage.as_of,
    )

    signals: list[SourceSignal] = []
    results_by_source = {result.source: result for result in provider_results}
    for dependency in lineage.providers:
        result = results_by_source[dependency.source]
        if result.status != SourceStatus.COMPLETE:
            signals.append(
                _provider_unavailable_signal(
                    dependency.source,
                    as_of=lineage.as_of,
                    status=result.status,
                    reason=result.reason or "PROVIDER_RESULT_NOT_COMPLETE",
                )
            )
            continue

        canonical_rows = _canonical_signal_rows(
            (*history, *current),
            source=dependency.source,
        )
        signals.append(
            derive_source_signal(
                canonical_rows,
                source=dependency.source,
                as_of=lineage.as_of,
            )
        )

    snapshot = build_behavioral_snapshot(
        entity,
        tuple(signals),
        as_of=lineage.as_of,
    )
    _assert_research_only(snapshot)

    current_artifact_rows = _dedupe_observations(current)
    artifacts = write_behavioral_daily_artifacts(
        artifact_root,
        observations=current_artifact_rows,
        snapshot=snapshot,
    )
    receipt = bind_collection_receipt(
        lineage,
        fetch_results=provider_results,
        observations=current_artifact_rows,
        snapshot=snapshot,
        artifacts=artifacts,
    )
    receipt_path, receipt_sha256 = _write_receipt(artifacts.directory, receipt)

    engagement_history = (*history, *current_artifact_rows)
    engagement_baselines = tuple(
        derive_youtube_engagement_baseline(
            engagement_history,
            entity_id=entity.entity_id,
            ticker=entity.ticker,
            metric=metric,
            as_of=lineage.as_of,
        )
        for metric in sorted(YOUTUBE_ENGAGEMENT_METRICS)
    )

    return BehavioralCollectionRun(
        entity_id=entity.entity_id,
        ticker=entity.ticker.upper(),
        as_of=lineage.as_of.astimezone(UTC),
        snapshot=snapshot,
        artifacts=artifacts,
        receipt=receipt,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        engagement_baselines=engagement_baselines,
    )


def load_behavioral_history(
    artifact_root: str | Path,
    *,
    entity: BehavioralEntity,
    as_of: datetime,
    lookback_days: int = 60,
) -> tuple[BehavioralObservation, ...]:
    """Load prior immutable raw observations without inventing missing dates."""
    _require_aware(as_of, "as_of")
    if lookback_days <= 0:
        raise ValueError("BEHAVIORAL_HISTORY_LOOKBACK_DAYS_INVALID")

    root = Path(artifact_root)
    cutoff = as_of.astimezone(UTC)
    earliest = cutoff.date() - timedelta(days=lookback_days)
    rows: list[BehavioralObservation] = []
    if not root.exists():
        return ()

    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day < earliest or day > cutoff.date():
            continue
        observations_path = day_dir / entity.entity_id / "behavioral_observations.jsonl"
        if not observations_path.exists():
            continue
        for line in observations_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(_observation_from_payload(json.loads(line)))

    return _validate_history(tuple(rows), entity=entity, as_of=cutoff)


def _validate_current_provider_results(
    *,
    entity: BehavioralEntity,
    lineage: BehavioralCollectionLineage,
    provider_results: tuple[ProviderFetchResult, ...],
    supplemental_observations: tuple[BehavioralObservation, ...],
) -> tuple[BehavioralObservation, ...]:
    dependencies = {item.source: item for item in lineage.providers}
    results: dict[BehavioralSource, ProviderFetchResult] = {}
    observations: list[BehavioralObservation] = []
    for result in provider_results:
        if result.source in results:
            raise ValueError("BEHAVIORAL_COLLECTION_DUPLICATE_PROVIDER_RESULT")
        dependency = dependencies.get(result.source)
        if dependency is None:
            raise ValueError("BEHAVIORAL_COLLECTION_UNDECLARED_PROVIDER_RESULT")
        if not dependency.configured and result.status == SourceStatus.COMPLETE:
            raise ValueError("BEHAVIORAL_UNCONFIGURED_PROVIDER_RETURNED_COMPLETE")
        if result.status == SourceStatus.COMPLETE and result.reason:
            raise ValueError("BEHAVIORAL_COMPLETE_PROVIDER_CANNOT_HAVE_REASON")
        for row in result.observations:
            _validate_current_observation(
                row,
                entity=entity,
                lineage=lineage,
                expected_source=result.source,
            )
            observations.append(row)
        results[result.source] = result

    if set(results) != set(dependencies):
        raise ValueError("BEHAVIORAL_COLLECTION_PROVIDER_RESULT_SET_MISMATCH")

    for row in supplemental_observations:
        if row.source not in dependencies:
            raise ValueError("BEHAVIORAL_COLLECTION_UNDECLARED_SUPPLEMENTAL_SOURCE")
        _validate_current_observation(
            row,
            entity=entity,
            lineage=lineage,
            expected_source=row.source,
        )
        observations.append(row)
    return _dedupe_observations(tuple(observations))


def _validate_current_observation(
    row: BehavioralObservation,
    *,
    entity: BehavioralEntity,
    lineage: BehavioralCollectionLineage,
    expected_source: BehavioralSource,
) -> None:
    if row.source != expected_source:
        raise ValueError("BEHAVIORAL_COLLECTION_PROVIDER_OBSERVATION_SOURCE_MISMATCH")
    if row.entity_id != entity.entity_id or row.ticker.upper() != entity.ticker.upper():
        raise ValueError("BEHAVIORAL_COLLECTION_OBSERVATION_ENTITY_MISMATCH")
    if row.observed_at > lineage.as_of or row.source_timestamp > lineage.as_of:
        raise ValueError("BEHAVIORAL_COLLECTION_LOOKAHEAD_REJECTED")


def _validate_history(
    rows: tuple[BehavioralObservation, ...],
    *,
    entity: BehavioralEntity,
    as_of: datetime,
) -> tuple[BehavioralObservation, ...]:
    _require_aware(as_of, "as_of")
    for row in rows:
        if row.entity_id != entity.entity_id or row.ticker.upper() != entity.ticker.upper():
            raise ValueError("BEHAVIORAL_HISTORY_ENTITY_MISMATCH")
        if row.observed_at > as_of or row.source_timestamp > as_of:
            raise ValueError("BEHAVIORAL_HISTORY_LOOKAHEAD_REJECTED")
    return _dedupe_observations(rows)


def _canonical_signal_rows(
    rows: Iterable[BehavioralObservation],
    *,
    source: BehavioralSource,
) -> tuple[BehavioralObservation, ...]:
    allowed_metrics = CANONICAL_SOURCE_METRICS[source]
    return tuple(
        row
        for row in rows
        if row.source == source
        and (allowed_metrics is None or row.metric in allowed_metrics)
    )


def _provider_unavailable_signal(
    source: BehavioralSource,
    *,
    as_of: datetime,
    status: SourceStatus,
    reason: str,
) -> SourceSignal:
    return SourceSignal(
        source=source,
        as_of=as_of.astimezone(UTC),
        status=status,
        reason=reason,
        observations_used=0,
        level_7d=None,
        level_28d=None,
        velocity_7d=None,
        prior_velocity_7d=None,
        acceleration=None,
        abnormality_z=None,
        persistence=None,
        prototype_score=None,
    )


def _dedupe_observations(
    rows: tuple[BehavioralObservation, ...],
) -> tuple[BehavioralObservation, ...]:
    unique: dict[tuple[str, str, str, str, str], BehavioralObservation] = {}
    for row in rows:
        prior = unique.get(row.identity)
        if prior is not None and prior != row:
            raise ValueError("BEHAVIORAL_COLLECTION_CONFLICTING_DUPLICATE_OBSERVATION")
        unique[row.identity] = row
    return tuple(sorted(unique.values(), key=lambda row: row.identity))


def _write_receipt(
    directory: Path,
    receipt: BehavioralCollectionReceipt,
) -> tuple[Path, str]:
    payload = _jsonable(asdict(receipt))
    payload["receipt_artifact_schema_version"] = RECEIPT_SCHEMA_VERSION
    raw = (
        json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / "behavioral_collection_receipt.json"
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("BEHAVIORAL_COLLECTION_RECEIPT_IMMUTABILITY_VIOLATION")
    if not path.exists():
        path.write_bytes(raw)
    return path, digest


def _observation_from_payload(payload: dict[str, Any]) -> BehavioralObservation:
    return BehavioralObservation(
        source=BehavioralSource(str(payload["source"])),
        entity_id=str(payload["entity_id"]),
        ticker=str(payload["ticker"]),
        query_key=str(payload["query_key"]),
        metric=str(payload["metric"]),
        observed_at=datetime.fromisoformat(str(payload["observed_at"])),
        source_timestamp=datetime.fromisoformat(str(payload["source_timestamp"])),
        raw_level=float(payload["raw_level"]),
        provenance=str(payload["provenance"]),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        _require_aware(value, "datetime")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _assert_research_only(snapshot: BehavioralSnapshot) -> None:
    if snapshot.research_only is not True:
        raise ValueError("BEHAVIORAL_COLLECTION_RESEARCH_ONLY_REQUIRED")
    if snapshot.trading_authorized is not False or snapshot.live_trading_enabled is not False:
        raise ValueError("BEHAVIORAL_COLLECTION_SAFETY_FLAG_VIOLATION")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
