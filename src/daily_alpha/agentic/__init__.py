"""Daily Alpha Agentic Intelligence research foundation."""

from .contracts import EvidenceContractError, EvidenceRecord, EvidenceStatus, ReadinessStatus
from .durable_evidence import (
    DecisionLineage,
    DurableEvidenceError,
    EvidenceBundle,
    EvidenceSnapshot,
    HistoricalReplayResult,
    InMemoryDurableEvidenceRepository,
    SourceHealthEvent,
    SourceHealthStatus,
    evidence_record_from_payload,
    evidence_record_to_payload,
    source_registry_fingerprint,
)
from .evidence_store import EvidenceConflictError, InMemoryEvidenceStore
from .source_registry import SourcePolicy, SourceRegistry, daily_alpha_v1_registry
from .supervisor import DataSupervisor, ReadinessPacket, SourceAssessment

__all__ = [
    "DataSupervisor",
    "DecisionLineage",
    "DurableEvidenceError",
    "EvidenceBundle",
    "EvidenceConflictError",
    "EvidenceContractError",
    "EvidenceRecord",
    "EvidenceSnapshot",
    "EvidenceStatus",
    "HistoricalReplayResult",
    "InMemoryDurableEvidenceRepository",
    "InMemoryEvidenceStore",
    "ReadinessPacket",
    "ReadinessStatus",
    "SourceAssessment",
    "SourceHealthEvent",
    "SourceHealthStatus",
    "SourcePolicy",
    "SourceRegistry",
    "daily_alpha_v1_registry",
    "evidence_record_from_payload",
    "evidence_record_to_payload",
    "source_registry_fingerprint",
]
