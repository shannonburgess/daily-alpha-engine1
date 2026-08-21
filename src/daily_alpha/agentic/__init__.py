"""Daily Alpha Agentic Intelligence research foundation."""

from .contracts import EvidenceRecord, EvidenceStatus, ReadinessStatus
from .evidence_store import EvidenceConflictError, InMemoryEvidenceStore
from .source_registry import SourcePolicy, SourceRegistry, daily_alpha_v1_registry
from .supervisor import DataSupervisor, ReadinessPacket, SourceAssessment

__all__ = [
    "DataSupervisor",
    "EvidenceConflictError",
    "EvidenceRecord",
    "EvidenceStatus",
    "InMemoryEvidenceStore",
    "ReadinessPacket",
    "ReadinessStatus",
    "SourceAssessment",
    "SourcePolicy",
    "SourceRegistry",
    "daily_alpha_v1_registry",
]
