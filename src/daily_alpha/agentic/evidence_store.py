"""Evidence-store contracts for point-in-time Agentic Intelligence research."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from .contracts import EvidenceContractError, EvidenceRecord


class EvidenceConflictError(EvidenceContractError):
    """A logical source observation was rewritten with different evidence."""


class InMemoryEvidenceStore:
    """Deterministic immutable store used by tests and local research.

    Production persistence can later implement the same behavior with S3/DynamoDB.
    The important contract is immutability and point-in-time retrieval, not the backend.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, EvidenceRecord] = {}
        self._logical_ids: dict[tuple[str, str, str, datetime], str] = {}
        self._symbol_ids: dict[str, set[str]] = defaultdict(set)

    def put(self, record: EvidenceRecord) -> str:
        evidence_id = record.evidence_id
        existing_id = self._logical_ids.get(record.logical_key)
        if existing_id is not None and existing_id != evidence_id:
            raise EvidenceConflictError(
                "EVIDENCE_IMMUTABILITY_VIOLATION:"
                f"{record.symbol}:{record.evidence_type}:{record.source}"
            )
        self._by_id.setdefault(evidence_id, record)
        self._logical_ids.setdefault(record.logical_key, evidence_id)
        self._symbol_ids[record.symbol].add(evidence_id)
        return evidence_id

    def put_many(self, records: Iterable[EvidenceRecord]) -> tuple[str, ...]:
        return tuple(self.put(record) for record in records)

    def get(self, evidence_id: str) -> EvidenceRecord:
        try:
            return self._by_id[evidence_id]
        except KeyError as exc:
            raise EvidenceContractError(f"EVIDENCE_ID_NOT_FOUND:{evidence_id}") from exc

    def records_for_symbol(self, symbol: str, as_of: datetime) -> tuple[EvidenceRecord, ...]:
        ticker = symbol.strip().upper()
        records: list[EvidenceRecord] = []
        for evidence_id in self._symbol_ids.get(ticker, set()):
            record = self._by_id[evidence_id]
            if record.observed_at <= as_of and record.received_at <= as_of:
                records.append(record)
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.evidence_type,
                    item.source,
                    item.observed_at,
                    item.received_at,
                    item.evidence_id,
                ),
            )
        )

    def latest(
        self,
        *,
        symbol: str,
        evidence_type: str,
        source: str,
        as_of: datetime,
    ) -> EvidenceRecord | None:
        ticker = symbol.strip().upper()
        kind = evidence_type.strip().upper()
        source_key = source.strip().upper()
        candidates = [
            record
            for record in self.records_for_symbol(ticker, as_of)
            if record.evidence_type == kind and record.source == source_key
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.observed_at, item.received_at, item.evidence_id),
        )
