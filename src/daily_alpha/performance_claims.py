"""Fail-closed performance evidence and customer-facing claim governance.

This module does not determine whether a regulatory regime applies and does not
represent legal approval. It creates an auditable repository gate so Daily Alpha
cannot accidentally present unsupported or ambiguously labeled performance claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class EvidenceBasis(StrEnum):
    ACTUAL = "ACTUAL"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    HYPOTHETICAL = "HYPOTHETICAL"


class ClaimChannel(StrEnum):
    NEWSLETTER = "NEWSLETTER"
    DASHBOARD = "DASHBOARD"
    WEBSITE = "WEBSITE"
    SALES_MATERIAL = "SALES_MATERIAL"
    INTERNAL = "INTERNAL"


class ClaimReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    INTERNAL_EVIDENCE_READY = "INTERNAL_EVIDENCE_READY"
    EXTERNAL_REVIEW_COMPLETE = "EXTERNAL_REVIEW_COMPLETE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PerformanceEvidence:
    evidence_id: str
    basis: EvidenceBasis
    metric_name: str
    period_start: str
    period_end: str
    as_of: str
    methodology_version: str
    source_hash: str
    sample_size: int
    gross_value: float | None
    net_value: float | None
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        start = date.fromisoformat(self.period_start)
        end = date.fromisoformat(self.period_end)
        datetime.fromisoformat(self.as_of)
        if end < start:
            raise ValueError("performance evidence period_end cannot precede period_start")
        if not all(
            (
                self.evidence_id,
                self.metric_name,
                self.methodology_version,
                self.source_hash,
            )
        ):
            raise ValueError("performance evidence identity and lineage are required")
        if len(self.source_hash) != 64:
            raise ValueError("source_hash must be a 64-character content hash")
        if self.sample_size <= 0:
            raise ValueError("sample_size must be positive")
        if self.gross_value is None and self.net_value is None:
            raise ValueError("at least one performance value is required")
        if self.basis in {EvidenceBasis.BACKTEST, EvidenceBasis.HYPOTHETICAL}:
            if not self.assumptions or not self.limitations:
                raise ValueError(
                    "backtest/hypothetical evidence requires assumptions and limitations"
                )


@dataclass(frozen=True)
class MarketingClaim:
    claim_id: str
    text: str
    channel: ClaimChannel
    audience: str
    created_at: str
    expires_on: str
    evidence_ids: tuple[str, ...]
    displayed_basis: EvidenceBasis
    risks_and_limitations: tuple[str, ...]
    review_status: ClaimReviewStatus = ClaimReviewStatus.DRAFT
    external_review_reference: str | None = None

    def __post_init__(self) -> None:
        created = datetime.fromisoformat(self.created_at)
        expires = date.fromisoformat(self.expires_on)
        if expires < created.date():
            raise ValueError("claim expiration cannot precede creation")
        if not all((self.claim_id, self.text, self.audience, self.evidence_ids)):
            raise ValueError("claim identity, text, audience, and evidence are required")
        if not self.risks_and_limitations:
            raise ValueError("customer-facing claims require risks and limitations")
        if (
            self.review_status == ClaimReviewStatus.EXTERNAL_REVIEW_COMPLETE
            and not self.external_review_reference
        ):
            raise ValueError("external review completion requires an auditable reference")


@dataclass(frozen=True)
class ClaimGateResult:
    allowed: bool
    reasons: tuple[str, ...]


def evaluate_customer_claim(
    *,
    claim: MarketingClaim,
    evidence: tuple[PerformanceEvidence, ...],
    as_of: str,
) -> ClaimGateResult:
    """Evaluate a fail-closed repository gate for a customer-facing claim.

    Passing this function only means the repository evidence controls passed. It
    does not mean a claim is legally permissible or regulator-approved.
    """

    current_date = date.fromisoformat(as_of)
    reasons: list[str] = []
    evidence_by_id = {item.evidence_id: item for item in evidence}

    missing_ids = [item for item in claim.evidence_ids if item not in evidence_by_id]
    if missing_ids:
        reasons.append("MISSING_EVIDENCE")

    selected = [evidence_by_id[item] for item in claim.evidence_ids if item in evidence_by_id]
    bases = {item.basis for item in selected}
    if len(bases) > 1:
        reasons.append("MIXED_PERFORMANCE_BASES")
    elif bases and claim.displayed_basis not in bases:
        reasons.append("MISLABELED_PERFORMANCE_BASIS")

    if date.fromisoformat(claim.expires_on) < current_date:
        reasons.append("CLAIM_EVIDENCE_EXPIRED")

    if claim.channel != ClaimChannel.INTERNAL:
        if claim.review_status != ClaimReviewStatus.EXTERNAL_REVIEW_COMPLETE:
            reasons.append("EXTERNAL_REVIEW_REQUIRED")
        if not claim.external_review_reference:
            reasons.append("EXTERNAL_REVIEW_REFERENCE_REQUIRED")

    if selected and any(not item.limitations for item in selected):
        reasons.append("EVIDENCE_LIMITATIONS_MISSING")

    if claim.displayed_basis in {EvidenceBasis.BACKTEST, EvidenceBasis.HYPOTHETICAL}:
        if not all(item.assumptions for item in selected):
            reasons.append("HYPOTHETICAL_ASSUMPTIONS_MISSING")

    if reasons:
        return ClaimGateResult(False, tuple(dict.fromkeys(reasons)))
    return ClaimGateResult(True, ("EVIDENCE_GATE_PASSED_EXTERNAL_LEGAL_REVIEW_STILL_REQUIRED",))
