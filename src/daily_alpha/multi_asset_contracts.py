from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Iterable, Protocol, Sequence


class PrimaryAssetClass(StrEnum):
    EQUITY = "EQUITY"
    FIXED_INCOME_CREDIT = "FIXED_INCOME_CREDIT"
    COMMODITY = "COMMODITY"
    DIGITAL_ASSET = "DIGITAL_ASSET"
    FX_CASH_RESERVE = "FX_CASH_RESERVE"


class OverlayKind(StrEnum):
    FACTOR = "FACTOR"
    SECTOR_INDUSTRY = "SECTOR_INDUSTRY"
    THEMATIC = "THEMATIC"
    ACTIVE = "ACTIVE"


class InstrumentType(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    OPTION = "OPTION"
    BOND = "BOND"
    CREDIT = "CREDIT"
    FUTURE = "FUTURE"
    COMMODITY_ETF = "COMMODITY_ETF"
    DIGITAL_ASSET = "DIGITAL_ASSET"
    DIGITAL_ASSET_ETF = "DIGITAL_ASSET_ETF"
    FX = "FX"
    CASH = "CASH"
    TREASURY_RESERVE = "TREASURY_RESERVE"
    BASKET = "BASKET"
    INDEX = "INDEX"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class EligibilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class WarningSeverity(StrEnum):
    NONE = "NONE"
    INFO = "INFO"
    CAUTION = "CAUTION"
    HIGH = "HIGH"


class OverrideRecommendation(StrEnum):
    ACCEPT = "ACCEPT"
    CAUTION = "CAUTION"
    REDUCE = "REDUCE"
    BLOCK = "BLOCK"


class OverrideEvaluationState(StrEnum):
    ACCEPTABLE = "ACCEPTABLE"
    ACKNOWLEDGMENT_REQUIRED = "ACKNOWLEDGMENT_REQUIRED"
    HARD_BLOCKED = "HARD_BLOCKED"


class HardBlockReason(StrEnum):
    DATA_UNRELIABLE = "DATA_UNRELIABLE"
    INSUFFICIENT_BUYING_POWER = "INSUFFICIENT_BUYING_POWER"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    MANDATE_PROHIBITION = "MANDATE_PROHIBITION"
    LIQUIDITY_CAPACITY = "LIQUIDITY_CAPACITY"
    REGULATORY_COMPLIANCE = "REGULATORY_COMPLIANCE"
    BROKER_CUSTODIAN = "BROKER_CUSTODIAN"
    SYSTEM_SAFETY = "SYSTEM_SAFETY"


class TwinKind(StrEnum):
    CURRENT = "CURRENT"
    PRO_FORMA = "PRO_FORMA"


class RiskProfile(StrEnum):
    CAPITAL_PRESERVATION = "CAPITAL_PRESERVATION"
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    GROWTH = "GROWTH"
    AGGRESSIVE = "AGGRESSIVE"
    CUSTOM_EXTREME = "CUSTOM_EXTREME"


def _require_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(
    value: float | int | None,
    field_name: str,
    *,
    minimum: float | None = None,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return result


def _required_finite(
    value: float | int,
    field_name: str,
    *,
    minimum: float | None = None,
) -> float:
    result = _finite(value, field_name, minimum=minimum)
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def _percent(value: float | int | None, field_name: str) -> float | None:
    result = _finite(value, field_name, minimum=0.0)
    if result is not None and result > 100.0:
        raise ValueError(f"{field_name} must be <= 100")
    return result


def _canonical(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if hasattr(value, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for name, field_definition in value.__dataclass_fields__.items():
            if not field_definition.init:
                continue
            result[name] = _canonical(getattr(value, name))
        return result
    return value


def deterministic_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class ExposureTag:
    kind: OverlayKind
    name: str
    weight_pct: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "name"))
        object.__setattr__(self, "weight_pct", _percent(self.weight_pct, "weight_pct"))


@dataclass(frozen=True, slots=True)
class ExpressionCandidate:
    expression_id: str
    primary_asset_class: PrimaryAssetClass
    instrument_type: InstrumentType
    instrument_id: str
    implementation_structure: str
    suitability_score: float
    eligibility: EligibilityState
    risk_summary: str
    liquidity_capacity_summary: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "expression_id", _require_text(self.expression_id, "expression_id"))
        object.__setattr__(self, "instrument_id", _require_text(self.instrument_id, "instrument_id"))
        object.__setattr__(
            self,
            "implementation_structure",
            _require_text(self.implementation_structure, "implementation_structure"),
        )
        score = _required_finite(self.suitability_score, "suitability_score", minimum=0.0)
        if score > 100.0:
            raise ValueError("suitability_score must be <= 100")
        object.__setattr__(self, "suitability_score", score)
        object.__setattr__(self, "risk_summary", _require_text(self.risk_summary, "risk_summary"))
        object.__setattr__(
            self,
            "liquidity_capacity_summary",
            _require_text(self.liquidity_capacity_summary, "liquidity_capacity_summary"),
        )
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")


@dataclass(frozen=True, slots=True)
class InvestmentOpportunityEnvelope:
    version: str
    as_of: datetime
    thesis_id: str
    thesis_summary: str
    primary_asset_class: PrimaryAssetClass
    exposure: str
    instrument_type: InstrumentType
    instrument_id: str
    implementation_structure: str
    direction: Direction
    risk_description: str
    liquidity_capacity_state: str
    volatility_sensitivity_state: str
    portfolio_fit_assessment: str
    account_eligibility: EligibilityState
    recommended_quantity: float | None = None
    recommended_allocation_pct: float | None = None
    recommended_capital_at_risk: float | None = None
    maximum_contractual_loss: float | None = None
    alternatives: tuple[ExpressionCandidate, ...] = ()
    overlays: tuple[ExposureTag, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    lineage_ids: tuple[str, ...] = ()
    agent_opinion_ids: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    opportunity_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)
    trading_authorized: bool = field(init=False, default=False)
    live_trading_enabled: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _require_text(self.version, "version"))
        _require_aware(self.as_of, "as_of")
        for name in (
            "thesis_id",
            "thesis_summary",
            "exposure",
            "instrument_id",
            "implementation_structure",
            "risk_description",
            "liquidity_capacity_state",
            "volatility_sensitivity_state",
            "portfolio_fit_assessment",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "recommended_quantity",
            _finite(self.recommended_quantity, "recommended_quantity", minimum=0.0),
        )
        object.__setattr__(
            self,
            "recommended_allocation_pct",
            _percent(self.recommended_allocation_pct, "recommended_allocation_pct"),
        )
        object.__setattr__(
            self,
            "recommended_capital_at_risk",
            _finite(self.recommended_capital_at_risk, "recommended_capital_at_risk", minimum=0.0),
        )
        object.__setattr__(
            self,
            "maximum_contractual_loss",
            _finite(self.maximum_contractual_loss, "maximum_contractual_loss", minimum=0.0),
        )
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")
        for name in ("evidence_ids", "lineage_ids", "agent_opinion_ids"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
        if any(candidate.instrument_id == self.instrument_id for candidate in self.alternatives):
            raise ValueError("alternatives must not duplicate the primary implementation")
        object.__setattr__(self, "opportunity_id", deterministic_id("opp", self))


@dataclass(frozen=True, slots=True)
class MandateLimit:
    dimension: str
    key: str
    maximum_pct: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", _require_text(self.dimension, "dimension"))
        object.__setattr__(self, "key", _require_text(self.key, "key"))
        object.__setattr__(
            self,
            "maximum_pct",
            _required_finite(_percent(self.maximum_pct, "maximum_pct"), "maximum_pct"),
        )


@dataclass(frozen=True, slots=True)
class PersonalCIOMandate:
    mandate_id: str
    version: str
    as_of: datetime
    risk_profile: RiskProfile
    allowed_asset_classes: frozenset[PrimaryAssetClass]
    prohibited_asset_classes: frozenset[PrimaryAssetClass] = frozenset()
    target_volatility_pct: float | None = None
    minimum_liquidity_reserve_pct: float = 0.0
    max_position_allocation_pct: float | None = None
    limits: tuple[MandateLimit, ...] = ()
    allowed_instrument_types: frozenset[InstrumentType] = frozenset()
    objectives: tuple[str, ...] = ()
    restrictions: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    execution_authorized: bool = field(init=False, default=False)
    trading_authorized: bool = field(init=False, default=False)
    live_trading_enabled: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mandate_id", _require_text(self.mandate_id, "mandate_id"))
        object.__setattr__(self, "version", _require_text(self.version, "version"))
        _require_aware(self.as_of, "as_of")
        if not self.allowed_asset_classes:
            raise ValueError("allowed_asset_classes cannot be empty")
        if self.allowed_asset_classes & self.prohibited_asset_classes:
            raise ValueError("asset class cannot be both allowed and prohibited")
        object.__setattr__(
            self,
            "target_volatility_pct",
            _percent(self.target_volatility_pct, "target_volatility_pct"),
        )
        object.__setattr__(
            self,
            "minimum_liquidity_reserve_pct",
            _required_finite(
                _percent(self.minimum_liquidity_reserve_pct, "minimum_liquidity_reserve_pct"),
                "minimum_liquidity_reserve_pct",
            ),
        )
        object.__setattr__(
            self,
            "max_position_allocation_pct",
            _percent(self.max_position_allocation_pct, "max_position_allocation_pct"),
        )


@dataclass(frozen=True, slots=True)
class StressLoss:
    scenario: str
    estimated_loss: float
    modeled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", _require_text(self.scenario, "scenario"))
        object.__setattr__(
            self,
            "estimated_loss",
            _required_finite(self.estimated_loss, "estimated_loss", minimum=0.0),
        )
        if not self.modeled:
            raise ValueError("stress losses must be explicitly modeled")


@dataclass(frozen=True, slots=True)
class RiskOverrideRecord:
    opportunity_id: str
    as_of: datetime
    policy_version: str
    actor_id: str
    actor_role: str
    recommended_quantity: float
    selected_quantity: float
    recommended_capital_at_risk: float
    selected_capital_at_risk: float
    concentration_impact: str
    correlation_impact: str
    liquidity_capacity_assessment: str
    account_eligibility: EligibilityState
    recommendation: OverrideRecommendation
    warning_severity: WarningSeverity
    warnings: tuple[str, ...]
    hard_blocks: tuple[HardBlockReason, ...]
    stress_losses: tuple[StressLoss, ...]
    acknowledged: bool
    evidence_ids: tuple[str, ...]
    override_id: str = field(init=False)
    override_multiple: float = field(init=False)
    evaluation_state: OverrideEvaluationState = field(init=False)
    execution_authorized: bool = field(init=False, default=False)
    trading_authorized: bool = field(init=False, default=False)
    live_trading_enabled: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in (
            "opportunity_id",
            "policy_version",
            "actor_id",
            "actor_role",
            "concentration_impact",
            "correlation_impact",
            "liquidity_capacity_assessment",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _require_aware(self.as_of, "as_of")
        recommended_quantity = _required_finite(
            self.recommended_quantity,
            "recommended_quantity",
            minimum=0.0,
        )
        if recommended_quantity == 0.0:
            raise ValueError("recommended_quantity must be > 0 for an override comparison")
        selected_quantity = _required_finite(self.selected_quantity, "selected_quantity", minimum=0.0)
        object.__setattr__(self, "recommended_quantity", recommended_quantity)
        object.__setattr__(self, "selected_quantity", selected_quantity)
        object.__setattr__(
            self,
            "recommended_capital_at_risk",
            _required_finite(
                self.recommended_capital_at_risk,
                "recommended_capital_at_risk",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "selected_capital_at_risk",
            _required_finite(
                self.selected_capital_at_risk,
                "selected_capital_at_risk",
                minimum=0.0,
            ),
        )
        object.__setattr__(self, "override_multiple", selected_quantity / recommended_quantity)
        if len(set(self.hard_blocks)) != len(self.hard_blocks):
            raise ValueError("hard_blocks must be unique")
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")
        if self.hard_blocks:
            if self.recommendation != OverrideRecommendation.BLOCK:
                raise ValueError("hard blocks require BLOCK recommendation")
            state = OverrideEvaluationState.HARD_BLOCKED
        elif self.override_multiple > 1.0 and not self.acknowledged:
            state = OverrideEvaluationState.ACKNOWLEDGMENT_REQUIRED
        else:
            state = OverrideEvaluationState.ACCEPTABLE
        object.__setattr__(self, "evaluation_state", state)
        object.__setattr__(self, "override_id", deterministic_id("ovr", self))


def evaluate_risk_override(
    *,
    opportunity_id: str,
    as_of: datetime,
    policy_version: str,
    actor_id: str,
    actor_role: str,
    recommended_quantity: float,
    selected_quantity: float,
    recommended_capital_at_risk: float,
    selected_capital_at_risk: float,
    concentration_impact: str,
    correlation_impact: str,
    liquidity_capacity_assessment: str,
    account_eligibility: EligibilityState,
    stress_losses: Sequence[StressLoss],
    acknowledged: bool,
    evidence_ids: Sequence[str],
    hard_blocks: Sequence[HardBlockReason] = (),
) -> RiskOverrideRecord:
    recommended = _required_finite(recommended_quantity, "recommended_quantity", minimum=0.0)
    if recommended <= 0.0:
        raise ValueError("recommended_quantity must be > 0")
    selected = _required_finite(selected_quantity, "selected_quantity", minimum=0.0)
    multiple = selected / recommended
    blocks = list(dict.fromkeys(hard_blocks))
    eligibility_block = {
        EligibilityState.NOT_AUTHORIZED: HardBlockReason.NOT_AUTHORIZED,
        EligibilityState.NOT_SUPPORTED: HardBlockReason.NOT_SUPPORTED,
        EligibilityState.DATA_UNAVAILABLE: HardBlockReason.DATA_UNRELIABLE,
    }.get(account_eligibility)
    if eligibility_block is not None and eligibility_block not in blocks:
        blocks.append(eligibility_block)

    if blocks:
        recommendation = OverrideRecommendation.BLOCK
        severity = WarningSeverity.HIGH
        warnings = ("Objective hard constraint prevents progression to execution evaluation.",)
    elif multiple > 5.0:
        recommendation = OverrideRecommendation.REDUCE
        severity = WarningSeverity.HIGH
        warnings = (
            f"Customer-selected quantity is {multiple:.2f}x the ConvexRidge recommended quantity.",
            "Customer acknowledgment is required; the house recommendation remains to reduce size.",
        )
    elif multiple > 1.0:
        recommendation = OverrideRecommendation.CAUTION
        severity = WarningSeverity.CAUTION
        warnings = (
            f"Customer-selected quantity is {multiple:.2f}x the ConvexRidge recommended quantity.",
            "Customer acknowledgment is required before any separate execution evaluation.",
        )
    else:
        recommendation = OverrideRecommendation.ACCEPT
        severity = WarningSeverity.NONE
        warnings = ()

    return RiskOverrideRecord(
        opportunity_id=opportunity_id,
        as_of=as_of,
        policy_version=policy_version,
        actor_id=actor_id,
        actor_role=actor_role,
        recommended_quantity=recommended_quantity,
        selected_quantity=selected_quantity,
        recommended_capital_at_risk=recommended_capital_at_risk,
        selected_capital_at_risk=selected_capital_at_risk,
        concentration_impact=concentration_impact,
        correlation_impact=correlation_impact,
        liquidity_capacity_assessment=liquidity_capacity_assessment,
        account_eligibility=account_eligibility,
        recommendation=recommendation,
        warning_severity=severity,
        warnings=warnings,
        hard_blocks=tuple(blocks),
        stress_losses=tuple(stress_losses),
        acknowledged=acknowledged,
        evidence_ids=tuple(evidence_ids),
    )


@dataclass(frozen=True, slots=True)
class InstrumentCapability:
    primary_asset_class: PrimaryAssetClass
    instrument_type: InstrumentType
    state: EligibilityState
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _require_text(self.reason, "reason"))


@dataclass(frozen=True, slots=True)
class BrokerCapability:
    account_id: str
    provider: str
    as_of: datetime
    account_type: str
    settlement_currency: str
    capabilities: tuple[InstrumentCapability, ...]
    buying_power: float | None = None
    collateral_semantics: str = "UNAVAILABLE"
    max_position_notional: float | None = None
    evidence_ids: tuple[str, ...] = ()
    execution_authorized: bool = field(init=False, default=False)
    trading_authorized: bool = field(init=False, default=False)
    live_trading_enabled: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in (
            "account_id",
            "provider",
            "account_type",
            "settlement_currency",
            "collateral_semantics",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _require_aware(self.as_of, "as_of")
        object.__setattr__(
            self,
            "buying_power",
            _finite(self.buying_power, "buying_power", minimum=0.0),
        )
        object.__setattr__(
            self,
            "max_position_notional",
            _finite(self.max_position_notional, "max_position_notional", minimum=0.0),
        )
        keys = [(item.primary_asset_class, item.instrument_type) for item in self.capabilities]
        if len(set(keys)) != len(keys):
            raise ValueError("capabilities must be unique by asset class and instrument type")

    def eligibility_for(
        self,
        primary_asset_class: PrimaryAssetClass,
        instrument_type: InstrumentType,
    ) -> EligibilityState:
        for capability in self.capabilities:
            if (
                capability.primary_asset_class == primary_asset_class
                and capability.instrument_type == instrument_type
            ):
                return capability.state
        return EligibilityState.NOT_SUPPORTED


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    position_id: str
    primary_asset_class: PrimaryAssetClass
    instrument_type: InstrumentType
    instrument_id: str
    quantity: float
    market_value: float | None
    notional_exposure: float | None
    capital_at_risk: float | None
    overlays: tuple[ExposureTag, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "position_id", _require_text(self.position_id, "position_id"))
        object.__setattr__(self, "instrument_id", _require_text(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "quantity", _required_finite(self.quantity, "quantity"))
        object.__setattr__(self, "market_value", _finite(self.market_value, "market_value"))
        object.__setattr__(
            self,
            "notional_exposure",
            _finite(self.notional_exposure, "notional_exposure"),
        )
        object.__setattr__(
            self,
            "capital_at_risk",
            _finite(self.capital_at_risk, "capital_at_risk", minimum=0.0),
        )


@dataclass(frozen=True, slots=True)
class ExposureMeasure:
    dimension: str
    key: str
    value: float
    unit: str
    modeled: bool
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("dimension", "key", "unit"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "value", _required_finite(self.value, "value"))


@dataclass(frozen=True, slots=True)
class PortfolioDigitalTwin:
    portfolio_id: str
    version: str
    kind: TwinKind
    as_of: datetime
    nav: float
    cash: float
    collateral: float | None
    buying_power: float | None
    positions: tuple[PortfolioPosition, ...]
    exposures: tuple[ExposureMeasure, ...]
    portfolio_volatility_pct: float | None
    drawdown_pct: float | None
    liquidity_reserve_requirement_pct: float
    evidence_ids: tuple[str, ...]
    parent_twin_id: str | None = None
    twin_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)
    trading_authorized: bool = field(init=False, default=False)
    live_trading_enabled: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "portfolio_id", _require_text(self.portfolio_id, "portfolio_id"))
        object.__setattr__(self, "version", _require_text(self.version, "version"))
        _require_aware(self.as_of, "as_of")
        object.__setattr__(self, "nav", _required_finite(self.nav, "nav", minimum=0.0))
        object.__setattr__(self, "cash", _required_finite(self.cash, "cash"))
        object.__setattr__(self, "collateral", _finite(self.collateral, "collateral", minimum=0.0))
        object.__setattr__(
            self,
            "buying_power",
            _finite(self.buying_power, "buying_power", minimum=0.0),
        )
        object.__setattr__(
            self,
            "portfolio_volatility_pct",
            _percent(self.portfolio_volatility_pct, "portfolio_volatility_pct"),
        )
        object.__setattr__(self, "drawdown_pct", _percent(self.drawdown_pct, "drawdown_pct"))
        object.__setattr__(
            self,
            "liquidity_reserve_requirement_pct",
            _required_finite(
                _percent(
                    self.liquidity_reserve_requirement_pct,
                    "liquidity_reserve_requirement_pct",
                ),
                "liquidity_reserve_requirement_pct",
            ),
        )
        if self.kind == TwinKind.CURRENT and self.parent_twin_id is not None:
            raise ValueError("CURRENT twin cannot have parent_twin_id")
        if self.kind == TwinKind.PRO_FORMA and not self.parent_twin_id:
            raise ValueError("PRO_FORMA twin requires parent_twin_id")
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")
        position_ids = [position.position_id for position in self.positions]
        if len(set(position_ids)) != len(position_ids):
            raise ValueError("positions must have unique position_id")
        object.__setattr__(self, "twin_id", deterministic_id("twin", self))


@dataclass(frozen=True, slots=True)
class DigitalTwinPair:
    current: PortfolioDigitalTwin
    pro_forma: PortfolioDigitalTwin
    decision_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _require_text(self.decision_id, "decision_id"))
        if self.current.kind != TwinKind.CURRENT:
            raise ValueError("current twin must have CURRENT kind")
        if self.pro_forma.kind != TwinKind.PRO_FORMA:
            raise ValueError("pro_forma twin must have PRO_FORMA kind")
        if self.current.portfolio_id != self.pro_forma.portfolio_id:
            raise ValueError("digital twins must share portfolio_id")
        if self.pro_forma.parent_twin_id != self.current.twin_id:
            raise ValueError("pro_forma twin must reference current twin")
        if self.pro_forma.as_of < self.current.as_of:
            raise ValueError("pro_forma twin cannot predate current twin")


@dataclass(frozen=True, slots=True)
class ScenarioShock:
    dimension: str
    target: str
    relative_change_pct: float | None = None
    basis_point_change: float | None = None
    absolute_change: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", _require_text(self.dimension, "dimension"))
        object.__setattr__(self, "target", _require_text(self.target, "target"))
        values = (
            self.relative_change_pct is not None,
            self.basis_point_change is not None,
            self.absolute_change is not None,
        )
        if sum(values) != 1:
            raise ValueError("scenario shock requires exactly one shock value")
        for name in ("relative_change_pct", "basis_point_change", "absolute_change"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    as_of: datetime
    portfolio_twin_id: str
    portfolio_as_of: datetime
    shocks: tuple[ScenarioShock, ...]
    evidence_ids: tuple[str, ...]
    request_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        _require_aware(self.portfolio_as_of, "portfolio_as_of")
        if self.as_of != self.portfolio_as_of:
            raise ValueError("scenario request must use the exact point-in-time portfolio snapshot")
        object.__setattr__(
            self,
            "portfolio_twin_id",
            _require_text(self.portfolio_twin_id, "portfolio_twin_id"),
        )
        if not self.shocks:
            raise ValueError("at least one scenario shock is required")
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")
        object.__setattr__(self, "request_id", deterministic_id("scenario", self))


@dataclass(frozen=True, slots=True)
class ScenarioResponse:
    request_id: str
    as_of: datetime
    portfolio_twin_id: str
    stressed_nav: float
    estimated_loss: float
    observations: tuple[str, ...]
    modeled: bool = True
    observed_market_value: bool = False
    execution_authorized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _require_text(self.request_id, "request_id"))
        object.__setattr__(
            self,
            "portfolio_twin_id",
            _require_text(self.portfolio_twin_id, "portfolio_twin_id"),
        )
        _require_aware(self.as_of, "as_of")
        object.__setattr__(
            self,
            "stressed_nav",
            _required_finite(self.stressed_nav, "stressed_nav", minimum=0.0),
        )
        object.__setattr__(
            self,
            "estimated_loss",
            _required_finite(self.estimated_loss, "estimated_loss", minimum=0.0),
        )
        if not self.modeled or self.observed_market_value:
            raise ValueError(
                "scenario responses must remain modeled and distinct from observed market values"
            )


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    thesis_id: str
    as_of: datetime
    mandate_id: str
    account_id: str
    evidence_ids: tuple[str, ...]
    request_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in ("thesis_id", "mandate_id", "account_id"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _require_aware(self.as_of, "as_of")
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")
        object.__setattr__(self, "request_id", deterministic_id("translate", self))


@dataclass(frozen=True, slots=True)
class TranslationResult:
    request_id: str
    ranked_expressions: tuple[ExpressionCandidate, ...]
    no_position_expression_id: str
    result_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _require_text(self.request_id, "request_id"))
        object.__setattr__(
            self,
            "no_position_expression_id",
            _require_text(self.no_position_expression_id, "no_position_expression_id"),
        )
        if not self.ranked_expressions:
            raise ValueError("ranked_expressions cannot be empty")
        ids = [item.expression_id for item in self.ranked_expressions]
        if len(set(ids)) != len(ids):
            raise ValueError("ranked expression IDs must be unique")
        if self.no_position_expression_id not in ids:
            raise ValueError("no-position/cash expression must be retained in ranked_expressions")
        object.__setattr__(self, "result_id", deterministic_id("translation", self))


class CrossAssetOpportunityTranslator(Protocol):
    def translate(
        self,
        request: TranslationRequest,
        candidates: Sequence[ExpressionCandidate],
    ) -> TranslationResult: ...


def rank_expression_candidates(
    request: TranslationRequest,
    candidates: Iterable[ExpressionCandidate],
    *,
    no_position_expression_id: str,
) -> TranslationResult:
    candidate_tuple = tuple(candidates)
    if not candidate_tuple:
        raise ValueError("candidates cannot be empty")
    eligibility_rank = {
        EligibilityState.AVAILABLE: 0,
        EligibilityState.NOT_AUTHORIZED: 1,
        EligibilityState.NOT_SUPPORTED: 2,
        EligibilityState.DATA_UNAVAILABLE: 3,
    }
    ranked = tuple(
        sorted(
            candidate_tuple,
            key=lambda item: (
                eligibility_rank[item.eligibility],
                -item.suitability_score,
                item.primary_asset_class.value,
                item.instrument_type.value,
                item.instrument_id,
                item.expression_id,
            ),
        )
    )
    return TranslationResult(
        request_id=request.request_id,
        ranked_expressions=ranked,
        no_position_expression_id=no_position_expression_id,
    )


@dataclass(frozen=True, slots=True)
class AgentTrackRecord:
    agent_id: str
    agent_version: str
    domain: str
    as_of: datetime
    sample_size: int
    directional_hit_rate: float | None
    expectancy_r: float | None
    max_drawdown_r: float | None
    max_loss_streak: int
    calibration_error: float | None
    stale_data_incidence_pct: float | None
    evidence_ids: tuple[str, ...]
    record_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in ("agent_id", "agent_version", "domain"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _require_aware(self.as_of, "as_of")
        if self.sample_size < 0 or self.max_loss_streak < 0:
            raise ValueError("sample_size and max_loss_streak cannot be negative")
        object.__setattr__(
            self,
            "directional_hit_rate",
            _percent(self.directional_hit_rate, "directional_hit_rate"),
        )
        object.__setattr__(self, "expectancy_r", _finite(self.expectancy_r, "expectancy_r"))
        object.__setattr__(
            self,
            "max_drawdown_r",
            _finite(self.max_drawdown_r, "max_drawdown_r", minimum=0.0),
        )
        object.__setattr__(
            self,
            "calibration_error",
            _finite(self.calibration_error, "calibration_error", minimum=0.0),
        )
        object.__setattr__(
            self,
            "stale_data_incidence_pct",
            _percent(self.stale_data_incidence_pct, "stale_data_incidence_pct"),
        )
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")
        object.__setattr__(self, "record_id", deterministic_id("agenttrack", self))


@dataclass(frozen=True, slots=True)
class OutcomeLink:
    outcome_id: str
    observed_at: datetime
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_id", _require_text(self.outcome_id, "outcome_id"))
        _require_aware(self.observed_at, "observed_at")
        if not self.evidence_ids:
            raise ValueError("evidence_ids are required")


@dataclass(frozen=True, slots=True)
class DecisionReplayRecord:
    decision_id: str
    as_of: datetime
    evidence_ids: tuple[str, ...]
    agent_opinion_ids: tuple[str, ...]
    cio_decision_id: str
    portfolio_assessment_id: str
    risk_evaluation_id: str
    opportunity_id: str
    recommended_size_id: str
    customer_override_id: str | None
    broker_capability_id: str | None
    outcome: OutcomeLink | None = None
    replay_id: str = field(init=False)
    execution_authorized: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "cio_decision_id",
            "portfolio_assessment_id",
            "risk_evaluation_id",
            "opportunity_id",
            "recommended_size_id",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        _require_aware(self.as_of, "as_of")
        if not self.evidence_ids or not self.agent_opinion_ids:
            raise ValueError("decision replay requires evidence and agent-opinion lineage")
        if self.outcome is not None and self.outcome.observed_at < self.as_of:
            raise ValueError("eventual outcome cannot predate the historical decision snapshot")
        object.__setattr__(self, "replay_id", deterministic_id("replay", self))


__all__ = [
    "AgentTrackRecord",
    "BrokerCapability",
    "CrossAssetOpportunityTranslator",
    "DecisionReplayRecord",
    "DigitalTwinPair",
    "Direction",
    "EligibilityState",
    "ExposureMeasure",
    "ExposureTag",
    "ExpressionCandidate",
    "HardBlockReason",
    "InstrumentCapability",
    "InstrumentType",
    "InvestmentOpportunityEnvelope",
    "MandateLimit",
    "OutcomeLink",
    "OverlayKind",
    "OverrideEvaluationState",
    "OverrideRecommendation",
    "PersonalCIOMandate",
    "PortfolioDigitalTwin",
    "PortfolioPosition",
    "PrimaryAssetClass",
    "RiskOverrideRecord",
    "RiskProfile",
    "ScenarioRequest",
    "ScenarioResponse",
    "ScenarioShock",
    "StressLoss",
    "TranslationRequest",
    "TranslationResult",
    "TwinKind",
    "WarningSeverity",
    "deterministic_id",
    "evaluate_risk_override",
    "rank_expression_candidates",
]
