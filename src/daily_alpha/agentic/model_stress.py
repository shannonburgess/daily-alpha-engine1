"""Point-in-time model stress testing and regime robustness for Daily Alpha.

This layer sits above Stage 9G model governance. It can further restrict which governed
quant-model views are considered stress-qualified for CIO/Fusion research, but it cannot
authorize portfolio construction, execution, capital, broker routing, or live trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .cio_fusion import QuantModelView
from .contracts import ReadinessStatus
from .model_governance import ModelGovernanceAssessment, ModelGovernancePacket


class ModelStressError(ValueError):
    """Stress scenario, result, or governance lineage violates the institutional contract."""


class StressScenarioClass(StrEnum):
    HISTORICAL_SHOCK = "HISTORICAL_SHOCK"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS"
    CORRELATION_SHOCK = "CORRELATION_SHOCK"
    MACRO_SHOCK = "MACRO_SHOCK"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelStressError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise ModelStressError("MODEL_STRESS_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise ModelStressError(f"{field_name}_MUST_BE_FINITE")
    return value


@dataclass(frozen=True)
class StressScenarioDefinition:
    scenario_id: str
    scenario_version: str
    scenario_class: StressScenarioClass
    effective_at: datetime
    description: str = ""
    research_only: bool = True
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        scenario_id = self.scenario_id.strip().upper()
        version = self.scenario_version.strip()
        if not scenario_id or not version:
            raise ModelStressError("STRESS_SCENARIO_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelStressError("STRESS_SCENARIO_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "scenario_version", version)
        object.__setattr__(
            self,
            "effective_at",
            _aware_utc(self.effective_at, "STRESS_SCENARIO_EFFECTIVE_AT"),
        )
        object.__setattr__(self, "description", self.description.strip())

    @property
    def scenario_key(self) -> tuple[str, str]:
        return self.scenario_id, self.scenario_version

    @property
    def definition_id(self) -> str:
        return _digest(
            {
                "scenario_id": self.scenario_id,
                "scenario_version": self.scenario_version,
                "scenario_class": self.scenario_class.value,
                "effective_at": self.effective_at.isoformat(),
                "description": self.description,
                "research_only": self.research_only,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


class StressScenarioRegistry:
    """Immutable registry of versioned institutional stress scenarios."""

    def __init__(self, definitions: tuple[StressScenarioDefinition, ...] = ()) -> None:
        self._definitions: dict[tuple[str, str], StressScenarioDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: StressScenarioDefinition) -> None:
        existing = self._definitions.get(definition.scenario_key)
        if existing is None:
            self._definitions[definition.scenario_key] = definition
            return
        if existing != definition:
            raise ModelStressError(
                f"STRESS_SCENARIO_CONFLICT:{definition.scenario_id}:"
                f"{definition.scenario_version}"
            )

    def get(self, scenario_id: str, scenario_version: str) -> StressScenarioDefinition:
        key = scenario_id.strip().upper(), scenario_version.strip()
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise ModelStressError(f"STRESS_SCENARIO_NOT_REGISTERED:{key[0]}:{key[1]}") from exc

    def active(self, as_of: datetime) -> tuple[StressScenarioDefinition, ...]:
        boundary = _aware_utc(as_of, "STRESS_SCENARIO_REGISTRY_AS_OF")
        return tuple(
            sorted(
                (item for item in self._definitions.values() if item.effective_at <= boundary),
                key=lambda item: item.scenario_key,
            )
        )

    @property
    def registry_id(self) -> str:
        return _digest(
            [
                item.definition_id
                for item in sorted(self._definitions.values(), key=lambda value: value.scenario_key)
            ]
        )


@dataclass(frozen=True)
class ModelStressResult:
    model_id: str
    model_version: str
    scenario_id: str
    scenario_version: str
    known_at: datetime
    window_start: datetime
    window_end: datetime
    sample_size: int
    expectancy_r: float
    sharpe: float
    max_drawdown: float
    worst_loss_r: float
    recovery_periods: int
    capacity_retention: float
    stability_score: float
    input_lineage_ids: tuple[str, ...]
    research_only: bool = True
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        model_id = self.model_id.strip().upper()
        version = self.model_version.strip()
        scenario_id = self.scenario_id.strip().upper()
        scenario_version = self.scenario_version.strip()
        if not all((model_id, version, scenario_id, scenario_version)):
            raise ModelStressError("MODEL_STRESS_RESULT_IDENTITY_REQUIRED")
        if self.sample_size <= 0:
            raise ModelStressError("MODEL_STRESS_SAMPLE_SIZE_MUST_BE_POSITIVE")
        if self.recovery_periods < 0:
            raise ModelStressError("MODEL_STRESS_RECOVERY_PERIODS_NEGATIVE")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelStressError("MODEL_STRESS_RESULT_MUST_REMAIN_RESEARCH_ONLY")
        known = _aware_utc(self.known_at, "MODEL_STRESS_KNOWN_AT")
        start = _aware_utc(self.window_start, "MODEL_STRESS_WINDOW_START")
        end = _aware_utc(self.window_end, "MODEL_STRESS_WINDOW_END")
        if start >= end:
            raise ModelStressError("MODEL_STRESS_WINDOW_INVALID")
        if end > known:
            raise ModelStressError("MODEL_STRESS_WINDOW_END_AFTER_KNOWN_AT")
        for field_name in (
            "expectancy_r",
            "sharpe",
            "max_drawdown",
            "worst_loss_r",
            "capacity_retention",
            "stability_score",
        ):
            _finite(getattr(self, field_name), f"MODEL_STRESS_{field_name.upper()}")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ModelStressError("MODEL_STRESS_MAX_DRAWDOWN_OUT_OF_RANGE")
        if not 0.0 <= self.capacity_retention <= 1.0:
            raise ModelStressError("MODEL_STRESS_CAPACITY_RETENTION_OUT_OF_RANGE")
        if not 0.0 <= self.stability_score <= 1.0:
            raise ModelStressError("MODEL_STRESS_STABILITY_OUT_OF_RANGE")
        lineage = tuple(sorted({item.strip().lower() for item in self.input_lineage_ids if item.strip()}))
        if not lineage:
            raise ModelStressError("MODEL_STRESS_INPUT_LINEAGE_REQUIRED")
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", version)
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "scenario_version", scenario_version)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "input_lineage_ids", lineage)

    @property
    def model_key(self) -> tuple[str, str]:
        return self.model_id, self.model_version

    @property
    def scenario_key(self) -> tuple[str, str]:
        return self.scenario_id, self.scenario_version

    @property
    def result_id(self) -> str:
        return _digest(
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "scenario_id": self.scenario_id,
                "scenario_version": self.scenario_version,
                "known_at": self.known_at.isoformat(),
                "window_start": self.window_start.isoformat(),
                "window_end": self.window_end.isoformat(),
                "sample_size": self.sample_size,
                "expectancy_r": self.expectancy_r,
                "sharpe": self.sharpe,
                "max_drawdown": self.max_drawdown,
                "worst_loss_r": self.worst_loss_r,
                "recovery_periods": self.recovery_periods,
                "capacity_retention": self.capacity_retention,
                "stability_score": self.stability_score,
                "input_lineage_ids": list(self.input_lineage_ids),
                "research_only": self.research_only,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class ModelStressPolicy:
    min_scenarios: int = 5
    required_classes: tuple[StressScenarioClass, ...] = (
        StressScenarioClass.HISTORICAL_SHOCK,
        StressScenarioClass.TREND_DOWN,
        StressScenarioClass.HIGH_VOLATILITY,
        StressScenarioClass.LIQUIDITY_STRESS,
        StressScenarioClass.MACRO_SHOCK,
    )
    min_expectancy_r: float = -0.25
    min_sharpe: float = -0.50
    max_drawdown: float = 0.35
    min_worst_loss_r: float = -3.0
    max_recovery_periods: int = 30
    min_capacity_retention: float = 0.50
    min_stability_score: float = 0.40
    min_pass_ratio: float = 0.80

    def __post_init__(self) -> None:
        if self.min_scenarios <= 0:
            raise ModelStressError("MODEL_STRESS_POLICY_MIN_SCENARIOS_MUST_BE_POSITIVE")
        if self.max_recovery_periods < 0:
            raise ModelStressError("MODEL_STRESS_POLICY_MAX_RECOVERY_NEGATIVE")
        for field_name in (
            "min_expectancy_r",
            "min_sharpe",
            "max_drawdown",
            "min_worst_loss_r",
            "min_capacity_retention",
            "min_stability_score",
            "min_pass_ratio",
        ):
            _finite(getattr(self, field_name), f"MODEL_STRESS_POLICY_{field_name.upper()}")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ModelStressError("MODEL_STRESS_POLICY_MAX_DRAWDOWN_OUT_OF_RANGE")
        if not 0.0 <= self.min_capacity_retention <= 1.0:
            raise ModelStressError("MODEL_STRESS_POLICY_CAPACITY_OUT_OF_RANGE")
        if not 0.0 <= self.min_stability_score <= 1.0:
            raise ModelStressError("MODEL_STRESS_POLICY_STABILITY_OUT_OF_RANGE")
        if not 0.0 <= self.min_pass_ratio <= 1.0:
            raise ModelStressError("MODEL_STRESS_POLICY_PASS_RATIO_OUT_OF_RANGE")
        required = tuple(sorted(set(self.required_classes)))
        if not required:
            raise ModelStressError("MODEL_STRESS_POLICY_REQUIRED_CLASSES_EMPTY")
        object.__setattr__(self, "required_classes", required)

    @property
    def policy_id(self) -> str:
        return _digest(
            {
                "min_scenarios": self.min_scenarios,
                "required_classes": [item.value for item in self.required_classes],
                "min_expectancy_r": self.min_expectancy_r,
                "min_sharpe": self.min_sharpe,
                "max_drawdown": self.max_drawdown,
                "min_worst_loss_r": self.min_worst_loss_r,
                "max_recovery_periods": self.max_recovery_periods,
                "min_capacity_retention": self.min_capacity_retention,
                "min_stability_score": self.min_stability_score,
                "min_pass_ratio": self.min_pass_ratio,
            }
        )


@dataclass(frozen=True)
class ScenarioStressAssessment:
    scenario_definition_id: str
    stress_result_id: str
    scenario_class: StressScenarioClass
    passed: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.scenario_definition_id.strip() or not self.stress_result_id.strip():
            raise ModelStressError("SCENARIO_STRESS_ASSESSMENT_IDENTITY_REQUIRED")
        reasons = tuple(sorted(set(self.reasons)))
        if self.passed and reasons:
            raise ModelStressError("PASSED_SCENARIO_STRESS_CANNOT_HAVE_FAILURE_REASONS")
        if not self.passed and not reasons:
            raise ModelStressError("FAILED_SCENARIO_STRESS_REQUIRES_REASON")
        object.__setattr__(self, "scenario_definition_id", self.scenario_definition_id.lower())
        object.__setattr__(self, "stress_result_id", self.stress_result_id.lower())
        object.__setattr__(self, "reasons", reasons)

    @property
    def assessment_id(self) -> str:
        return _digest(
            {
                "scenario_definition_id": self.scenario_definition_id,
                "stress_result_id": self.stress_result_id,
                "scenario_class": self.scenario_class.value,
                "passed": self.passed,
                "reasons": list(self.reasons),
            }
        )


@dataclass(frozen=True)
class ModelStressAssessment:
    model_view_id: str
    model_id: str
    model_version: str
    upstream_governance_assessment_id: str
    scenario_assessments: tuple[ScenarioStressAssessment, ...]
    covered_classes: tuple[StressScenarioClass, ...]
    pass_ratio: float
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    stress_qualified_for_cio_research: bool
    research_only: bool = True
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not all(
            (
                self.model_view_id.strip(),
                self.model_id.strip(),
                self.model_version.strip(),
                self.upstream_governance_assessment_id.strip(),
            )
        ):
            raise ModelStressError("MODEL_STRESS_ASSESSMENT_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelStressError("MODEL_STRESS_ASSESSMENT_MUST_REMAIN_RESEARCH_ONLY")
        if not math.isfinite(self.pass_ratio) or not 0.0 <= self.pass_ratio <= 1.0:
            raise ModelStressError("MODEL_STRESS_ASSESSMENT_PASS_RATIO_OUT_OF_RANGE")
        scenario_assessments = tuple(
            sorted(self.scenario_assessments, key=lambda item: item.assessment_id)
        )
        covered = tuple(sorted(set(self.covered_classes)))
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.stress_qualified_for_cio_research and self.status is ReadinessStatus.BLOCKED:
            raise ModelStressError("BLOCKED_MODEL_CANNOT_BE_STRESS_QUALIFIED")
        if not self.stress_qualified_for_cio_research and self.status is not ReadinessStatus.BLOCKED:
            raise ModelStressError("UNQUALIFIED_MODEL_STRESS_MUST_BE_BLOCKED")
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ModelStressError("PASS_MODEL_STRESS_ASSESSMENT_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ModelStressError("WARNING_MODEL_STRESS_ASSESSMENT_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "model_view_id", self.model_view_id.lower())
        object.__setattr__(self, "model_id", self.model_id.upper())
        object.__setattr__(self, "upstream_governance_assessment_id", self.upstream_governance_assessment_id.lower())
        object.__setattr__(self, "scenario_assessments", scenario_assessments)
        object.__setattr__(self, "covered_classes", covered)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def assessment_id(self) -> str:
        return _digest(
            {
                "model_view_id": self.model_view_id,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "upstream_governance_assessment_id": self.upstream_governance_assessment_id,
                "scenario_assessment_ids": [item.assessment_id for item in self.scenario_assessments],
                "covered_classes": [item.value for item in self.covered_classes],
                "pass_ratio": self.pass_ratio,
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "stress_qualified_for_cio_research": self.stress_qualified_for_cio_research,
                "research_only": self.research_only,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class ModelStressPacket:
    security_id: str
    as_of: datetime
    upstream_governance_packet_id: str
    scenario_registry_id: str
    policy_id: str
    assessments: tuple[ModelStressAssessment, ...]
    stress_qualified_model_view_ids: tuple[str, ...]
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
        if not all(
            (
                security,
                self.upstream_governance_packet_id.strip(),
                self.scenario_registry_id.strip(),
                self.policy_id.strip(),
            )
        ):
            raise ModelStressError("MODEL_STRESS_PACKET_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelStressError("MODEL_STRESS_PACKET_MUST_REMAIN_RESEARCH_ONLY")
        assessments = tuple(sorted(self.assessments, key=lambda item: item.assessment_id))
        qualified = tuple(sorted(set(self.stress_qualified_model_view_ids)))
        expected = tuple(
            sorted(
                item.model_view_id
                for item in assessments
                if item.stress_qualified_for_cio_research
            )
        )
        if qualified != expected:
            raise ModelStressError("MODEL_STRESS_QUALIFIED_SET_MISMATCH")
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ModelStressError("PASS_MODEL_STRESS_PACKET_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ModelStressError("WARNING_MODEL_STRESS_PACKET_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "security_id", security)
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "MODEL_STRESS_PACKET_AS_OF"))
        object.__setattr__(self, "upstream_governance_packet_id", self.upstream_governance_packet_id.lower())
        object.__setattr__(self, "scenario_registry_id", self.scenario_registry_id.lower())
        object.__setattr__(self, "policy_id", self.policy_id.lower())
        object.__setattr__(self, "assessments", assessments)
        object.__setattr__(self, "stress_qualified_model_view_ids", qualified)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def packet_id(self) -> str:
        return _digest(
            {
                "security_id": self.security_id,
                "as_of": self.as_of.isoformat(),
                "upstream_governance_packet_id": self.upstream_governance_packet_id,
                "scenario_registry_id": self.scenario_registry_id,
                "policy_id": self.policy_id,
                "assessment_ids": [item.assessment_id for item in self.assessments],
                "stress_qualified_model_view_ids": list(self.stress_qualified_model_view_ids),
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

    def assert_views_stress_qualified(self, views: tuple[QuantModelView, ...]) -> None:
        for view in views:
            if view.security_id != self.security_id:
                raise ModelStressError("MODEL_STRESS_PACKET_SECURITY_MISMATCH")
            if view.as_of > self.as_of:
                raise ModelStressError("FUTURE_MODEL_VIEW_NOT_ALLOWED_BY_STRESS_PACKET")
            if view.model_view_id not in self.stress_qualified_model_view_ids:
                raise ModelStressError(
                    f"MODEL_VIEW_NOT_STRESS_QUALIFIED:{view.model_id}:{view.model_version}"
                )


class ModelStressEngine:
    """Evaluate scenario robustness using only results known by each model-view boundary."""

    def __init__(self, *, scenario_registry: StressScenarioRegistry) -> None:
        self.scenario_registry = scenario_registry

    @staticmethod
    def _scenario_failure_reasons(
        result: ModelStressResult,
        policy: ModelStressPolicy,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        checks = (
            (result.expectancy_r, policy.min_expectancy_r, "STRESSED_EXPECTANCY_BELOW_POLICY"),
            (result.sharpe, policy.min_sharpe, "STRESSED_SHARPE_BELOW_POLICY"),
            (
                result.capacity_retention,
                policy.min_capacity_retention,
                "STRESSED_CAPACITY_RETENTION_BELOW_POLICY",
            ),
            (
                result.stability_score,
                policy.min_stability_score,
                "STRESSED_STABILITY_BELOW_POLICY",
            ),
        )
        for actual, threshold, reason in checks:
            if actual < threshold:
                reasons.append(f"{reason}:{actual:.6f}<{threshold:.6f}")
        if result.max_drawdown > policy.max_drawdown:
            reasons.append(
                f"STRESSED_MAX_DRAWDOWN_ABOVE_POLICY:{result.max_drawdown:.6f}>"
                f"{policy.max_drawdown:.6f}"
            )
        if result.worst_loss_r < policy.min_worst_loss_r:
            reasons.append(
                f"STRESSED_WORST_LOSS_BELOW_POLICY:{result.worst_loss_r:.6f}<"
                f"{policy.min_worst_loss_r:.6f}"
            )
        if result.recovery_periods > policy.max_recovery_periods:
            reasons.append(
                f"STRESSED_RECOVERY_ABOVE_POLICY:{result.recovery_periods}>"
                f"{policy.max_recovery_periods}"
            )
        return tuple(sorted(reasons))

    @staticmethod
    def _latest_results(
        *,
        view: QuantModelView,
        results: tuple[ModelStressResult, ...],
    ) -> dict[tuple[str, str], ModelStressResult]:
        latest: dict[tuple[str, str], ModelStressResult] = {}
        for result in results:
            if result.model_key != (view.model_id, view.model_version):
                continue
            if result.known_at > view.as_of:
                continue
            existing = latest.get(result.scenario_key)
            if existing is None or (result.known_at, result.result_id) > (
                existing.known_at,
                existing.result_id,
            ):
                latest[result.scenario_key] = result
        return latest

    def assess_view(
        self,
        *,
        view: QuantModelView,
        governance_assessment: ModelGovernanceAssessment,
        results: tuple[ModelStressResult, ...],
        policy: ModelStressPolicy,
    ) -> ModelStressAssessment:
        if governance_assessment.model_view_id != view.model_view_id:
            raise ModelStressError("MODEL_STRESS_GOVERNANCE_VIEW_MISMATCH")
        if governance_assessment.model_id != view.model_id:
            raise ModelStressError("MODEL_STRESS_GOVERNANCE_MODEL_MISMATCH")
        if governance_assessment.model_version != view.model_version:
            raise ModelStressError("MODEL_STRESS_GOVERNANCE_VERSION_MISMATCH")

        blockers: list[str] = []
        warnings: list[str] = []
        if not governance_assessment.eligible_for_cio_research:
            blockers.append("UPSTREAM_MODEL_GOVERNANCE_BLOCKED")

        active_definitions = {
            item.scenario_key: item for item in self.scenario_registry.active(view.as_of)
        }
        latest = self._latest_results(view=view, results=results)
        assessments: list[ScenarioStressAssessment] = []
        covered_classes: set[StressScenarioClass] = set()
        passing_classes: set[StressScenarioClass] = set()
        for scenario_key, result in sorted(latest.items()):
            definition = active_definitions.get(scenario_key)
            if definition is None:
                blockers.append(
                    f"STRESS_RESULT_SCENARIO_NOT_ACTIVE:{result.scenario_id}:"
                    f"{result.scenario_version}"
                )
                continue
            covered_classes.add(definition.scenario_class)
            reasons = self._scenario_failure_reasons(result, policy)
            passed = not reasons
            if passed:
                passing_classes.add(definition.scenario_class)
            else:
                warnings.extend(
                    f"SCENARIO:{definition.scenario_id}:{reason}" for reason in reasons
                )
            assessments.append(
                ScenarioStressAssessment(
                    scenario_definition_id=definition.definition_id,
                    stress_result_id=result.result_id,
                    scenario_class=definition.scenario_class,
                    passed=passed,
                    reasons=reasons,
                )
            )

        if len(assessments) < policy.min_scenarios:
            blockers.append(
                f"STRESS_SCENARIO_COUNT_BELOW_POLICY:{len(assessments)}<{policy.min_scenarios}"
            )
        missing_classes = sorted(set(policy.required_classes) - covered_classes)
        blockers.extend(f"REQUIRED_STRESS_CLASS_MISSING:{item.value}" for item in missing_classes)
        failed_required = sorted(set(policy.required_classes) & covered_classes - passing_classes)
        blockers.extend(f"REQUIRED_STRESS_CLASS_FAILED:{item.value}" for item in failed_required)

        passed_count = sum(item.passed for item in assessments)
        pass_ratio = passed_count / len(assessments) if assessments else 0.0
        if pass_ratio < policy.min_pass_ratio:
            blockers.append(
                f"STRESS_PASS_RATIO_BELOW_POLICY:{pass_ratio:.6f}<{policy.min_pass_ratio:.6f}"
            )
        if blockers:
            status = ReadinessStatus.BLOCKED
        elif warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return ModelStressAssessment(
            model_view_id=view.model_view_id,
            model_id=view.model_id,
            model_version=view.model_version,
            upstream_governance_assessment_id=governance_assessment.assessment_id,
            scenario_assessments=tuple(assessments),
            covered_classes=tuple(covered_classes),
            pass_ratio=pass_ratio,
            status=status,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            stress_qualified_for_cio_research=status is not ReadinessStatus.BLOCKED,
        )

    def evaluate(
        self,
        *,
        governance_packet: ModelGovernancePacket,
        views: tuple[QuantModelView, ...],
        results: tuple[ModelStressResult, ...],
        policy: ModelStressPolicy | None = None,
    ) -> ModelStressPacket:
        active_policy = policy or ModelStressPolicy()
        boundary = governance_packet.as_of
        unique_views: dict[str, QuantModelView] = {}
        for view in views:
            if view.security_id != governance_packet.security_id:
                raise ModelStressError("MODEL_STRESS_VIEW_SECURITY_MISMATCH")
            if view.as_of > boundary:
                raise ModelStressError("FUTURE_MODEL_VIEW_NOT_ALLOWED_BY_STRESS_ENGINE")
            unique_views.setdefault(view.model_view_id, view)
        governance_by_view = {
            item.model_view_id: item for item in governance_packet.assessments
        }
        assessments: list[ModelStressAssessment] = []
        for view in sorted(unique_views.values(), key=lambda item: item.model_view_id):
            governance_assessment = governance_by_view.get(view.model_view_id)
            if governance_assessment is None:
                raise ModelStressError("MODEL_STRESS_UPSTREAM_GOVERNANCE_ASSESSMENT_MISSING")
            assessments.append(
                self.assess_view(
                    view=view,
                    governance_assessment=governance_assessment,
                    results=results,
                    policy=active_policy,
                )
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
        qualified = tuple(
            sorted(
                item.model_view_id
                for item in assessments
                if item.stress_qualified_for_cio_research
            )
        )
        if blockers:
            status = ReadinessStatus.BLOCKED
        elif warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return ModelStressPacket(
            security_id=governance_packet.security_id,
            as_of=boundary,
            upstream_governance_packet_id=governance_packet.packet_id,
            scenario_registry_id=self.scenario_registry.registry_id,
            policy_id=active_policy.policy_id,
            assessments=tuple(assessments),
            stress_qualified_model_view_ids=qualified,
            status=status,
            blockers=blockers,
            warnings=warnings,
        )
