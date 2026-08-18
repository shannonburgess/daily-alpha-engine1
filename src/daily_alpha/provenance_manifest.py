"""Research/report provenance contract for future commercial-beta artifacts.

This module is intentionally disconnected from publication and execution. It creates a
stable, hashable manifest that can later be attached to customer-visible research
artifacts without containing secrets or customer PII.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

_ALLOWED_BASES = {"NONE", "ACTUAL", "PAPER", "BACKTEST", "HYPOTHETICAL"}
_ALLOWED_ENVIRONMENTS = {"research", "staging", "production"}
_ALLOWED_FRESHNESS = {"FRESH", "STALE", "DATA_ERROR", "DATA_UNAVAILABLE"}


class ProvenanceValidationError(ValueError):
    """Raised when a provenance manifest cannot safely represent its evidence."""


@dataclass(frozen=True, order=True)
class SourceEvidence:
    source_id: str
    source_as_of_at: str
    retrieved_at: str
    freshness_status: str
    evidence_locator: str
    content_sha256: str = ""
    schema_version: str = ""

    def validate(self) -> None:
        for field_name in ("source_id", "source_as_of_at", "retrieved_at", "evidence_locator"):
            if not str(getattr(self, field_name)).strip():
                raise ProvenanceValidationError(f"source evidence requires {field_name}")
        if self.freshness_status not in _ALLOWED_FRESHNESS:
            raise ProvenanceValidationError(
                f"unsupported freshness_status: {self.freshness_status}"
            )
        if self.content_sha256 and len(self.content_sha256) != 64:
            raise ProvenanceValidationError("content_sha256 must be a 64-character hex digest")


@dataclass(frozen=True)
class ReportProvenanceManifest:
    report_id: str
    report_type: str
    generated_at: str
    source_as_of_at: str
    strategy_version: str
    model_version: str
    methodology_version: str
    ranking_schema_version: str
    entitlement_tier: str
    environment: str
    git_commit: str
    build_id: str
    config_hash: str
    performance_basis: str = "NONE"
    benchmark_id: str = ""
    cost_model_version: str = ""
    option_mark_policy: str = ""
    archive_locator: str = ""
    delivery_correlation_id: str = ""
    sources: tuple[SourceEvidence, ...] = ()

    def validate(self) -> None:
        required = (
            "report_id",
            "report_type",
            "generated_at",
            "source_as_of_at",
            "strategy_version",
            "model_version",
            "methodology_version",
            "ranking_schema_version",
            "entitlement_tier",
            "environment",
            "git_commit",
            "build_id",
            "config_hash",
        )
        for field_name in required:
            if not str(getattr(self, field_name)).strip():
                raise ProvenanceValidationError(f"manifest requires {field_name}")
        if self.performance_basis not in _ALLOWED_BASES:
            raise ProvenanceValidationError(
                f"unsupported performance_basis: {self.performance_basis}"
            )
        if self.environment not in _ALLOWED_ENVIRONMENTS:
            raise ProvenanceValidationError(f"unsupported environment: {self.environment}")
        if not self.sources:
            raise ProvenanceValidationError("manifest requires at least one source evidence record")
        for source in self.sources:
            source.validate()
        if self.performance_basis != "NONE" and not self.methodology_version:
            raise ProvenanceValidationError("performance artifacts require methodology_version")

    def canonical_dict(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["sources"] = [asdict(source) for source in sorted(self.sources)]
        return payload

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def evidence_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def immutable_identity(self) -> str:
        """Stable idempotency key for one report/build/evidence combination."""
        raw = (
            f"{self.report_id}|{self.report_type}|{self.strategy_version}|"
            f"{self.model_version}|{self.methodology_version}|{self.git_commit}|"
            f"{self.build_id}|{self.evidence_hash()}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def has_source_failure(self) -> bool:
        return any(
            source.freshness_status in {"STALE", "DATA_ERROR", "DATA_UNAVAILABLE"}
            for source in self.sources
        )

    def customer_safe_footer(self) -> dict[str, str]:
        """Return the small non-sensitive provenance surface safe for a report footer."""
        return {
            "report_id": self.report_id,
            "strategy_version": self.strategy_version,
            "model_version": self.model_version,
            "methodology_version": self.methodology_version,
            "source_as_of_at": self.source_as_of_at,
            "performance_basis": self.performance_basis,
            "evidence_hash": self.evidence_hash(),
            "data_quality": "DEGRADED" if self.has_source_failure() else "OK",
        }


def build_manifest(
    *,
    sources: Iterable[SourceEvidence],
    **kwargs: Any,
) -> ReportProvenanceManifest:
    """Construct and validate a manifest while freezing the source sequence."""
    manifest = ReportProvenanceManifest(sources=tuple(sources), **kwargs)
    manifest.validate()
    return manifest
