"""Point-in-time model outcome attribution and alpha-decay surveillance.

This layer consumes immutable realized research outcomes without mutating PAPER or live
ledgers. It can restrict which Stage 9H stress-qualified model views remain eligible for
CIO/Fusion research, but it never authorizes portfolio construction, execution, capital,
broker routing, or live trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .cio_fusion import QuantModelView
from .contracts import ReadinessStatus
from .model_governance import ModelGovernancePacket, ModelValidationRecord
from .model_stress import ModelStressPacket


class ModelPerformanceError(ValueError):
    """Model performance attribution or surveillance lineage violates the contract."""


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelPerformanceError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
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
        raise ModelPerformanceError("MODEL_PERFORMANCE_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise ModelPerformanceError(f"{field_name}_MUST_BE_FINITE")
    return value


@dataclass(frozen=True)
class ModelOutcomeRecord:
    """Immutable realized research outcome attributed to the exact historical model view."""

    security_id: str
    model_view_id: str
    model_id: str
    model_version: str
    known_at: datetime
    measurement_start: datetime
    measurement_end: datetime
    realized_r: float
    realized_return: float
    fees_bps: float
    input_lineage_ids: tuple[str, ...]
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
    portfolio_construction_authorized: bool = False
    execution_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security = self.security_id.strip().upper()
        view_id = self.model_view_id.strip().lower()
        model_id = self.model_id.strip().upper()
        version = self.model_version.strip()
        if not all((security, view_id, model_id, version)):
            raise ModelPerformanceError("MODEL_OUTCOME_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelPerformanceError("MODEL_OUTCOME_MUST_REMAIN_RESEARCH_ONLY")
        known = _aware_utc(self.known_at, "MODEL_OUTCOME_KNOWN_AT")
        start = _aware_utc(self.measurement_start, "MODEL_OUTCOME_MEASUREMENT_START")
        end = _aware_utc(self.measurement_end, "MODEL_OUTCOME_MEASUREMENT_END")
        if start >= end:
            raise ModelPerformanceError("MODEL_OUTCOME_MEASUREMENT_WINDOW_INVALID")
        if end > known:
            raise ModelPerformanceError("MODEL_OUTCOME_MEASUREMENT_END_AFTER_KNOWN_AT")
        for field_name in ("realized_r", "realized_return", "fees_bps"):
            _finite(getattr(self, field_name), f"MODEL_OUTCOME_{field_name.upper()}")
        if self.fees_bps < 0:
            raise ModelPerformanceError("MODEL_OUTCOME_FEES_BPS_NEGATIVE")
        lineage = tuple(sorted({item.strip().lower() for item in self.input_lineage_ids if item.strip()}))
        if not lineage:
            raise ModelPerformanceError("MODEL_OUTCOME_INPUT_LINEAGE_REQUIRED")
        object.__setattr__(self, "security_id", security)
        object.__setattr__(self, "model_view_id", view_id)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_version", version)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "measurement_start", start)
        object.__setattr__(self, "measurement_end", end)
        object.__setattr__(self, "input_lineage_ids", lineage)

    @property
    def model_key(self) -> tuple[str, str]:
        return self.model_id, self.model_version

    @property
    def outcome_id(self) -> str:
        return _digest(
            {
                "security_id": self.security_id,
                "model_view_id": self.model_view_id,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "known_at": self.known_at.isoformat(),
                "measurement_start": self.measurement_start.isoformat(),
                "measurement_end": self.measurement_end.isoformat(),
                "realized_r": self.realized_r,
                "realized_return": self.realized_return,
                "fees_bps": self.fees_bps,
                "input_lineage_ids": list(self.input_lineage_ids),
                "research_only": self.research_only,
                "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class ModelPerformancePolicy:
    lookback_days: int = 90
    min_outcomes: int = 30
    min_hit_rate: float = 0.40
    min_expectancy_r: float = 0.0
    min_profit_factor: float = 1.0
    max_drawdown_r: float = 6.0
    max_loss_streak: int = 8
    max_expectancy_decay_fraction: float = 0.75

    def __post_init__(self) -> None:
        if self.lookback_days <= 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_LOOKBACK_DAYS_MUST_BE_POSITIVE")
        if self.min_outcomes <= 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_MIN_OUTCOMES_MUST_BE_POSITIVE")
        if self.max_loss_streak < 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_MAX_LOSS_STREAK_NEGATIVE")
        for field_name in (
            "min_hit_rate",
            "min_expectancy_r",
            "min_profit_factor",
            "max_drawdown_r",
            "max_expectancy_decay_fraction",
        ):
            _finite(getattr(self, field_name), f"MODEL_PERFORMANCE_POLICY_{field_name.upper()}")
        if not 0.0 <= self.min_hit_rate <= 1.0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_MIN_HIT_RATE_OUT_OF_RANGE")
        if self.min_profit_factor < 0 or self.max_drawdown_r < 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_POLICY_NONNEGATIVE_VALUE_REQUIRED")
        if self.max_expectancy_decay_fraction < 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_DECAY_FRACTION_NEGATIVE")

    @property
    def policy_id(self) -> str:
        return _digest(self.__dict__)


@dataclass(frozen=True)
class ModelPerformanceMetrics:
    sample_size: int
    wins: int
    losses: int
    breakeven: int
    hit_rate: float
    expectancy_r: float
    profit_factor: float | None
    cumulative_r: float
    max_drawdown_r: float
    max_loss_streak: int
    baseline_expectancy_r: float
    expectancy_decay_fraction: float | None
    outcome_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if min(self.sample_size, self.wins, self.losses, self.breakeven, self.max_loss_streak) < 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_METRIC_COUNT_NEGATIVE")
        if self.wins + self.losses + self.breakeven != self.sample_size:
            raise ModelPerformanceError("MODEL_PERFORMANCE_METRIC_COUNT_MISMATCH")
        for field_name in (
            "hit_rate",
            "expectancy_r",
            "cumulative_r",
            "max_drawdown_r",
            "baseline_expectancy_r",
        ):
            _finite(getattr(self, field_name), f"MODEL_PERFORMANCE_{field_name.upper()}")
        if not 0.0 <= self.hit_rate <= 1.0 or self.max_drawdown_r < 0:
            raise ModelPerformanceError("MODEL_PERFORMANCE_METRIC_OUT_OF_RANGE")
        if self.profit_factor is not None:
            _finite(self.profit_factor, "MODEL_PERFORMANCE_PROFIT_FACTOR")
            if self.profit_factor < 0:
                raise ModelPerformanceError("MODEL_PERFORMANCE_PROFIT_FACTOR_NEGATIVE")
        if self.expectancy_decay_fraction is not None:
            _finite(
                self.expectancy_decay_fraction,
                "MODEL_PERFORMANCE_EXPECTANCY_DECAY_FRACTION",
            )
            if self.expectancy_decay_fraction < 0:
                raise ModelPerformanceError("MODEL_PERFORMANCE_EXPECTANCY_DECAY_NEGATIVE")
        outcomes = tuple(sorted(set(self.outcome_ids)))
        if len(outcomes) != self.sample_size:
            raise ModelPerformanceError("MODEL_PERFORMANCE_OUTCOME_ID_COUNT_MISMATCH")
        object.__setattr__(self, "outcome_ids", outcomes)

    @property
    def metrics_id(self) -> str:
        return _digest(
            {
                "sample_size": self.sample_size,
                "wins": self.wins,
                "losses": self.losses,
                "breakeven": self.breakeven,
                "hit_rate": self.hit_rate,
                "expectancy_r": self.expectancy_r,
                "profit_factor": self.profit_factor,
                "cumulative_r": self.cumulative_r,
                "max_drawdown_r": self.max_drawdown_r,
                "max_loss_streak": self.max_loss_streak,
                "baseline_expectancy_r": self.baseline_expectancy_r,
                "expectancy_decay_fraction": self.expectancy_decay_fraction,
                "outcome_ids": list(self.outcome_ids),
            }
        )


@dataclass(frozen=True)
class ModelPerformanceAssessment:
    model_view_id: str
    model_id: str
    model_version: str
    upstream_governance_assessment_id: str
    upstream_stress_assessment_id: str
    baseline_validation_id: str
    metrics: ModelPerformanceMetrics
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    performance_eligible_for_cio_research: bool
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
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
                self.upstream_stress_assessment_id.strip(),
                self.baseline_validation_id.strip(),
            )
        ):
            raise ModelPerformanceError("MODEL_PERFORMANCE_ASSESSMENT_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelPerformanceError("MODEL_PERFORMANCE_ASSESSMENT_MUST_REMAIN_RESEARCH_ONLY")
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.performance_eligible_for_cio_research and self.status is ReadinessStatus.BLOCKED:
            raise ModelPerformanceError("BLOCKED_MODEL_CANNOT_BE_PERFORMANCE_ELIGIBLE")
        if not self.performance_eligible_for_cio_research and self.status is not ReadinessStatus.BLOCKED:
            raise ModelPerformanceError("INELIGIBLE_MODEL_PERFORMANCE_MUST_BE_BLOCKED")
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ModelPerformanceError("PASS_MODEL_PERFORMANCE_ASSESSMENT_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ModelPerformanceError("WARNING_MODEL_PERFORMANCE_ASSESSMENT_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "model_view_id", self.model_view_id.lower())
        object.__setattr__(self, "model_id", self.model_id.upper())
        object.__setattr__(self, "upstream_governance_assessment_id", self.upstream_governance_assessment_id.lower())
        object.__setattr__(self, "upstream_stress_assessment_id", self.upstream_stress_assessment_id.lower())
        object.__setattr__(self, "baseline_validation_id", self.baseline_validation_id.lower())
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
                "upstream_stress_assessment_id": self.upstream_stress_assessment_id,
                "baseline_validation_id": self.baseline_validation_id,
                "metrics_id": self.metrics.metrics_id,
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "performance_eligible_for_cio_research": self.performance_eligible_for_cio_research,
                "research_only": self.research_only,
                "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )


@dataclass(frozen=True)
class ModelPerformancePacket:
    security_id: str
    as_of: datetime
    upstream_governance_packet_id: str
    upstream_stress_packet_id: str
    policy_id: str
    assessments: tuple[ModelPerformanceAssessment, ...]
    performance_eligible_model_view_ids: tuple[str, ...]
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    paper_ledger_mutation_authorized: bool = False
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
                self.upstream_stress_packet_id.strip(),
                self.policy_id.strip(),
            )
        ):
            raise ModelPerformanceError("MODEL_PERFORMANCE_PACKET_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.paper_ledger_mutation_authorized
            or self.portfolio_construction_authorized
            or self.execution_authorized
            or self.trading_authorized
            or self.live_trading_enabled
        ):
            raise ModelPerformanceError("MODEL_PERFORMANCE_PACKET_MUST_REMAIN_RESEARCH_ONLY")
        assessments = tuple(sorted(self.assessments, key=lambda item: item.assessment_id))
        eligible = tuple(sorted(set(self.performance_eligible_model_view_ids)))
        expected = tuple(
            sorted(
                item.model_view_id
                for item in assessments
                if item.performance_eligible_for_cio_research
            )
        )
        if eligible != expected:
            raise ModelPerformanceError("MODEL_PERFORMANCE_ELIGIBLE_SET_MISMATCH")
        blockers = tuple(sorted(set(self.blockers)))
        warnings = tuple(sorted(set(self.warnings)))
        if self.status is ReadinessStatus.PASS and (blockers or warnings):
            raise ModelPerformanceError("PASS_MODEL_PERFORMANCE_PACKET_CANNOT_HAVE_ISSUES")
        if self.status is ReadinessStatus.WARNING and blockers:
            raise ModelPerformanceError("WARNING_MODEL_PERFORMANCE_PACKET_CANNOT_HAVE_BLOCKERS")
        object.__setattr__(self, "security_id", security)
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "MODEL_PERFORMANCE_PACKET_AS_OF"))
        object.__setattr__(self, "upstream_governance_packet_id", self.upstream_governance_packet_id.lower())
        object.__setattr__(self, "upstream_stress_packet_id", self.upstream_stress_packet_id.lower())
        object.__setattr__(self, "policy_id", self.policy_id.lower())
        object.__setattr__(self, "assessments", assessments)
        object.__setattr__(self, "performance_eligible_model_view_ids", eligible)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def packet_id(self) -> str:
        return _digest(
            {
                "security_id": self.security_id,
                "as_of": self.as_of.isoformat(),
                "upstream_governance_packet_id": self.upstream_governance_packet_id,
                "upstream_stress_packet_id": self.upstream_stress_packet_id,
                "policy_id": self.policy_id,
                "assessment_ids": [item.assessment_id for item in self.assessments],
                "performance_eligible_model_view_ids": list(
                    self.performance_eligible_model_view_ids
                ),
                "status": self.status.value,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
                "research_only": self.research_only,
                "paper_ledger_mutation_authorized": self.paper_ledger_mutation_authorized,
                "portfolio_construction_authorized": self.portfolio_construction_authorized,
                "execution_authorized": self.execution_authorized,
                "trading_authorized": self.trading_authorized,
                "live_trading_enabled": self.live_trading_enabled,
            }
        )

    def assert_views_performance_eligible(self, views: tuple[QuantModelView, ...]) -> None:
        for view in views:
            if view.security_id != self.security_id:
                raise ModelPerformanceError("MODEL_PERFORMANCE_PACKET_SECURITY_MISMATCH")
            if view.as_of > self.as_of:
                raise ModelPerformanceError(
                    "FUTURE_MODEL_VIEW_NOT_ALLOWED_BY_PERFORMANCE_PACKET"
                )
            if view.model_view_id not in self.performance_eligible_model_view_ids:
                raise ModelPerformanceError(
                    f"MODEL_VIEW_NOT_PERFORMANCE_ELIGIBLE:{view.model_id}:{view.model_version}"
                )


class ModelPerformanceEngine:
    """Attribute realized outcomes and detect rolling model decay without lookahead."""

    @staticmethod
    def _select_outcomes(
        *,
        view: QuantModelView,
        outcomes: tuple[ModelOutcomeRecord, ...],
        as_of: datetime,
        policy: ModelPerformancePolicy,
    ) -> tuple[ModelOutcomeRecord, ...]:
        lower = as_of - timedelta(days=policy.lookback_days)
        selected: dict[str, ModelOutcomeRecord] = {}
        for outcome in outcomes:
            if outcome.model_key != (view.model_id, view.model_version):
                continue
            if outcome.known_at > as_of or outcome.measurement_end > as_of:
                continue
            if outcome.measurement_end < lower:
                continue
            selected.setdefault(outcome.outcome_id, outcome)
        return tuple(
            sorted(
                selected.values(),
                key=lambda item: (item.measurement_end, item.known_at, item.outcome_id),
            )
        )

    @staticmethod
    def _metrics(
        *,
        outcomes: tuple[ModelOutcomeRecord, ...],
        baseline: ModelValidationRecord,
    ) -> ModelPerformanceMetrics:
        rs = [item.realized_r for item in outcomes]
        wins = sum(value > 0 for value in rs)
        losses = sum(value < 0 for value in rs)
        breakeven = len(rs) - wins - losses
        hit_rate = wins / len(rs) if rs else 0.0
        expectancy = sum(rs) / len(rs) if rs else 0.0
        gross_profit = sum(value for value in rs if value > 0)
        gross_loss = -sum(value for value in rs if value < 0)
        if gross_loss > 0:
            profit_factor: float | None = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = None
        else:
            profit_factor = 0.0

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        loss_streak = 0
        max_loss_streak = 0
        for value in rs:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            if value < 0:
                loss_streak += 1
                max_loss_streak = max(max_loss_streak, loss_streak)
            else:
                loss_streak = 0

        decay: float | None = None
        if baseline.expectancy_r > 0:
            decay = max(0.0, 1.0 - expectancy / baseline.expectancy_r)
        return ModelPerformanceMetrics(
            sample_size=len(outcomes),
            wins=wins,
            losses=losses,
            breakeven=breakeven,
            hit_rate=hit_rate,
            expectancy_r=expectancy,
            profit_factor=profit_factor,
            cumulative_r=sum(rs),
            max_drawdown_r=max_drawdown,
            max_loss_streak=max_loss_streak,
            baseline_expectancy_r=baseline.expectancy_r,
            expectancy_decay_fraction=decay,
            outcome_ids=tuple(item.outcome_id for item in outcomes),
        )

    @staticmethod
    def _performance_blockers(
        metrics: ModelPerformanceMetrics,
        policy: ModelPerformancePolicy,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if metrics.hit_rate < policy.min_hit_rate:
            blockers.append(
                f"MODEL_HIT_RATE_BELOW_POLICY:{metrics.hit_rate:.6f}<"
                f"{policy.min_hit_rate:.6f}"
            )
        if metrics.expectancy_r < policy.min_expectancy_r:
            blockers.append(
                f"MODEL_EXPECTANCY_BELOW_POLICY:{metrics.expectancy_r:.6f}<"
                f"{policy.min_expectancy_r:.6f}"
            )
        if metrics.profit_factor is not None and metrics.profit_factor < policy.min_profit_factor:
            blockers.append(
                f"MODEL_PROFIT_FACTOR_BELOW_POLICY:{metrics.profit_factor:.6f}<"
                f"{policy.min_profit_factor:.6f}"
            )
        if metrics.max_drawdown_r > policy.max_drawdown_r:
            blockers.append(
                f"MODEL_DRAWDOWN_R_ABOVE_POLICY:{metrics.max_drawdown_r:.6f}>"
                f"{policy.max_drawdown_r:.6f}"
            )
        if metrics.max_loss_streak > policy.max_loss_streak:
            blockers.append(
                f"MODEL_LOSS_STREAK_ABOVE_POLICY:{metrics.max_loss_streak}>"
                f"{policy.max_loss_streak}"
            )
        if (
            metrics.expectancy_decay_fraction is not None
            and metrics.expectancy_decay_fraction > policy.max_expectancy_decay_fraction
        ):
            blockers.append(
                f"MODEL_EXPECTANCY_DECAY_ABOVE_POLICY:"
                f"{metrics.expectancy_decay_fraction:.6f}>"
                f"{policy.max_expectancy_decay_fraction:.6f}"
            )
        return tuple(sorted(blockers))

    def evaluate(
        self,
        *,
        governance_packet: ModelGovernancePacket,
        stress_packet: ModelStressPacket,
        views: tuple[QuantModelView, ...],
        validations: tuple[ModelValidationRecord, ...],
        outcomes: tuple[ModelOutcomeRecord, ...],
        policy: ModelPerformancePolicy | None = None,
    ) -> ModelPerformancePacket:
        active_policy = policy or ModelPerformancePolicy()
        boundary = governance_packet.as_of
        if stress_packet.security_id != governance_packet.security_id:
            raise ModelPerformanceError("MODEL_PERFORMANCE_UPSTREAM_SECURITY_MISMATCH")
        if stress_packet.as_of != boundary:
            raise ModelPerformanceError("MODEL_PERFORMANCE_UPSTREAM_AS_OF_MISMATCH")
        if stress_packet.upstream_governance_packet_id != governance_packet.packet_id:
            raise ModelPerformanceError("MODEL_PERFORMANCE_UPSTREAM_PACKET_LINEAGE_MISMATCH")

        governance_by_view = {
            item.model_view_id: item for item in governance_packet.assessments
        }
        stress_by_view = {item.model_view_id: item for item in stress_packet.assessments}
        validations_by_id = {item.validation_id: item for item in validations if item.as_of <= boundary}
        unique_views: dict[str, QuantModelView] = {}
        for view in views:
            if view.security_id != governance_packet.security_id:
                raise ModelPerformanceError("MODEL_PERFORMANCE_VIEW_SECURITY_MISMATCH")
            if view.as_of > boundary:
                raise ModelPerformanceError("FUTURE_MODEL_VIEW_NOT_ALLOWED_BY_PERFORMANCE_ENGINE")
            unique_views.setdefault(view.model_view_id, view)

        assessments: list[ModelPerformanceAssessment] = []
        for view in sorted(unique_views.values(), key=lambda item: item.model_view_id):
            governance = governance_by_view.get(view.model_view_id)
            stress = stress_by_view.get(view.model_view_id)
            if governance is None or stress is None:
                raise ModelPerformanceError("MODEL_PERFORMANCE_UPSTREAM_ASSESSMENT_MISSING")
            if governance.validation_id is None:
                raise ModelPerformanceError("MODEL_PERFORMANCE_BASELINE_VALIDATION_ID_MISSING")
            baseline = validations_by_id.get(governance.validation_id)
            if baseline is None:
                raise ModelPerformanceError("MODEL_PERFORMANCE_BASELINE_VALIDATION_NOT_AVAILABLE")
            if baseline.model_key != (view.model_id, view.model_version):
                raise ModelPerformanceError("MODEL_PERFORMANCE_BASELINE_MODEL_MISMATCH")

            selected = self._select_outcomes(
                view=view,
                outcomes=outcomes,
                as_of=boundary,
                policy=active_policy,
            )
            metrics = self._metrics(outcomes=selected, baseline=baseline)
            blockers: list[str] = []
            warnings: list[str] = []
            if not governance.eligible_for_cio_research:
                blockers.append("UPSTREAM_MODEL_GOVERNANCE_BLOCKED")
            elif governance.status is ReadinessStatus.WARNING:
                warnings.append("UPSTREAM_MODEL_GOVERNANCE_WARNING")
            if not stress.stress_qualified_for_cio_research:
                blockers.append("UPSTREAM_MODEL_STRESS_BLOCKED")
            elif stress.status is ReadinessStatus.WARNING:
                warnings.append("UPSTREAM_MODEL_STRESS_WARNING")

            if metrics.sample_size < active_policy.min_outcomes:
                warnings.append(
                    f"MODEL_PERFORMANCE_HISTORY_INSUFFICIENT:{metrics.sample_size}<"
                    f"{active_policy.min_outcomes}"
                )
            else:
                blockers.extend(self._performance_blockers(metrics, active_policy))

            if blockers:
                status = ReadinessStatus.BLOCKED
            elif warnings:
                status = ReadinessStatus.WARNING
            else:
                status = ReadinessStatus.PASS
            assessments.append(
                ModelPerformanceAssessment(
                    model_view_id=view.model_view_id,
                    model_id=view.model_id,
                    model_version=view.model_version,
                    upstream_governance_assessment_id=governance.assessment_id,
                    upstream_stress_assessment_id=stress.assessment_id,
                    baseline_validation_id=baseline.validation_id,
                    metrics=metrics,
                    status=status,
                    blockers=tuple(blockers),
                    warnings=tuple(warnings),
                    performance_eligible_for_cio_research=status is not ReadinessStatus.BLOCKED,
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
        eligible = tuple(
            sorted(
                item.model_view_id
                for item in assessments
                if item.performance_eligible_for_cio_research
            )
        )
        if blockers:
            status = ReadinessStatus.BLOCKED
        elif warnings:
            status = ReadinessStatus.WARNING
        else:
            status = ReadinessStatus.PASS
        return ModelPerformancePacket(
            security_id=governance_packet.security_id,
            as_of=boundary,
            upstream_governance_packet_id=governance_packet.packet_id,
            upstream_stress_packet_id=stress_packet.packet_id,
            policy_id=active_policy.policy_id,
            assessments=tuple(assessments),
            performance_eligible_model_view_ids=eligible,
            status=status,
            blockers=blockers,
            warnings=warnings,
        )
