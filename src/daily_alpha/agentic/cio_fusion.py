"""CIO/Fusion contracts for Daily Alpha Quantitative Investment Platform.

The CIO layer synthesizes governed Research Council opinions, quant-model views, and
portfolio/regime context into an investment intent. It may override individual analyst or
model views when the override is explicit and attributable. It may not place orders,
authorize live trading, override the independent deterministic Risk Governor, or bypass
the Governance Lock.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus
from .research_council import ResearchCouncilPacket


class CIOFusionError(ValueError):
    """CIO/Fusion contract or lineage invariant failed."""


class InvestmentAction(StrEnum):
    BUY = "BUY"
    WAIT = "WAIT"
    HOLD = "HOLD"
    ADD = "ADD"
    TRIM = "TRIM"
    SELL = "SELL"
    HEDGE = "HEDGE"
    NO_ACTION = "NO_ACTION"


class CIOContextKind(StrEnum):
    PORTFOLIO = "PORTFOLIO"
    REGIME = "REGIME"
    MARKET = "MARKET"
    FEATURE = "FEATURE"
    EVENT = "EVENT"
    RESEARCH = "RESEARCH"


class OverrideSourceKind(StrEnum):
    AGENT_OPINION = "AGENT_OPINION"
    QUANT_MODEL = "QUANT_MODEL"


RISK_ON_ACTIONS = frozenset({InvestmentAction.BUY, InvestmentAction.ADD})


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CIOFusionError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


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
        raise CIOFusionError("CIO_FUSION_VALUE_NOT_CANONICAL_JSON") from exc


def _normalized_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({value.strip().upper() for value in values if value.strip()}))


@dataclass(frozen=True, order=True)
class CIOContextRef:
    context_kind: CIOContextKind
    context_id: str
    available_at: datetime
    quality_label: str = "UNSPECIFIED"
    status: ReadinessStatus = ReadinessStatus.PASS

    def __post_init__(self) -> None:
        context_id = self.context_id.strip().lower()
        quality = self.quality_label.strip().upper()
        if not context_id:
            raise CIOFusionError("CIO_CONTEXT_ID_REQUIRED")
        if not quality:
            raise CIOFusionError("CIO_CONTEXT_QUALITY_REQUIRED")
        object.__setattr__(self, "context_id", context_id)
        object.__setattr__(self, "quality_label", quality)
        object.__setattr__(self, "available_at", _aware_utc(self.available_at, "CONTEXT_AVAILABLE_AT"))


@dataclass(frozen=True)
class QuantModelView:
    """Point-in-time output from a deterministic or statistical alpha model."""

    security_id: str
    model_id: str
    model_version: str
    as_of: datetime
    status: ReadinessStatus
    signal_label: str
    score: int | None
    confidence: float
    input_lineage_ids: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        model_id = self.model_id.strip().upper()
        version = self.model_version.strip()
        label = self.signal_label.strip().upper()
        boundary = _aware_utc(self.as_of, "QUANT_MODEL_AS_OF")
        if not security_id or not model_id or not version or not label:
            raise CIOFusionError("QUANT_MODEL_IDENTITY_REQUIRED")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise CIOFusionError("QUANT_MODEL_CONFIDENCE_OUT_OF_RANGE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise CIOFusionError("QUANT_MODEL_VIEW_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED:
            if self.score is not None or self.confidence != 0.0:
                raise CIOFusionError("BLOCKED_QUANT_MODEL_CANNOT_HAVE_ACTIVE_SCORE")
        elif self.score is None or not -100 <= self.score <= 100:
            raise CIOFusionError("QUANT_MODEL_SCORE_OUT_OF_RANGE")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", version)
        object.__setattr__(self, "signal_label", label)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "input_lineage_ids", tuple(sorted(set(self.input_lineage_ids))))

    @property
    def model_view_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "as_of": self.as_of.isoformat(),
            "status": self.status.value,
            "signal_label": self.signal_label,
            "score": self.score,
            "confidence": self.confidence,
            "input_lineage_ids": list(self.input_lineage_ids),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CIOFusionInput:
    """Exact investment-decision input surface for the CIO layer."""

    security_id: str
    as_of: datetime
    council: ResearchCouncilPacket
    quant_model_views: tuple[QuantModelView, ...] = ()
    context_refs: tuple[CIOContextRef, ...] = ()
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        boundary = _aware_utc(self.as_of, "CIO_FUSION_AS_OF")
        if not security_id:
            raise CIOFusionError("CIO_FUSION_SECURITY_ID_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise CIOFusionError("CIO_FUSION_INPUT_MUST_REMAIN_RESEARCH_ONLY")
        if self.council.security_id != security_id or self.council.as_of != boundary:
            raise CIOFusionError("CIO_COUNCIL_CONTEXT_MISMATCH")
        model_ids = [item.model_view_id for item in self.quant_model_views]
        if len(set(model_ids)) != len(model_ids):
            raise CIOFusionError("DUPLICATE_QUANT_MODEL_VIEW")
        for model in self.quant_model_views:
            if model.security_id != security_id:
                raise CIOFusionError("QUANT_MODEL_SECURITY_MISMATCH")
            if model.as_of > boundary:
                raise CIOFusionError(f"FUTURE_QUANT_MODEL_VIEW_NOT_ALLOWED:{model.model_id}")
        context_ids = [item.context_id for item in self.context_refs]
        if len(set(context_ids)) != len(context_ids):
            raise CIOFusionError("DUPLICATE_CIO_CONTEXT_ID")
        for context in self.context_refs:
            if context.available_at > boundary:
                raise CIOFusionError(f"FUTURE_CIO_CONTEXT_NOT_ALLOWED:{context.context_id}")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "quant_model_views",
            tuple(sorted(self.quant_model_views, key=lambda item: (item.model_id, item.model_version))),
        )
        object.__setattr__(
            self,
            "context_refs",
            tuple(sorted(self.context_refs, key=lambda item: (item.context_kind.value, item.context_id))),
        )

    @property
    def fusion_input_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "as_of": self.as_of.isoformat(),
            "council_packet_id": self.council.council_packet_id,
            "quant_model_view_ids": [item.model_view_id for item in self.quant_model_views],
            "context_refs": [
                {
                    "context_kind": item.context_kind.value,
                    "context_id": item.context_id,
                    "available_at": item.available_at.isoformat(),
                    "quality_label": item.quality_label,
                    "status": item.status.value,
                }
                for item in self.context_refs
            ],
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, order=True)
class OverrideRecord:
    source_kind: OverrideSourceKind
    source_id: str
    source_label: str
    reason: str

    def __post_init__(self) -> None:
        source_id = self.source_id.strip().lower()
        label = self.source_label.strip().upper()
        reason = self.reason.strip()
        if not source_id or not label or not reason:
            raise CIOFusionError("CIO_OVERRIDE_FIELDS_REQUIRED")
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_label", label)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class CIOInvestmentDecision:
    """Security-level investment intent; never an executable order."""

    security_id: str
    as_of: datetime
    fusion_input_id: str
    action: InvestmentAction
    conviction: float
    expected_alpha_score: int
    rationale: str
    opposing_case: str
    invalidation_conditions: tuple[str, ...]
    cited_opinion_ids: tuple[str, ...]
    cited_model_view_ids: tuple[str, ...]
    overrides: tuple[OverrideRecord, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    reasoning_engine: str = "UNSPECIFIED"
    reasoning_engine_version: str = "UNSPECIFIED"
    research_only: bool = True
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False
    may_override_risk_governor: bool = False
    may_override_governance_lock: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        fusion_input_id = self.fusion_input_id.strip().lower()
        rationale = self.rationale.strip()
        opposing_case = self.opposing_case.strip()
        engine = self.reasoning_engine.strip().upper()
        engine_version = self.reasoning_engine_version.strip()
        boundary = _aware_utc(self.as_of, "CIO_DECISION_AS_OF")
        if not security_id or not fusion_input_id:
            raise CIOFusionError("CIO_DECISION_IDENTITY_REQUIRED")
        if not rationale or not opposing_case:
            raise CIOFusionError("CIO_DECISION_RATIONALE_AND_OPPOSING_CASE_REQUIRED")
        if not engine or not engine_version:
            raise CIOFusionError("CIO_DECISION_REASONING_ENGINE_REQUIRED")
        if not math.isfinite(self.conviction) or not 0.0 <= self.conviction <= 1.0:
            raise CIOFusionError("CIO_DECISION_CONVICTION_OUT_OF_RANGE")
        if not -100 <= self.expected_alpha_score <= 100:
            raise CIOFusionError("CIO_EXPECTED_ALPHA_SCORE_OUT_OF_RANGE")
        if not self.invalidation_conditions:
            raise CIOFusionError("CIO_DECISION_REQUIRES_INVALIDATION_CONDITION")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
            or self.may_override_risk_governor
            or self.may_override_governance_lock
        ):
            raise CIOFusionError("CIO_DECISION_MUST_REMAIN_BELOW_RISK_AND_GOVERNANCE")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "fusion_input_id", fusion_input_id)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "opposing_case", opposing_case)
        object.__setattr__(self, "reasoning_engine", engine)
        object.__setattr__(self, "reasoning_engine_version", engine_version)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "invalidation_conditions",
            tuple(sorted({item.strip() for item in self.invalidation_conditions if item.strip()})),
        )
        object.__setattr__(self, "cited_opinion_ids", tuple(sorted(set(self.cited_opinion_ids))))
        object.__setattr__(self, "cited_model_view_ids", tuple(sorted(set(self.cited_model_view_ids))))
        object.__setattr__(
            self,
            "overrides",
            tuple(sorted(self.overrides, key=lambda item: (item.source_kind.value, item.source_id))),
        )
        object.__setattr__(self, "blockers", _normalized_strings(self.blockers))
        object.__setattr__(self, "warnings", _normalized_strings(self.warnings))

    @property
    def decision_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "as_of": self.as_of.isoformat(),
            "fusion_input_id": self.fusion_input_id,
            "action": self.action.value,
            "conviction": self.conviction,
            "expected_alpha_score": self.expected_alpha_score,
            "rationale": self.rationale,
            "opposing_case": self.opposing_case,
            "invalidation_conditions": list(self.invalidation_conditions),
            "cited_opinion_ids": list(self.cited_opinion_ids),
            "cited_model_view_ids": list(self.cited_model_view_ids),
            "overrides": [
                {
                    "source_kind": item.source_kind.value,
                    "source_id": item.source_id,
                    "source_label": item.source_label,
                    "reason": item.reason,
                }
                for item in self.overrides
            ],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "reasoning_engine": self.reasoning_engine,
            "reasoning_engine_version": self.reasoning_engine_version,
            "research_only": self.research_only,
            "portfolio_construction_authorized": self.portfolio_construction_authorized,
            "execution_authorized": self.execution_authorized,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
            "may_override_risk_governor": self.may_override_risk_governor,
            "may_override_governance_lock": self.may_override_governance_lock,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CIOFusionRecord:
    """Validated pairing of CIO input and investment intent."""

    fusion_input: CIOFusionInput
    decision: CIOInvestmentDecision
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def fusion_record_id(self) -> str:
        payload = {
            "fusion_input_id": self.fusion_input.fusion_input_id,
            "decision_id": self.decision.decision_id,
            "status": self.status.value,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class CIOFusionValidator:
    """Validate CIO lineage and authority without performing the reasoning itself."""

    def validate(
        self,
        fusion_input: CIOFusionInput,
        decision: CIOInvestmentDecision,
    ) -> CIOFusionRecord:
        if (
            decision.security_id != fusion_input.security_id
            or decision.as_of != fusion_input.as_of
            or decision.fusion_input_id != fusion_input.fusion_input_id
        ):
            raise CIOFusionError("CIO_DECISION_CONTEXT_MISMATCH")

        opinion_ids = {item.opinion_id for item in fusion_input.council.opinions}
        model_ids = {item.model_view_id for item in fusion_input.quant_model_views}
        unknown_opinions = set(decision.cited_opinion_ids) - opinion_ids
        unknown_models = set(decision.cited_model_view_ids) - model_ids
        if unknown_opinions:
            raise CIOFusionError(
                f"CIO_CITES_UNKNOWN_OPINION:{','.join(sorted(unknown_opinions))}"
            )
        if unknown_models:
            raise CIOFusionError(f"CIO_CITES_UNKNOWN_MODEL:{','.join(sorted(unknown_models))}")
        if not decision.cited_opinion_ids:
            raise CIOFusionError("CIO_DECISION_REQUIRES_COUNCIL_CITATION")

        valid_override_ids = opinion_ids | model_ids
        for override in decision.overrides:
            if override.source_id not in valid_override_ids:
                raise CIOFusionError(f"CIO_OVERRIDE_SOURCE_UNKNOWN:{override.source_id}")
            if (
                override.source_kind is OverrideSourceKind.AGENT_OPINION
                and override.source_id not in opinion_ids
            ):
                raise CIOFusionError("CIO_OVERRIDE_SOURCE_KIND_MISMATCH")
            if (
                override.source_kind is OverrideSourceKind.QUANT_MODEL
                and override.source_id not in model_ids
            ):
                raise CIOFusionError("CIO_OVERRIDE_SOURCE_KIND_MISMATCH")

        blockers: list[str] = []
        warnings: list[str] = list(decision.warnings)
        if fusion_input.council.status is ReadinessStatus.BLOCKED:
            blockers.append("RESEARCH_COUNCIL_BLOCKED")
            if decision.action not in {InvestmentAction.WAIT, InvestmentAction.NO_ACTION}:
                raise CIOFusionError("BLOCKED_COUNCIL_REQUIRES_WAIT_OR_NO_ACTION")
        elif fusion_input.council.status is ReadinessStatus.WARNING:
            warnings.append("RESEARCH_COUNCIL_WARNING")

        blocked_models = [
            item.model_id
            for item in fusion_input.quant_model_views
            if item.status is ReadinessStatus.BLOCKED
        ]
        warnings.extend(f"BLOCKED_QUANT_MODEL:{model_id}" for model_id in blocked_models)
        degraded_context = [
            item.context_id
            for item in fusion_input.context_refs
            if item.status is not ReadinessStatus.PASS
        ]
        warnings.extend(f"DEGRADED_CIO_CONTEXT:{context_id}" for context_id in degraded_context)

        if decision.action in RISK_ON_ACTIONS and blockers:
            raise CIOFusionError("CIO_RISK_ON_ACTION_BLOCKED_BY_INPUT_READINESS")

        status = (
            ReadinessStatus.BLOCKED
            if blockers
            else ReadinessStatus.WARNING
            if warnings
            else ReadinessStatus.PASS
        )
        return CIOFusionRecord(
            fusion_input=fusion_input,
            decision=decision,
            status=status,
            blockers=tuple(sorted(set(blockers))),
            warnings=tuple(sorted(set(warnings))),
        )
