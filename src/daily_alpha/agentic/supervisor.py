"""Deterministic data-readiness supervisor for Agentic Intelligence V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .contracts import EvidenceContractError, EvidenceRecord, EvidenceStatus, ReadinessStatus
from .evidence_store import InMemoryEvidenceStore
from .source_registry import SourcePolicy, SourceRegistry


@dataclass(frozen=True)
class SourceAssessment:
    source: str
    evidence_type: str
    required: bool
    status: EvidenceStatus
    age_seconds: float | None
    confidence: float
    reason_code: str | None
    evidence_id: str | None


@dataclass(frozen=True)
class ReadinessPacket:
    symbol: str
    as_of: datetime
    status: ReadinessStatus
    completeness_score: float
    freshness_score: float
    data_confidence_score: float
    assessments: tuple[SourceAssessment, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["status"] = self.status.value
        for assessment in payload["assessments"]:
            assessment["status"] = assessment["status"].value
        return payload


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceContractError("AS_OF_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _effective_status(
    record: EvidenceRecord,
    policy: SourcePolicy,
    as_of: datetime,
) -> tuple[EvidenceStatus, float]:
    record.validate_point_in_time(as_of)
    age = record.age_seconds(as_of)
    if record.status is EvidenceStatus.COMPLETE and age > policy.max_freshness_seconds:
        return EvidenceStatus.STALE, age
    return record.status, age


class DataSupervisor:
    """Evaluate source coverage without making or authorizing a trading decision."""

    def __init__(self, *, registry: SourceRegistry, store: InMemoryEvidenceStore) -> None:
        self.registry = registry
        self.store = store

    def evaluate(self, symbol: str, as_of: datetime) -> ReadinessPacket:
        ticker = symbol.strip().upper()
        if not ticker:
            raise EvidenceContractError("SUPERVISOR_SYMBOL_REQUIRED")
        boundary = _aware_utc(as_of)

        assessments: list[SourceAssessment] = []
        blockers: list[str] = []
        warnings: list[str] = []
        record_lookup: dict[tuple[str, str], EvidenceRecord] = {}
        total_slots = 0
        complete_slots = 0
        freshness_values: list[float] = []
        confidence_values: list[float] = []

        for policy in self.registry.policies():
            for evidence_type in policy.evidence_types:
                total_slots += 1
                record = self.store.latest(
                    symbol=ticker,
                    evidence_type=evidence_type,
                    source=policy.source,
                    as_of=boundary,
                )
                if record is None:
                    assessment = SourceAssessment(
                        source=policy.source,
                        evidence_type=evidence_type,
                        required=policy.required,
                        status=EvidenceStatus.SOURCE_UNAVAILABLE,
                        age_seconds=None,
                        confidence=0.0,
                        reason_code=(
                            "MISSING_REQUIRED_EVIDENCE"
                            if policy.required
                            else "OPTIONAL_EVIDENCE_NOT_PRESENT"
                        ),
                        evidence_id=None,
                    )
                    assessments.append(assessment)
                    freshness_values.append(0.0)
                    confidence_values.append(0.0)
                    if policy.required:
                        blockers.append(f"MISSING_REQUIRED_EVIDENCE:{policy.source}:{evidence_type}")
                    continue

                status, age = _effective_status(record, policy, boundary)
                record_lookup[(policy.source, evidence_type)] = record
                if status is EvidenceStatus.COMPLETE:
                    complete_slots += 1
                freshness_values.append(
                    max(0.0, min(1.0, 1.0 - age / policy.max_freshness_seconds))
                )
                confidence_values.append(record.confidence if status is EvidenceStatus.COMPLETE else 0.0)
                assessment = SourceAssessment(
                    source=policy.source,
                    evidence_type=evidence_type,
                    required=policy.required,
                    status=status,
                    age_seconds=age,
                    confidence=record.confidence,
                    reason_code=record.reason_code,
                    evidence_id=record.evidence_id,
                )
                assessments.append(assessment)

                if status in policy.fail_closed_statuses:
                    reason = f"{status.value}:{policy.source}:{evidence_type}"
                    if policy.required:
                        blockers.append(reason)
                    else:
                        warnings.append(reason)

        blockers.extend(self._agreement_blockers(record_lookup, boundary))

        completeness = 100.0 if total_slots == 0 else 100.0 * complete_slots / total_slots
        freshness = (
            100.0 * sum(freshness_values) / len(freshness_values) if freshness_values else 100.0
        )
        confidence = (
            100.0 * sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 100.0
        )

        if blockers:
            readiness = ReadinessStatus.BLOCKED
        elif warnings:
            readiness = ReadinessStatus.WARNING
        else:
            readiness = ReadinessStatus.PASS

        return ReadinessPacket(
            symbol=ticker,
            as_of=boundary,
            status=readiness,
            completeness_score=round(completeness, 3),
            freshness_score=round(freshness, 3),
            data_confidence_score=round(confidence, 3),
            assessments=tuple(
                sorted(assessments, key=lambda item: (item.evidence_type, item.source))
            ),
            blockers=tuple(sorted(set(blockers))),
            warnings=tuple(sorted(set(warnings))),
        )

    def _agreement_blockers(
        self,
        records: dict[tuple[str, str], EvidenceRecord],
        as_of: datetime,
    ) -> list[str]:
        blockers: list[str] = []
        evidence_types = sorted(
            {
                evidence_type
                for policy in self.registry.policies()
                if policy.requires_cross_source_agreement
                for evidence_type in policy.evidence_types
            }
        )
        for evidence_type in evidence_types:
            hashes: set[str] = set()
            sources: list[str] = []
            for policy in self.registry.policies_for(evidence_type):
                if not policy.requires_cross_source_agreement:
                    continue
                record = records.get((policy.source, evidence_type))
                if record is None:
                    continue
                status, _ = _effective_status(record, policy, as_of)
                if status is not EvidenceStatus.COMPLETE:
                    continue
                hashes.add(record.value_hash)
                sources.append(policy.source)
            if len(hashes) > 1:
                blockers.append(
                    f"CROSS_SOURCE_CONFLICT:{evidence_type}:{','.join(sorted(sources))}"
                )
        return blockers
