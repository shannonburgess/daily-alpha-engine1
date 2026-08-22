"""Point-in-time quantitative model governance for Agentic Intelligence V1.

This layer governs whether a QuantModelView has sufficient versioned validation evidence
to participate in CIO/Fusion research. Lifecycle stages and validation outcomes are model-
risk controls only; they never authorize portfolio construction, execution, capital, or live
trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .cio_fusion import QuantModelView
from .contracts import ReadinessStatus


class ModelGovernanceError(ValueError):
    """Model governance metadata or validation lineage violates the contract."""


class ModelLifecycleStage(StrEnum):
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    VALIDATED = "VALIDATED"
    RETIRED = "RETIRED"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelGovernanceError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise ModelGovernanceError("MODEL_GOVERNANCE_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise ModelGovernanceError(f"{field_name}_MUST_BE_FINITE")
    return value


@dataclass(frozen=True)
class ModelDefinition:
    model_id: str
    model_version: str
    owner: str
    stage: ModelLifecycleStage
    effective_at: datetime
    retired_at: datetime | None = None
    description: str = ""
    research_only: bool = True
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        model_id = self.model_id.strip().upper()
        version = self.model_version.strip()
        owner = self.owner.strip()
        if not model_id or not version or not owner:
            raise ModelGovernanceError("MODEL_DEFINITION_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelGovernanceError("MODEL_DEFINITION_MUST_REMAIN_RESEARCH_ONLY")
        effective = _aware_utc(self.effective_at, "MODEL_EFFECTIVE_AT")
        retired = _aware_utc(self.retired_at, "MODEL_RETIRED_AT") if self.retired_at else None
        if retired is not None and retired <= effective:
            raise ModelGovernanceError("MODEL_RETIREMENT_MUST_FOLLOW_EFFECTIVE_AT")
        if self.stage is ModelLifecycleStage.RETIRED and retired is None:
            raise ModelGovernanceError("RETIRED_MODEL_REQUIRES_RETIRED_AT")
        if self.stage is not ModelLifecycleStage.RETIRED and retired is not None:
            raise ModelGovernanceError("ACTIVE_MODEL_CANNOT_HAVE_RETIRED_AT")
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", version)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "retired_at", retired)
        object.__setattr__(self, "description", self.description.strip())

    @property
    def model_key(self) -> tuple[str, str]:
        return self.model_id, self.model_version

    @property
    def definition_id(self) -> str:
        return _digest(
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "owner": self.owner,
                "stage": self.stage.value,
                "effective_at": self.effective_at.isoformat(),
                "retired_at": self.retired_at.isoformat() if self.retired_at else None,
                "description": self.description,
                "research_only": self.research_only,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


class ModelRegistry:
    """Immutable model/version registry; a registered version cannot be silently redefined."""

    def __init__(self, definitions: tuple[ModelDefinition, ...] = ()) -> None:
        self._definitions: dict[tuple[str, str], ModelDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ModelDefinition) -> None:
        existing = self._definitions.get(definition.model_key)
        if existing is None:
            self._definitions[definition.model_key] = definition
            return
        if existing != definition:
            raise ModelGovernanceError(
                f"MODEL_DEFINITION_CONFLICT:{definition.model_id}:{definition.model_version}"
            )

    def get(self, model_id: str, model_version: str) -> ModelDefinition:
        key = model_id.strip().upper(), model_version.strip()
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise ModelGovernanceError(f"MODEL_NOT_REGISTERED:{key[0]}:{key[1]}") from exc

    def definitions(self) -> tuple[ModelDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    @property
    def registry_id(self) -> str:
        return _digest([item.definition_id for item in self.definitions()])


@dataclass(frozen=True)
class ModelValidationRecord:
    model_id: str
    model_version: str
    as_of: datetime
    window_start: datetime
    window_end: datetime
    sample_size: int
    expectancy_r: float
    sharpe: float
    sortino: float
    max_drawdown: float
    profit_factor: float
    stability_score: float
    input_lineage_ids: tuple[str, ...]
    validation_method: str = "OUT_OF_SAMPLE"
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        model_id = self.model_id.strip().upper()
        version = self.model_version.strip()
        method = self.validation_method.strip().upper()
        if not model_id or not version or not method:
            raise ModelGovernanceError("MODEL_VALIDATION_IDENTITY_REQUIRED")
        if self.sample_size <= 0:
            raise ModelGovernanceError("MODEL_VALIDATION_SAMPLE_SIZE_MUST_BE_POSITIVE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ModelGovernanceError("MODEL_VALIDATION_MUST_REMAIN_RESEARCH_ONLY")
        boundary = _aware_utc(self.as_of, "MODEL_VALIDATION_AS_OF")
        start = _aware_utc(self.window_start, "MODEL_VALIDATION_WINDOW_START")
        end = _aware_utc(self.window_end, "MODEL_VALIDATION_WINDOW_END")
        if start >= end:
            raise ModelGovernanceError("MODEL_VALIDATION_WINDOW_INVALID")
        if end > boundary:
            raise ModelGovernanceError("MODEL_VALIDATION_WINDOW_END_AFTER_AS_OF")
        for field_name in ("expectancy_r", "sharpe", "sortino", "max_drawdown", "profit_factor"):
            _finite(getattr(self, field_name), f"MODEL_VALIDATION_{field_name.upper()}")
        _finite(self.stability_score, "MODEL_VALIDATION_STABILITY_SCORE")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ModelGovernanceError("MODEL_VALIDATION_MAX_DRAWDOWN_OUT_OF_RANGE")
        if self.profit_factor < 0:
            raise ModelGovernanceError("MODEL_VALIDATION_PROFIT_FACTOR_NEGATIVE")
        if not 0.0 <= self.stability_score <= 1.0:
            raise ModelGovernanceError("MODEL_VALIDATION_STABILITY_OUT_OF_RANGE")
        lineage = tuple(sorted({item.strip().lower() for item in self.input_lineage_ids if item.strip()}))
        if not lineage:
            raise ModelGovernanceError("MODEL_VALIDATION_INPUT_LINEAGE_REQUIRED")
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", version)
        object.__setattr__(self, "validation_method", method)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "input_lineage_ids", lineage)

    @property
    def model_key(self) -> tuple[str, str]:
        return self.model_id, self.model_version

    @property
    def validation_id(self) -> str:
        return _digest(
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "as_of": self.as_of.isoformat(),
                "window_start": self.window_start.isoformat(),
                "window_end": self.window_end.isoformat(),
                "sample_size": self.sample_size,
                "expectancy_r": self.expectancy_r,
                "sharpe": self.sharpe,
                "sortino": self.sortino,
                "max_drawdown": self.max_drawdown,
                "profit_factor": self.profit_factor,
                "stability_score": self.stability_score,
                "input_lineage_ids": list(self.input_lineage_ids),
                "validation_method": self.validation_method,
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class ModelGovernancePolicy:
    min_sample_size: int = 50
    min_expectancy_r: float = 0.0
    min_sharpe: float = 0.75
    min_sortino: float = 1.0
    max_drawdown: float = 0.20
    min_profit_factor: float = 1.10
    min_stability_score: float = 0.60
    eligible_stages: tuple[ModelLifecycleStage, ...] = (
        ModelLifecycleStage.SHADOW,
        ModelLifecycleStage.VALIDATED,
    )
    validated_stage_warn_only: bool = False

    def __post_init__(self) -> None:
        if self.min_sample_size <= 0:
            raise ModelGovernanceError("MODEL_POLICY_MIN_SAMPLE_SIZE_MUST_BE_POSITIVE")
        for field_name in (
            "min_expectancy_r",
            "min_sharpe",
            "min_sortino",
            "max_drawdown",
            "min_profit_factor",
            "min_stability_score",
        ):
            _finite(getattr(self, field_name), f"MODEL_POLICY_{field_name.upper()}")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ModelGovernanceError("MODEL_POLICY_MAX_DRAWDOWN_OUT_OF_RANGE")
        if not 0.0 <= self.min_stability_score <= 1.0:
            raise ModelGovernanceError("MODEL_POLICY_STABILITY_OUT_OF_RANGE")
        stages = tuple(sorted(set(self.eligible_stages)))
        if not stages:
            raise ModelGovernanceError("MODEL_POLICY_ELIGIBLE_STAGES_REQUIRED")
        if ModelLifecycleStage.RETIRED in stages:
            raise ModelGovernanceError("MODEL_POLICY_CANNOT_ELIGIBLE_RETIRED_STAGE")
        object.__setattr__(self, "eligible_stages", stages)

    @property
    def policy_id(self) -> str:
        return _digest(
            {
                "min_sample_size": self.min_sample_size,
                "min_expectancy_r": self.min_expectancy_r,
                "min_sharpe": self.min_sharpe,
                "min_sortino": self.min_sortino,
                "max_drawdown": self.max_drawdown,
                "min_profit_factor": self.min_profit_factor,
                "min_stability_score": self.min_stability_score,
                "eligible_stages": [stage.value for stage in self.eligible_stages],
                "validated_stage_warn_only": self.validated_stage_warn_only,
            }
        )


@dataclass(frozen=True)
class ModelGovernanceAssessment:
    model_view_id: str
    model_id: str
    model_version: str
    definition_id: str
    lifecycle_stage: ModelLifecycleStage
    validation_id: str | None
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    eligible_for_cio_research: bool
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not all(
            (
                self.model_view_id.strip(),
                self.model_id.strip(),
                self.model_version.strip(),
                self.definition_id.strip(),
            )
        ):
            raise ModelGovernanceError("MODEL_ASSESSMENT_IDENTITY_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ModelGovernanceError("MODEL_ASSESSMENT_MUST_REMAIN_RESEARCH_ONLY")
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.eligible_for_cio_research and self.status is ReadinessStatus.BLOCKED:
            raise ModelGovernanceError("BLOCKED_MODEL_CANNOT_BE_CIO_ELIGIBLE")
        if not self.eligible_for_cio_research and self.status is not ReadinessStatus.BLOCKED:
            raise ModelGovernanceError("INELIGIBLE_MODEL_MUST_BE_BLOCKED")
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ModelGovernanceError("PASS_MODEL_ASSESSMENT_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ModelGovernanceError("WARNING_MODEL_ASSESSMENT_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "model_view_id", self.model_view_id.strip().lower())
        object.__setattr__(self, "model_id", self.model_id.strip().upper())
        object.__setattr__(self, "model_version", self.model_version.strip())
        object.__setattr__(self, "definition_id", self.definition_id.strip().lower())
        if self.validation_id is not None:
            object.__setattr__(self, "validation_id", self.validation_id.strip().lower())
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def assessment_id(self) -> str:
        return _digest(
            {
                "model_view_id": self.model_view_id,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "definition_id": self.definition_id,
                "lifecycle_stage": self.lifecycle_stage.value,
                "validation_id": self.validation_id,
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "eligible_for_cio_research": self.eligible_for_cio_research,
                "research_only": self.research_only,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class ModelGovernancePacket:
    security_id: str
    as_of: datetime
    registry_id: str
    policy_id: str
    assessments: tuple[ModelGovernanceAssessment, ...]
    eligible_model_view_ids: tuple[str, ...]
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security = self.security_id.strip().upper()
        if not security or not self.registry_id.strip() or not self.policy_id.strip():
            raise ModelGovernanceError("MODEL_GOVERNANCE_PACKET_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelGovernanceError("MODEL_GOVERNANCE_PACKET_MUST_REMAIN_RESEARCH_ONLY")
        boundary = _aware_utc(self.as_of, "MODEL_GOVERNANCE_PACKET_AS_OF")
        assessments = tuple(sorted(self.assessments, key=lambda item: item.assessment_id))
        eligible = tuple(sorted(set(self.eligible_model_view_ids)))
        assessment_eligible = tuple(
            sorted(item.model_view_id for item in assessments if item.eligible_for_cio_research)
        )
        if eligible != assessment_eligible:
            raise ModelGovernanceError("MODEL_GOVERNANCE_ELIGIBLE_SET_MISMATCH")
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ModelGovernanceError("PASS_MODEL_GOVERNANCE_PACKET_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ModelGovernanceError("WARNING_MODEL_GOVERNANCE_PACKET_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "security_id", security)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "registry_id", self.registry_id.strip().lower())
        object.__setattr__(self, "policy_id", self.policy_id.strip().lower())
        object.__setattr__(self, "assessments", assessments)
        object.__setattr__(self, "eligible_model_view_ids", eligible)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def packet_id(self) -> str:
        return _digest(
            {
                "security_id": self.security_id,
                "as_of": self.as_of.isoformat(),
                "registry_id": self.registry_id,
                "policy_id": self.policy_id,
                "assessment_ids": [item.assessment_id for item in self.assessments],
                "eligible_model_view_ids": list(self.eligible_model_view_ids),
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "research_only": self.research_only,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )

    def assert_views_eligible(self, views: tuple[QuantModelView, ...]) -> None:
        for view in views:
            if view.security_id != self.security_id:
                raise ModelGovernanceError("MODEL_GOVERNANCE_PACKET_SECURITY_MISMATCH")
            if view.as_of > self.as_of:
                raise ModelGovernanceError("FUTURE_MODEL_VIEW_NOT_ALLOWED_BY_GOVERNANCE_PACKET")
            if view.model_view_id not in self.eligible_model_view_ids:
                raise ModelGovernanceError(
                    f"MODEL_VIEW_NOT_GOVERNANCE_ELIGIBLE:{view.model_id}:{view.model_version}"
                )


class ModelGovernanceEngine:
    """Evaluate QuantModelView eligibility from only validation evidence available then."""

    def __init__(self, *, registry: ModelRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _latest_validation(
        view: QuantModelView,
        validations: tuple[ModelValidationRecord, ...],
    ) -> ModelValidationRecord | None:
        candidates = [
            item
            for item in validations
            if item.model_key == (view.model_id, view.model_version) and item.as_of <= view.as_of
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.as_of, item.validation_id))
        return candidates[-1]

    @staticmethod
    def _validation_issues(
        validation: ModelValidationRecord,
        policy: ModelGovernancePolicy,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if validation.sample_size < policy.min_sample_size:
            blockers.append(
                f"MODEL_SAMPLE_SIZE_BELOW_POLICY:{validation.sample_size}<{policy.min_sample_size}"
            )
        checks = (
            (validation.expectancy_r, policy.min_expectancy_r, "EXPECTANCY_R_BELOW_POLICY"),
            (validation.sharpe, policy.min_sharpe, "SHARPE_BELOW_POLICY"),
            (validation.sortino, policy.min_sortino, "SORTINO_BELOW_POLICY"),
            (validation.profit_factor, policy.min_profit_factor, "PROFIT_FACTOR_BELOW_POLICY"),
            (validation.stability_score, policy.min_stability_score, "STABILITY_BELOW_POLICY"),
        )
        for actual, threshold, reason in checks:
            if actual < threshold:
                blockers.append(f"{reason}:{actual:.6f}<{threshold:.6f}")
        if validation.max_drawdown > policy.max_drawdown:
            blockers.append(
                f"MAX_DRAWDOWN_ABOVE_POLICY:{validation.max_drawdown:.6f}>"
                f"{policy.max_drawdown:.6f}"
            )
        return tuple(sorted(blockers))

    def assess_view(
        self,
        *,
        view: QuantModelView,
        validations: tuple[ModelValidationRecord, ...],
        policy: ModelGovernancePolicy,
    ) -> ModelGovernanceAssessment:
        definition = self.registry.get(view.model_id, view.model_version)
        blockers: list[str] = []
        warnings: list[str] = []
        if view.as_of < definition.effective_at:
            blockers.append("MODEL_VIEW_PRECEDES_DEFINITION_EFFECTIVE_AT")
        if definition.stage is ModelLifecycleStage.RETIRED:
            blockers.append("MODEL_VERSION_RETIRED")
        elif definition.stage not in policy.eligible_stages:
            blockers.append(f"MODEL_STAGE_NOT_ELIGIBLE:{definition.stage.value}")
        if view.status is ReadinessStatus.BLOCKED:
            blockers.append("QUANT_MODEL_VIEW_BLOCKED")
        elif view.status is ReadinessStatus.WARNING:
            warnings.append("QUANT_MODEL_VIEW_WARNING")
        if not view.input_lineage_ids:
            blockers.append("QUANT_MODEL_VIEW_INPUT_LINEAGE_REQUIRED")

        validation = self._latest_validation(view, validations)
        if validation is None:
            blockers.append("MODEL_VALIDATION_NOT_AVAILABLE_AS_OF_VIEW")
        else:
            validation_blockers = self._validation_issues(validation, policy)
            if validation_blockers and (
                definition.stage is ModelLifecycleStage.VALIDATED
                and policy.validated_stage_warn_only
            ):
                warnings.extend(validation_blockers)
            else:
                blockers.extend(validation_blockers)

        if blockers:
            status = ReadinessStatus.BLOCKED
        elif warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return ModelGovernanceAssessment(
            model_view_id=view.model_view_id,
            model_id=view.model_id,
            model_version=view.model_version,
            definition_id=definition.definition_id,
            lifecycle_stage=definition.stage,
            validation_id=validation.validation_id if validation else None,
            status=status,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            eligible_for_cio_research=status is not ReadinessStatus.BLOCKED,
        )

    def evaluate(
        self,
        *,
        security_id: str,
        as_of: datetime,
        views: tuple[QuantModelView, ...],
        validations: tuple[ModelValidationRecord, ...],
        policy: ModelGovernancePolicy | None = None,
    ) -> ModelGovernancePacket:
        security = security_id.strip().upper()
        boundary = _aware_utc(as_of, "MODEL_GOVERNANCE_AS_OF")
        if not security:
            raise ModelGovernanceError("MODEL_GOVERNANCE_SECURITY_REQUIRED")
        active_policy = policy or ModelGovernancePolicy()
        unique_views: dict[str, QuantModelView] = {}
        for view in views:
            if view.security_id != security:
                raise ModelGovernanceError("MODEL_VIEW_SECURITY_MISMATCH")
            if view.as_of > boundary:
                raise ModelGovernanceError("FUTURE_MODEL_VIEW_NOT_ALLOWED")
            unique_views.setdefault(view.model_view_id, view)
        assessments = tuple(
            self.assess_view(
                view=view,
                validations=validations,
                policy=active_policy,
            )
            for view in sorted(unique_views.values(), key=lambda item: item.model_view_id)
        )
        blockers = tuple(
            sorted(
                {
                    f"MODEL:{item.model_id}:{item.model_version}:{reason}"
                    for item in assessments
                    for reason in item.blockers
                }
            )
        )
        warnings = tuple(
            sorted(
                {
                    f"MODEL:{item.model_id}:{item.model_version}:{reason}"
                    for item in assessments
                    for reason in item.warnings
                }
            )
        )
        eligible = tuple(
            sorted(item.model_view_id for item in assessments if item.eligible_for_cio_research)
        )
        if blockers:
            status = ReadinessStatus.BLOCKED
        elif warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return ModelGovernancePacket(
            security_id=security,
            as_of=boundary,
            registry_id=self.registry.registry_id,
            policy_id=active_policy.policy_id,
            assessments=assessments,
            eligible_model_view_ids=eligible,
            status=status,
            blockers=blockers,
            warnings=warnings,
        )
