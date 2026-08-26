"""Asset-neutral public/private investment opportunity contracts.

These contracts are deliberately below signal generation, CIO/Fusion, portfolio construction,
risk governance, customer decision, and execution. They provide one deterministic language for
public-market and private-market opportunities so ConvexRidge products and future investment
vehicles can share evidence, thesis, conflict, and lineage semantics without sharing authority.

Nothing in this module can authorize capital, place an order, or enable live trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class OpportunityContractError(ValueError):
    """An opportunity contract violated an identity, evidence, or authority invariant."""


class MarketDomain(StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class PrimaryAssetClass(StrEnum):
    EQUITY = "EQUITY"
    FIXED_INCOME_CREDIT = "FIXED_INCOME_CREDIT"
    COMMODITY = "COMMODITY"
    DIGITAL_ASSET = "DIGITAL_ASSET"
    FX_CASH_RESERVE = "FX_CASH_RESERVE"


class InstrumentType(StrEnum):
    SHARE = "SHARE"
    ETF = "ETF"
    OPTION = "OPTION"
    BOND = "BOND"
    TREASURY = "TREASURY"
    CREDIT = "CREDIT"
    FUTURE = "FUTURE"
    FX = "FX"
    CASH = "CASH"
    RESERVE = "RESERVE"
    DIGITAL_ASSET = "DIGITAL_ASSET"
    PRIVATE_COMPANY_EQUITY = "PRIVATE_COMPANY_EQUITY"
    SAFE = "SAFE"
    CONVERTIBLE_NOTE = "CONVERTIBLE_NOTE"
    FUND_INTEREST = "FUND_INTEREST"
    OTHER = "OTHER"


class InvestmentDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class EligibilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class LiquidityState(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class InformationClassification(StrEnum):
    PUBLIC = "PUBLIC"
    CONFIDENTIAL = "CONFIDENTIAL"
    MNPI_RESTRICTED = "MNPI_RESTRICTED"


class ConflictType(StrEnum):
    VENTURE_HOLDING = "VENTURE_HOLDING"
    PUBLIC_MARKET_HOLDING = "PUBLIC_MARKET_HOLDING"
    BOARD_ROLE = "BOARD_ROLE"
    ADVISORY_RELATIONSHIP = "ADVISORY_RELATIONSHIP"
    COMMERCIAL_RELATIONSHIP = "COMMERCIAL_RELATIONSHIP"
    OTHER = "OTHER"


class BusinessLine(StrEnum):
    PLATFORM_RESEARCH = "PLATFORM_RESEARCH"
    PUBLIC_ASSET_MANAGEMENT = "PUBLIC_ASSET_MANAGEMENT"
    VENTURE_CAPITAL = "VENTURE_CAPITAL"
    OTHER = "OTHER"


class VehicleType(StrEnum):
    RESEARCH_PLATFORM = "RESEARCH_PLATFORM"
    PUBLIC_MARKETS_FUND = "PUBLIC_MARKETS_FUND"
    VENTURE_FUND = "VENTURE_FUND"
    MANAGED_ACCOUNT = "MANAGED_ACCOUNT"
    OTHER = "OTHER"


class OpportunityRelationship(StrEnum):
    PRIMARY_EXPRESSION = "PRIMARY_EXPRESSION"
    ALTERNATIVE_EXPRESSION = "ALTERNATIVE_EXPRESSION"
    SUPPLIER = "SUPPLIER"
    CUSTOMER = "CUSTOMER"
    BOTTLENECK_SOLVER = "BOTTLENECK_SOLVER"
    HEDGE = "HEDGE"
    OTHER = "OTHER"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OpportunityContractError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _required(value: str, field_name: str, *, upper: bool = False) -> str:
    normalized = value.strip()
    if not normalized:
        raise OpportunityContractError(f"{field_name}_REQUIRED")
    return normalized.upper() if upper else normalized


def _normalized_ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(sorted({_required(value, field_name) for value in values}))
    if len(normalized) != len(values):
        raise OpportunityContractError(f"{field_name}_MUST_BE_UNIQUE")
    return normalized


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
        raise OpportunityContractError("OPPORTUNITY_VALUE_NOT_CANONICAL_JSON") from exc


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InvestmentVehicleContext:
    """Opaque legal/business scope carried with research without granting authority."""

    as_of: datetime
    business_line: BusinessLine
    vehicle_type: VehicleType
    legal_entity_id: str
    vehicle_id: str
    mandate_id: str
    conflict_policy_id: str
    information_barrier_policy_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "VEHICLE_AS_OF"))
        for field_name in (
            "legal_entity_id",
            "vehicle_id",
            "mandate_id",
            "conflict_policy_id",
            "information_barrier_policy_id",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name.upper()))

    @property
    def context_id(self) -> str:
        return _hash_payload(
            {
                "as_of": self.as_of.isoformat(),
                "business_line": self.business_line.value,
                "vehicle_type": self.vehicle_type.value,
                "legal_entity_id": self.legal_entity_id,
                "vehicle_id": self.vehicle_id,
                "mandate_id": self.mandate_id,
                "conflict_policy_id": self.conflict_policy_id,
                "information_barrier_policy_id": self.information_barrier_policy_id,
            }
        )


@dataclass(frozen=True)
class PrivateMarketTerms:
    """Optional point-in-time financing context for a private-market opportunity."""

    stage: str
    financing_instrument: InstrumentType
    source_evidence_ids: tuple[str, ...]
    post_money_valuation: float | None = None
    round_size: float | None = None
    ownership_target: float | None = None
    expected_liquidity_horizon_months: int | None = None

    def __post_init__(self) -> None:
        stage = _required(self.stage, "PRIVATE_STAGE", upper=True)
        evidence = _normalized_ids(self.source_evidence_ids, "PRIVATE_EVIDENCE_ID")
        if self.financing_instrument not in {
            InstrumentType.PRIVATE_COMPANY_EQUITY,
            InstrumentType.SAFE,
            InstrumentType.CONVERTIBLE_NOTE,
            InstrumentType.FUND_INTEREST,
            InstrumentType.CREDIT,
            InstrumentType.OTHER,
        }:
            raise OpportunityContractError("PRIVATE_FINANCING_INSTRUMENT_INVALID")
        for value, field_name in (
            (self.post_money_valuation, "PRIVATE_POST_MONEY_VALUATION"),
            (self.round_size, "PRIVATE_ROUND_SIZE"),
        ):
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise OpportunityContractError(f"{field_name}_INVALID")
        if self.ownership_target is not None and (
            not math.isfinite(self.ownership_target) or not 0.0 <= self.ownership_target <= 1.0
        ):
            raise OpportunityContractError("PRIVATE_OWNERSHIP_TARGET_OUT_OF_RANGE")
        if self.expected_liquidity_horizon_months is not None and self.expected_liquidity_horizon_months < 0:
            raise OpportunityContractError("PRIVATE_LIQUIDITY_HORIZON_INVALID")
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "source_evidence_ids", evidence)


@dataclass(frozen=True)
class ConflictDisclosure:
    """Explicit relationship that downstream governance must preserve and disclose."""

    as_of: datetime
    conflict_type: ConflictType
    subject_id: str
    related_entity_id: str
    evidence_ids: tuple[str, ...]
    public_market_use_permitted: bool
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "CONFLICT_AS_OF"))
        object.__setattr__(self, "subject_id", _required(self.subject_id, "CONFLICT_SUBJECT_ID"))
        object.__setattr__(
            self,
            "related_entity_id",
            _required(self.related_entity_id, "CONFLICT_RELATED_ENTITY_ID"),
        )
        object.__setattr__(self, "evidence_ids", _normalized_ids(self.evidence_ids, "CONFLICT_EVIDENCE_ID"))
        object.__setattr__(self, "note", self.note.strip())

    @property
    def disclosure_id(self) -> str:
        return _hash_payload(
            {
                "as_of": self.as_of.isoformat(),
                "conflict_type": self.conflict_type.value,
                "subject_id": self.subject_id,
                "related_entity_id": self.related_entity_id,
                "evidence_ids": list(self.evidence_ids),
                "public_market_use_permitted": self.public_market_use_permitted,
                "note": self.note,
            }
        )


@dataclass(frozen=True)
class InvestmentOpportunityEnvelope:
    """One deterministic opportunity representation across public and private markets."""

    as_of: datetime
    thesis_id: str
    subject_id: str
    issuer_id: str
    market_domain: MarketDomain
    primary_asset_class: PrimaryAssetClass
    instrument_type: InstrumentType
    exposure: str
    direction: InvestmentDirection
    summary: str
    confidence: float
    liquidity_state: LiquidityState
    eligibility_state: EligibilityState
    evidence_ids: tuple[str, ...]
    lineage_ids: tuple[str, ...] = field(default_factory=tuple)
    alternative_opportunity_ids: tuple[str, ...] = field(default_factory=tuple)
    vehicle_context: InvestmentVehicleContext | None = None
    private_market_terms: PrivateMarketTerms | None = None
    conflicts: tuple[ConflictDisclosure, ...] = field(default_factory=tuple)
    information_classification: InformationClassification = InformationClassification.PUBLIC
    public_market_research_use_permitted: bool = True
    no_position_alternative_permitted: bool = True
    research_only: bool = True
    capital_allocation_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "OPPORTUNITY_AS_OF")
        thesis_id = _required(self.thesis_id, "THESIS_ID")
        subject_id = _required(self.subject_id, "SUBJECT_ID")
        issuer_id = _required(self.issuer_id, "ISSUER_ID")
        exposure = _required(self.exposure, "EXPOSURE", upper=True)
        summary = _required(self.summary, "SUMMARY")
        evidence = _normalized_ids(self.evidence_ids, "EVIDENCE_ID")
        lineage = _normalized_ids(self.lineage_ids, "LINEAGE_ID")
        alternatives = _normalized_ids(self.alternative_opportunity_ids, "ALTERNATIVE_OPPORTUNITY_ID")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise OpportunityContractError("OPPORTUNITY_CONFIDENCE_OUT_OF_RANGE")
        if self.private_market_terms is not None and self.market_domain is not MarketDomain.PRIVATE:
            raise OpportunityContractError("PRIVATE_TERMS_REQUIRE_PRIVATE_MARKET_DOMAIN")
        if self.market_domain is MarketDomain.PRIVATE and self.instrument_type is InstrumentType.OPTION:
            raise OpportunityContractError("PRIVATE_MARKET_OPTION_NOT_SUPPORTED_BY_CORE_CONTRACT")
        if (
            self.information_classification is InformationClassification.MNPI_RESTRICTED
            and self.public_market_research_use_permitted
        ):
            raise OpportunityContractError("MNPI_RESTRICTED_CANNOT_FEED_PUBLIC_MARKET_RESEARCH")
        if any(item.as_of > boundary for item in self.conflicts):
            raise OpportunityContractError("CONFLICT_DISCLOSURE_CANNOT_BE_FUTURE_DATED")
        if self.private_market_terms is not None and any(
            evidence_id not in evidence for evidence_id in self.private_market_terms.source_evidence_ids
        ):
            raise OpportunityContractError("PRIVATE_TERMS_EVIDENCE_MUST_BE_IN_OPPORTUNITY_EVIDENCE")
        if (
            not self.research_only
            or self.capital_allocation_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise OpportunityContractError("OPPORTUNITY_ENVELOPE_HAS_FORBIDDEN_AUTHORITY")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "thesis_id", thesis_id)
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "issuer_id", issuer_id)
        object.__setattr__(self, "exposure", exposure)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(self, "lineage_ids", lineage)
        object.__setattr__(self, "alternative_opportunity_ids", alternatives)
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted(self.conflicts, key=lambda item: item.disclosure_id)),
        )

    @property
    def opportunity_id(self) -> str:
        payload = {
            "as_of": self.as_of.isoformat(),
            "thesis_id": self.thesis_id,
            "subject_id": self.subject_id,
            "issuer_id": self.issuer_id,
            "market_domain": self.market_domain.value,
            "primary_asset_class": self.primary_asset_class.value,
            "instrument_type": self.instrument_type.value,
            "exposure": self.exposure,
            "direction": self.direction.value,
            "summary": self.summary,
            "confidence": self.confidence,
            "liquidity_state": self.liquidity_state.value,
            "eligibility_state": self.eligibility_state.value,
            "evidence_ids": list(self.evidence_ids),
            "lineage_ids": list(self.lineage_ids),
            "alternative_opportunity_ids": list(self.alternative_opportunity_ids),
            "vehicle_context_id": self.vehicle_context.context_id if self.vehicle_context else None,
            "private_market_terms": (
                {
                    "stage": self.private_market_terms.stage,
                    "financing_instrument": self.private_market_terms.financing_instrument.value,
                    "source_evidence_ids": list(self.private_market_terms.source_evidence_ids),
                    "post_money_valuation": self.private_market_terms.post_money_valuation,
                    "round_size": self.private_market_terms.round_size,
                    "ownership_target": self.private_market_terms.ownership_target,
                    "expected_liquidity_horizon_months": (
                        self.private_market_terms.expected_liquidity_horizon_months
                    ),
                }
                if self.private_market_terms
                else None
            ),
            "conflict_disclosure_ids": [item.disclosure_id for item in self.conflicts],
            "information_classification": self.information_classification.value,
            "public_market_research_use_permitted": self.public_market_research_use_permitted,
            "no_position_alternative_permitted": self.no_position_alternative_permitted,
            "research_only": self.research_only,
            "capital_allocation_authorized": self.capital_allocation_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return _hash_payload(payload)


@dataclass(frozen=True)
class OpportunityGraphEdge:
    thesis_id: str
    from_opportunity_id: str
    to_opportunity_id: str
    relationship: OpportunityRelationship
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "thesis_id", _required(self.thesis_id, "EDGE_THESIS_ID"))
        object.__setattr__(
            self,
            "from_opportunity_id",
            _required(self.from_opportunity_id, "EDGE_FROM_OPPORTUNITY_ID"),
        )
        object.__setattr__(
            self,
            "to_opportunity_id",
            _required(self.to_opportunity_id, "EDGE_TO_OPPORTUNITY_ID"),
        )
        if self.from_opportunity_id == self.to_opportunity_id:
            raise OpportunityContractError("OPPORTUNITY_GRAPH_SELF_EDGE_FORBIDDEN")
        object.__setattr__(self, "evidence_ids", _normalized_ids(self.evidence_ids, "EDGE_EVIDENCE_ID"))

    @property
    def edge_id(self) -> str:
        return _hash_payload(
            {
                "thesis_id": self.thesis_id,
                "from_opportunity_id": self.from_opportunity_id,
                "to_opportunity_id": self.to_opportunity_id,
                "relationship": self.relationship.value,
                "evidence_ids": list(self.evidence_ids),
            }
        )


@dataclass(frozen=True)
class PublicPrivateOpportunityGraph:
    """Point-in-time thesis graph spanning public and private expressions."""

    as_of: datetime
    thesis_id: str
    opportunities: tuple[InvestmentOpportunityEnvelope, ...]
    edges: tuple[OpportunityGraphEdge, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    research_only: bool = True
    capital_allocation_authorized: bool = False
    execution_authorized: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "GRAPH_AS_OF")
        thesis_id = _required(self.thesis_id, "GRAPH_THESIS_ID")
        evidence = _normalized_ids(self.evidence_ids, "GRAPH_EVIDENCE_ID")
        if not self.opportunities:
            raise OpportunityContractError("OPPORTUNITY_GRAPH_REQUIRES_OPPORTUNITIES")
        if any(item.as_of > boundary for item in self.opportunities):
            raise OpportunityContractError("GRAPH_OPPORTUNITY_CANNOT_BE_FUTURE_DATED")
        if any(item.thesis_id != thesis_id for item in self.opportunities):
            raise OpportunityContractError("GRAPH_THESIS_MISMATCH")
        opportunity_ids = {item.opportunity_id for item in self.opportunities}
        if len(opportunity_ids) != len(self.opportunities):
            raise OpportunityContractError("GRAPH_OPPORTUNITY_DUPLICATE")
        for edge in self.edges:
            if edge.thesis_id != thesis_id:
                raise OpportunityContractError("GRAPH_EDGE_THESIS_MISMATCH")
            if edge.from_opportunity_id not in opportunity_ids or edge.to_opportunity_id not in opportunity_ids:
                raise OpportunityContractError("GRAPH_EDGE_REFERENCES_UNKNOWN_OPPORTUNITY")
        if not self.research_only or self.capital_allocation_authorized or self.execution_authorized:
            raise OpportunityContractError("OPPORTUNITY_GRAPH_HAS_FORBIDDEN_AUTHORITY")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "thesis_id", thesis_id)
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(
            self,
            "opportunities",
            tuple(sorted(self.opportunities, key=lambda item: item.opportunity_id)),
        )
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda item: item.edge_id)))

    @property
    def graph_id(self) -> str:
        return _hash_payload(
            {
                "as_of": self.as_of.isoformat(),
                "thesis_id": self.thesis_id,
                "opportunity_ids": [item.opportunity_id for item in self.opportunities],
                "edge_ids": [item.edge_id for item in self.edges],
                "evidence_ids": list(self.evidence_ids),
                "research_only": self.research_only,
                "capital_allocation_authorized": self.capital_allocation_authorized,
                "execution_authorized": self.execution_authorized,
            }
        )
