from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class PrivateMarketGovernanceError(ValueError):
    """A private-market governance or valuation invariant was violated."""


class PrivateValuationMethod(StrEnum):
    LAST_ROUND = "LAST_ROUND"
    COMPARABLES = "COMPARABLES"
    DCF = "DCF"
    THIRD_PARTY = "THIRD_PARTY"
    MANAGER_MARK = "MANAGER_MARK"
    OTHER = "OTHER"


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrivateMarketGovernanceError(f"{name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _required(value: str, name: str, *, upper: bool = False) -> str:
    normalized = value.strip()
    if not normalized:
        raise PrivateMarketGovernanceError(f"{name}_REQUIRED")
    return normalized.upper() if upper else normalized


def _ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_required(value, name) for value in values))
    if not normalized:
        raise PrivateMarketGovernanceError(f"{name}_REQUIRED")
    if len(set(normalized)) != len(normalized):
        raise PrivateMarketGovernanceError(f"{name}_MUST_BE_UNIQUE")
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
class InvestmentGovernanceBoundary:
    """Independent policy identities carried with research, never execution authority."""

    as_of: datetime
    opportunity_id: str
    vehicle_context_id: str
    mandate_id: str
    conflict_policy_id: str
    information_barrier_policy_id: str
    valuation_policy_id: str
    portfolio_policy_id: str
    risk_policy_id: str
    execution_policy_id: str
    capital_commitment_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "GOVERNANCE_AS_OF"))
        for field_name in (
            "opportunity_id",
            "vehicle_context_id",
            "mandate_id",
            "conflict_policy_id",
            "information_barrier_policy_id",
            "valuation_policy_id",
            "portfolio_policy_id",
            "risk_policy_id",
            "execution_policy_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name.upper()),
            )
        if (
            self.capital_commitment_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise PrivateMarketGovernanceError("GOVERNANCE_BOUNDARY_HAS_FORBIDDEN_AUTHORITY")

    @property
    def governance_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "opportunity_id": self.opportunity_id,
                "vehicle_context_id": self.vehicle_context_id,
                "mandate_id": self.mandate_id,
                "conflict_policy_id": self.conflict_policy_id,
                "information_barrier_policy_id": self.information_barrier_policy_id,
                "valuation_policy_id": self.valuation_policy_id,
                "portfolio_policy_id": self.portfolio_policy_id,
                "risk_policy_id": self.risk_policy_id,
                "execution_policy_id": self.execution_policy_id,
                "capital_commitment_authorized": self.capital_commitment_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True, slots=True)
class PrivateMarketValuationSnapshot:
    """Point-in-time private valuation evidence, explicitly distinct from observed market price."""

    as_of: datetime
    opportunity_id: str
    currency: str
    method: PrivateValuationMethod
    base_value: float
    evidence_ids: tuple[str, ...]
    low_value: float | None = None
    high_value: float | None = None
    observed_market_price: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "VALUATION_AS_OF"))
        object.__setattr__(
            self,
            "opportunity_id",
            _required(self.opportunity_id, "VALUATION_OPPORTUNITY_ID"),
        )
        object.__setattr__(self, "currency", _required(self.currency, "CURRENCY", upper=True))
        object.__setattr__(
            self,
            "evidence_ids",
            _ids(self.evidence_ids, "VALUATION_EVIDENCE_ID"),
        )
        if not math.isfinite(self.base_value) or self.base_value < 0.0:
            raise PrivateMarketGovernanceError("VALUATION_BASE_VALUE_INVALID")
        low = self.base_value if self.low_value is None else self.low_value
        high = self.base_value if self.high_value is None else self.high_value
        if not math.isfinite(low) or not math.isfinite(high) or low < 0.0 or high < 0.0:
            raise PrivateMarketGovernanceError("VALUATION_RANGE_INVALID")
        if low > self.base_value or self.base_value > high:
            raise PrivateMarketGovernanceError("VALUATION_RANGE_MUST_BRACKET_BASE")
        if self.observed_market_price:
            raise PrivateMarketGovernanceError(
                "PRIVATE_VALUATION_CANNOT_BE_MARKED_AS_OBSERVED_MARKET_PRICE"
            )

    @property
    def valuation_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "opportunity_id": self.opportunity_id,
                "currency": self.currency,
                "method": self.method.value,
                "base_value": self.base_value,
                "low_value": self.low_value,
                "high_value": self.high_value,
                "evidence_ids": list(self.evidence_ids),
                "observed_market_price": self.observed_market_price,
            }
        )


@dataclass(frozen=True, slots=True)
class PrivateMarketDecisionContext:
    """Join private valuation and policy lineage below the shared opportunity envelope."""

    as_of: datetime
    opportunity_id: str
    governance: InvestmentGovernanceBoundary
    valuation: PrivateMarketValuationSnapshot
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "PRIVATE_DECISION_AS_OF")
        opportunity_id = _required(self.opportunity_id, "PRIVATE_DECISION_OPPORTUNITY_ID")
        evidence = _ids(self.evidence_ids, "PRIVATE_DECISION_EVIDENCE_ID")
        if self.governance.opportunity_id != opportunity_id:
            raise PrivateMarketGovernanceError("GOVERNANCE_OPPORTUNITY_ID_MISMATCH")
        if self.valuation.opportunity_id != opportunity_id:
            raise PrivateMarketGovernanceError("VALUATION_OPPORTUNITY_ID_MISMATCH")
        if self.governance.as_of > boundary or self.valuation.as_of > boundary:
            raise PrivateMarketGovernanceError("PRIVATE_DECISION_CONTAINS_FUTURE_KNOWLEDGE")
        if any(item not in evidence for item in self.valuation.evidence_ids):
            raise PrivateMarketGovernanceError(
                "VALUATION_EVIDENCE_MUST_BE_IN_DECISION_EVIDENCE"
            )
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "opportunity_id", opportunity_id)
        object.__setattr__(self, "evidence_ids", evidence)

    @property
    def decision_context_id(self) -> str:
        return _hash(
            {
                "as_of": self.as_of.isoformat(),
                "opportunity_id": self.opportunity_id,
                "governance_id": self.governance.governance_id,
                "valuation_id": self.valuation.valuation_id,
                "evidence_ids": list(self.evidence_ids),
            }
        )


__all__ = [
    "InvestmentGovernanceBoundary",
    "PrivateMarketDecisionContext",
    "PrivateMarketGovernanceError",
    "PrivateMarketValuationSnapshot",
    "PrivateValuationMethod",
]
