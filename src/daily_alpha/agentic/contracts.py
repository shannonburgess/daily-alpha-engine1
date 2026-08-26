"""Canonical point-in-time contracts for Daily Alpha Agentic Intelligence.

The agentic layer is research/shadow only. Deterministic source data remains authoritative,
and no evidence record may authorize trading or live execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EvidenceContractError(ValueError):
    """Evidence violates the canonical point-in-time contract."""


class EvidenceStatus(StrEnum):
    COMPLETE = "COMPLETE"
    STALE = "STALE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CONFLICT = "CONFLICT"
    DATA_ERROR = "DATA_ERROR"


class ReadinessStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceContractError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    """Return deterministic JSON and reject values that cannot be audited safely."""
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceContractError("EVIDENCE_VALUE_NOT_CANONICAL_JSON") from exc
    return payload


def _normalize_provenance(
    provenance: tuple[tuple[str, str], ...] | dict[str, str],
) -> tuple[tuple[str, str], ...]:
    items = provenance.items() if isinstance(provenance, dict) else provenance
    normalized = tuple(sorted((str(key), str(value)) for key, value in items))
    if len({key for key, _ in normalized}) != len(normalized):
        raise EvidenceContractError("PROVENANCE_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable, source-attributed evidence available at a point in time."""

    symbol: str
    evidence_type: str
    value: Any
    source: str
    observed_at: datetime
    received_at: datetime
    source_version: str
    status: EvidenceStatus = EvidenceStatus.COMPLETE
    confidence: float = 1.0
    reason_code: str | None = None
    provenance: tuple[tuple[str, str], ...] | dict[str, str] = field(default_factory=tuple)
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        evidence_type = self.evidence_type.strip().upper()
        source = self.source.strip().upper()
        source_version = self.source_version.strip()
        if not symbol:
            raise EvidenceContractError("EVIDENCE_SYMBOL_REQUIRED")
        if not evidence_type:
            raise EvidenceContractError("EVIDENCE_TYPE_REQUIRED")
        if not source:
            raise EvidenceContractError("EVIDENCE_SOURCE_REQUIRED")
        if not source_version:
            raise EvidenceContractError("EVIDENCE_SOURCE_VERSION_REQUIRED")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise EvidenceContractError("EVIDENCE_CONFIDENCE_OUT_OF_RANGE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise EvidenceContractError("AGENTIC_FOUNDATION_MUST_REMAIN_RESEARCH_ONLY")

        observed_at = _require_aware(self.observed_at, "OBSERVED_AT")
        received_at = _require_aware(self.received_at, "RECEIVED_AT")
        if received_at < observed_at:
            raise EvidenceContractError("RECEIVED_AT_PRECEDES_OBSERVED_AT")

        _canonical_json(self.value)
        normalized_provenance = _normalize_provenance(self.provenance)

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "evidence_type", evidence_type)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "received_at", received_at)
        object.__setattr__(self, "provenance", normalized_provenance)
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", self.reason_code.strip().upper() or None)

    @property
    def logical_key(self) -> tuple[str, str, str, datetime]:
        """Identity of one source observation before its value/status are considered."""
        return self.symbol, self.evidence_type, self.source, self.observed_at

    @property
    def value_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.value).encode("utf-8")).hexdigest()

    @property
    def evidence_id(self) -> str:
        payload = {
            "symbol": self.symbol,
            "evidence_type": self.evidence_type,
            "value": self.value,
            "source": self.source,
            "observed_at": self.observed_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "source_version": self.source_version,
            "status": self.status.value,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "provenance": list(self.provenance),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        canonical = _canonical_json(payload)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def validate_point_in_time(self, as_of: datetime) -> None:
        boundary = _require_aware(as_of, "AS_OF")
        if self.observed_at > boundary or self.received_at > boundary:
            raise EvidenceContractError("FUTURE_EVIDENCE_NOT_ALLOWED")

    def age_seconds(self, as_of: datetime) -> float:
        boundary = _require_aware(as_of, "AS_OF")
        self.validate_point_in_time(boundary)
        return max(0.0, (boundary - self.observed_at).total_seconds())
