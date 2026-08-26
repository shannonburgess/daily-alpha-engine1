"""Durable point-in-time evidence lineage for Agentic Intelligence V1.

This module defines backend-neutral immutable snapshot, bundle, source-health, and
historical replay contracts. It remains research/shadow only and does not deploy AWS,
mutate trading state, or authorize execution.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import EvidenceContractError, EvidenceRecord, EvidenceStatus, ReadinessStatus
from .evidence_store import EvidenceConflictError, InMemoryEvidenceStore
from .source_registry import SourceRegistry
from .supervisor import DataSupervisor, ReadinessPacket


class DurableEvidenceError(EvidenceContractError):
    """Durable evidence persistence or lineage contract failed."""


class SourceHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICT = "CONFLICT"
    DATA_ERROR = "DATA_ERROR"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DurableEvidenceError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DurableEvidenceError("DURABLE_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def source_registry_fingerprint(registry: SourceRegistry) -> str:
    """Return a deterministic fingerprint of the exact source-policy contract."""
    payload = []
    for policy in registry.policies():
        payload.append(
            {
                "source": policy.source,
                "owner": policy.owner,
                "evidence_types": list(policy.evidence_types),
                "cadence_seconds": policy.cadence_seconds,
                "max_freshness_seconds": policy.max_freshness_seconds,
                "required": policy.required,
                "requires_cross_source_agreement": policy.requires_cross_source_agreement,
                "fail_closed_statuses": [status.value for status in policy.fail_closed_statuses],
            }
        )
    return _digest(payload)


@dataclass(frozen=True)
class SourceHealthEvent:
    """Immutable operational evidence about one source at a point in time."""

    source: str
    observed_at: datetime
    status: SourceHealthStatus
    evidence_type: str | None = None
    reason_code: str | None = None
    detail: str | None = None
    related_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        source = self.source.strip().upper()
        if not source:
            raise DurableEvidenceError("SOURCE_HEALTH_SOURCE_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DurableEvidenceError("DURABLE_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "SOURCE_HEALTH_OBSERVED_AT"))
        if self.evidence_type is not None:
            object.__setattr__(self, "evidence_type", self.evidence_type.strip().upper() or None)
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", self.reason_code.strip().upper() or None)
        object.__setattr__(self, "related_evidence_ids", tuple(sorted(set(self.related_evidence_ids))))

    @property
    def health_event_id(self) -> str:
        return _digest(
            {
                "source": self.source,
                "observed_at": self.observed_at.isoformat(),
                "status": self.status.value,
                "evidence_type": self.evidence_type,
                "reason_code": self.reason_code,
                "detail": self.detail,
                "related_evidence_ids": list(self.related_evidence_ids),
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Exact evidence set that was available for one symbol at an as-of boundary."""

    symbol: str
    as_of: datetime
    evidence_ids: tuple[str, ...]
    schema_version: str = "AGENTIC_EVIDENCE_SNAPSHOT_V1"
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise DurableEvidenceError("SNAPSHOT_SYMBOL_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DurableEvidenceError("DURABLE_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        evidence_ids = tuple(sorted(set(self.evidence_ids)))
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "SNAPSHOT_AS_OF"))
        object.__setattr__(self, "evidence_ids", evidence_ids)

    @property
    def snapshot_id(self) -> str:
        return _digest(
            {
                "schema_version": self.schema_version,
                "symbol": self.symbol,
                "as_of": self.as_of.isoformat(),
                "evidence_ids": list(self.evidence_ids),
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class EvidenceBundle:
    """Decision-ready identity binding evidence, source policy, health, and readiness."""

    snapshot_id: str
    registry_fingerprint: str
    readiness_status: ReadinessStatus
    readiness_hash: str
    health_event_ids: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = "AGENTIC_EVIDENCE_BUNDLE_V1"
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise DurableEvidenceError("BUNDLE_SNAPSHOT_ID_REQUIRED")
        if not self.registry_fingerprint.strip():
            raise DurableEvidenceError("BUNDLE_REGISTRY_FINGERPRINT_REQUIRED")
        if not self.readiness_hash.strip():
            raise DurableEvidenceError("BUNDLE_READINESS_HASH_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DurableEvidenceError("DURABLE_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "health_event_ids", tuple(sorted(set(self.health_event_ids))))

    @property
    def bundle_id(self) -> str:
        return _digest(
            {
                "schema_version": self.schema_version,
                "snapshot_id": self.snapshot_id,
                "registry_fingerprint": self.registry_fingerprint,
                "readiness_status": self.readiness_status.value,
                "readiness_hash": self.readiness_hash,
                "health_event_ids": list(self.health_event_ids),
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class DecisionLineage:
    """Immutable research decision identity bound to one evidence bundle.

    Stage 3 does not make a decision. This contract gives later CIO/model layers a
    deterministic place to bind their output to the exact evidence they saw.
    """

    symbol: str
    decision_at: datetime
    decision_type: str
    decision_value: str
    evidence_bundle_id: str
    model_id: str
    model_version: str
    parent_decision_id: str | None = None
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        decision_type = self.decision_type.strip().upper()
        decision_value = self.decision_value.strip().upper()
        model_id = self.model_id.strip().upper()
        model_version = self.model_version.strip()
        if not all((symbol, decision_type, decision_value, self.evidence_bundle_id.strip(), model_id, model_version)):
            raise DurableEvidenceError("DECISION_LINEAGE_FIELDS_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise DurableEvidenceError("DURABLE_EVIDENCE_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "decision_type", decision_type)
        object.__setattr__(self, "decision_value", decision_value)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", model_version)
        object.__setattr__(self, "decision_at", _aware_utc(self.decision_at, "DECISION_AT"))

    @property
    def logical_key(self) -> tuple[str, datetime, str, str]:
        return self.symbol, self.decision_at, self.decision_type, self.model_id

    @property
    def decision_id(self) -> str:
        return _digest(
            {
                "symbol": self.symbol,
                "decision_at": self.decision_at.isoformat(),
                "decision_type": self.decision_type,
                "decision_value": self.decision_value,
                "evidence_bundle_id": self.evidence_bundle_id,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "parent_decision_id": self.parent_decision_id,
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class HistoricalReplayResult:
    snapshot: EvidenceSnapshot
    bundle: EvidenceBundle
    readiness: ReadinessPacket
    evidence: tuple[EvidenceRecord, ...]
    health_events: tuple[SourceHealthEvent, ...]


class InMemoryDurableEvidenceRepository:
    """Backend-neutral reference repository proving immutable durable semantics.

    S3/Dynamo adapters can later implement this same contract. This reference keeps
    Stage 3 local/repo-only while proving exact IDs, point-in-time snapshots, health
    lineage, and replay behavior.
    """

    def __init__(self) -> None:
        self.evidence_store = InMemoryEvidenceStore()
        self._snapshots: dict[str, EvidenceSnapshot] = {}
        self._health_by_id: dict[str, SourceHealthEvent] = {}
        self._health_by_source: dict[str, set[str]] = defaultdict(set)
        self._bundles: dict[str, EvidenceBundle] = {}
        self._lineage_by_id: dict[str, DecisionLineage] = {}
        self._lineage_logical_ids: dict[tuple[str, datetime, str, str], str] = {}

    def append_evidence(self, record: EvidenceRecord) -> str:
        return self.evidence_store.put(record)

    def append_evidence_many(self, records: tuple[EvidenceRecord, ...]) -> tuple[str, ...]:
        return self.evidence_store.put_many(records)

    def append_health(self, event: SourceHealthEvent) -> str:
        event_id = event.health_event_id
        self._health_by_id.setdefault(event_id, event)
        self._health_by_source[event.source].add(event_id)
        return event_id

    def health_as_of(self, as_of: datetime) -> tuple[SourceHealthEvent, ...]:
        boundary = _aware_utc(as_of, "HEALTH_AS_OF")
        events = [event for event in self._health_by_id.values() if event.observed_at <= boundary]
        return tuple(sorted(events, key=lambda event: (event.source, event.observed_at, event.health_event_id)))

    def create_snapshot(self, symbol: str, as_of: datetime) -> EvidenceSnapshot:
        boundary = _aware_utc(as_of, "SNAPSHOT_AS_OF")
        records = self.evidence_store.records_for_symbol(symbol, boundary)
        snapshot = EvidenceSnapshot(
            symbol=symbol,
            as_of=boundary,
            evidence_ids=tuple(record.evidence_id for record in records),
        )
        self._snapshots.setdefault(snapshot.snapshot_id, snapshot)
        return self._snapshots[snapshot.snapshot_id]

    def get_snapshot(self, snapshot_id: str) -> EvidenceSnapshot:
        try:
            return self._snapshots[snapshot_id]
        except KeyError as exc:
            raise DurableEvidenceError(f"SNAPSHOT_ID_NOT_FOUND:{snapshot_id}") from exc

    def records_for_snapshot(self, snapshot_id: str) -> tuple[EvidenceRecord, ...]:
        snapshot = self.get_snapshot(snapshot_id)
        return tuple(self.evidence_store.get(evidence_id) for evidence_id in snapshot.evidence_ids)

    def create_bundle(self, snapshot_id: str, registry: SourceRegistry) -> EvidenceBundle:
        snapshot = self.get_snapshot(snapshot_id)
        replay_store = InMemoryEvidenceStore()
        replay_store.put_many(self.records_for_snapshot(snapshot_id))
        readiness = DataSupervisor(registry=registry, store=replay_store).evaluate(
            snapshot.symbol,
            snapshot.as_of,
        )
        relevant_health = self.health_as_of(snapshot.as_of)
        bundle = EvidenceBundle(
            snapshot_id=snapshot.snapshot_id,
            registry_fingerprint=source_registry_fingerprint(registry),
            readiness_status=readiness.status,
            readiness_hash=_digest(readiness.to_dict()),
            health_event_ids=tuple(event.health_event_id for event in relevant_health),
        )
        self._bundles.setdefault(bundle.bundle_id, bundle)
        return self._bundles[bundle.bundle_id]

    def get_bundle(self, bundle_id: str) -> EvidenceBundle:
        try:
            return self._bundles[bundle_id]
        except KeyError as exc:
            raise DurableEvidenceError(f"BUNDLE_ID_NOT_FOUND:{bundle_id}") from exc

    def append_lineage(self, lineage: DecisionLineage) -> str:
        existing_id = self._lineage_logical_ids.get(lineage.logical_key)
        if existing_id is not None and existing_id != lineage.decision_id:
            raise EvidenceConflictError(
                "DECISION_LINEAGE_IMMUTABILITY_VIOLATION:"
                f"{lineage.symbol}:{lineage.decision_type}:{lineage.model_id}"
            )
        self._lineage_by_id.setdefault(lineage.decision_id, lineage)
        self._lineage_logical_ids.setdefault(lineage.logical_key, lineage.decision_id)
        return lineage.decision_id

    def get_lineage(self, decision_id: str) -> DecisionLineage:
        try:
            return self._lineage_by_id[decision_id]
        except KeyError as exc:
            raise DurableEvidenceError(f"DECISION_ID_NOT_FOUND:{decision_id}") from exc

    def replay(self, snapshot_id: str, registry: SourceRegistry) -> HistoricalReplayResult:
        snapshot = self.get_snapshot(snapshot_id)
        evidence = self.records_for_snapshot(snapshot_id)
        replay_store = InMemoryEvidenceStore()
        replay_store.put_many(evidence)
        readiness = DataSupervisor(registry=registry, store=replay_store).evaluate(
            snapshot.symbol,
            snapshot.as_of,
        )
        bundle = self.create_bundle(snapshot_id, registry)
        health_events = tuple(
            self._health_by_id[event_id]
            for event_id in bundle.health_event_ids
            if event_id in self._health_by_id
        )
        return HistoricalReplayResult(
            snapshot=snapshot,
            bundle=bundle,
            readiness=readiness,
            evidence=evidence,
            health_events=health_events,
        )


def evidence_record_to_payload(record: EvidenceRecord) -> dict[str, Any]:
    """Canonical wire representation suitable for future S3/Dynamo persistence."""
    return {
        "evidence_id": record.evidence_id,
        "symbol": record.symbol,
        "evidence_type": record.evidence_type,
        "value": record.value,
        "source": record.source,
        "observed_at": record.observed_at.isoformat(),
        "received_at": record.received_at.isoformat(),
        "source_version": record.source_version,
        "status": record.status.value,
        "confidence": record.confidence,
        "reason_code": record.reason_code,
        "provenance": dict(record.provenance),
        "research_only": record.research_only,
        "trading_authorized": record.trading_authorized,
        "live_trading_enabled": record.live_trading_enabled,
    }


def evidence_record_from_payload(payload: dict[str, Any]) -> EvidenceRecord:
    """Rehydrate a canonical record and verify the stored immutable identity."""
    try:
        record = EvidenceRecord(
            symbol=str(payload["symbol"]),
            evidence_type=str(payload["evidence_type"]),
            value=payload["value"],
            source=str(payload["source"]),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            received_at=datetime.fromisoformat(str(payload["received_at"])),
            source_version=str(payload["source_version"]),
            status=EvidenceStatus(str(payload["status"])),
            confidence=float(payload["confidence"]),
            reason_code=(None if payload.get("reason_code") is None else str(payload["reason_code"])),
            provenance={str(key): str(value) for key, value in dict(payload.get("provenance") or {}).items()},
            research_only=bool(payload.get("research_only", True)),
            trading_authorized=bool(payload.get("trading_authorized", False)),
            live_trading_enabled=bool(payload.get("live_trading_enabled", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DurableEvidenceError("EVIDENCE_PAYLOAD_INVALID") from exc
    stored_id = str(payload.get("evidence_id") or "")
    if stored_id and stored_id != record.evidence_id:
        raise DurableEvidenceError("EVIDENCE_PAYLOAD_ID_MISMATCH")
    return record
