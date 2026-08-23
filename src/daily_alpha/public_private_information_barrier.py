from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .opportunity_contracts import (
    InformationClassification,
    InvestmentOpportunityEnvelope,
    MarketDomain,
)


class InformationBarrierError(ValueError):
    """A public/private evidence-use decision violated an information-barrier invariant."""


class InformationBarrierDisposition(StrEnum):
    ALLOW_PUBLIC_RESEARCH = "ALLOW_PUBLIC_RESEARCH"
    BLOCK_PUBLIC_RESEARCH = "BLOCK_PUBLIC_RESEARCH"


class InformationBarrierReason(StrEnum):
    SOURCE_INFORMATION_PUBLIC = "SOURCE_INFORMATION_PUBLIC"
    SOURCE_CONFIDENTIAL = "SOURCE_CONFIDENTIAL"
    SOURCE_MNPI_RESTRICTED = "SOURCE_MNPI_RESTRICTED"
    SOURCE_PUBLIC_USE_NOT_PERMITTED = "SOURCE_PUBLIC_USE_NOT_PERMITTED"
    SOURCE_CONFLICT_PUBLIC_USE_BLOCKED = "SOURCE_CONFLICT_PUBLIC_USE_BLOCKED"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InformationBarrierError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InformationBarrierError(f"{field_name}_REQUIRED")
    return normalized


def _ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_required(value, field_name) for value in values))
    if not normalized:
        raise InformationBarrierError(f"{field_name}_REQUIRED")
    if len(set(normalized)) != len(normalized):
        raise InformationBarrierError(f"{field_name}_MUST_BE_UNIQUE")
    return normalized


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicMarketInformationBarrierDecision:
    """Immutable decision on whether exact source evidence may feed public-market research."""

    as_of: datetime
    policy_id: str
    source_opportunity_id: str
    target_opportunity_id: str
    source_information_classification: InformationClassification
    evidence_ids: tuple[str, ...]
    disposition: InformationBarrierDisposition
    reason_codes: tuple[InformationBarrierReason, ...]
    research_only: bool = True
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "BARRIER_AS_OF"))
        object.__setattr__(self, "policy_id", _required(self.policy_id, "BARRIER_POLICY_ID"))
        object.__setattr__(
            self,
            "source_opportunity_id",
            _required(self.source_opportunity_id, "SOURCE_OPPORTUNITY_ID"),
        )
        object.__setattr__(
            self,
            "target_opportunity_id",
            _required(self.target_opportunity_id, "TARGET_OPPORTUNITY_ID"),
        )
        if self.source_opportunity_id == self.target_opportunity_id:
            raise InformationBarrierError("INFORMATION_BARRIER_SELF_TRANSFER_FORBIDDEN")
        object.__setattr__(
            self,
            "evidence_ids",
            _ids(self.evidence_ids, "BARRIER_EVIDENCE_ID"),
        )
        normalized_reasons = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        if not normalized_reasons:
            raise InformationBarrierError("INFORMATION_BARRIER_REASON_REQUIRED")
        object.__setattr__(self, "reason_codes", normalized_reasons)
        if (
            self.disposition is InformationBarrierDisposition.ALLOW_PUBLIC_RESEARCH
            and self.source_information_classification is not InformationClassification.PUBLIC
        ):
            raise InformationBarrierError("NON_PUBLIC_INFORMATION_CANNOT_BE_ALLOWED_DIRECTLY")
        if (
            not self.research_only
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise InformationBarrierError("INFORMATION_BARRIER_DECISION_HAS_FORBIDDEN_AUTHORITY")

    @property
    def decision_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "policy_id": self.policy_id,
                "source_opportunity_id": self.source_opportunity_id,
                "target_opportunity_id": self.target_opportunity_id,
                "source_information_classification": self.source_information_classification.value,
                "evidence_ids": list(self.evidence_ids),
                "disposition": self.disposition.value,
                "reason_codes": [item.value for item in self.reason_codes],
                "research_only": self.research_only,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


def evaluate_public_market_information_barrier(
    *,
    as_of: datetime,
    policy_id: str,
    source: InvestmentOpportunityEnvelope,
    target: InvestmentOpportunityEnvelope,
    evidence_ids: tuple[str, ...],
) -> PublicMarketInformationBarrierDecision:
    """Evaluate direct evidence use without allowing the shared graph to bypass an information wall."""
    boundary = _aware_utc(as_of, "BARRIER_AS_OF")
    if source.as_of > boundary or target.as_of > boundary:
        raise InformationBarrierError("INFORMATION_BARRIER_CONTAINS_FUTURE_OPPORTUNITY")
    if target.market_domain is not MarketDomain.PUBLIC:
        raise InformationBarrierError("INFORMATION_BARRIER_TARGET_MUST_BE_PUBLIC_MARKET")

    evidence = _ids(evidence_ids, "BARRIER_EVIDENCE_ID")
    source_evidence = set(source.evidence_ids)
    if any(item not in source_evidence for item in evidence):
        raise InformationBarrierError("BARRIER_EVIDENCE_MUST_EXIST_IN_SOURCE_OPPORTUNITY")

    reasons: list[InformationBarrierReason] = []
    blocked = False
    if source.information_classification is InformationClassification.MNPI_RESTRICTED:
        reasons.append(InformationBarrierReason.SOURCE_MNPI_RESTRICTED)
        blocked = True
    elif source.information_classification is InformationClassification.CONFIDENTIAL:
        reasons.append(InformationBarrierReason.SOURCE_CONFIDENTIAL)
        blocked = True
    else:
        reasons.append(InformationBarrierReason.SOURCE_INFORMATION_PUBLIC)

    if not source.public_market_research_use_permitted:
        reasons.append(InformationBarrierReason.SOURCE_PUBLIC_USE_NOT_PERMITTED)
        blocked = True
    if any(not conflict.public_market_use_permitted for conflict in source.conflicts):
        reasons.append(InformationBarrierReason.SOURCE_CONFLICT_PUBLIC_USE_BLOCKED)
        blocked = True

    disposition = (
        InformationBarrierDisposition.BLOCK_PUBLIC_RESEARCH
        if blocked
        else InformationBarrierDisposition.ALLOW_PUBLIC_RESEARCH
    )
    return PublicMarketInformationBarrierDecision(
        as_of=boundary,
        policy_id=policy_id,
        source_opportunity_id=source.opportunity_id,
        target_opportunity_id=target.opportunity_id,
        source_information_classification=source.information_classification,
        evidence_ids=evidence,
        disposition=disposition,
        reason_codes=tuple(reasons),
    )


__all__ = [
    "InformationBarrierDisposition",
    "InformationBarrierError",
    "InformationBarrierReason",
    "PublicMarketInformationBarrierDecision",
    "evaluate_public_market_information_barrier",
]
