"""Explainable ORATS volatility, flow, and capacity intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import OptionCandidate


class FlowClassification(StrEnum):
    NORMAL = "NORMAL"
    UNUSUAL_CONFIRMATION = "UNUSUAL_CONFIRMATION"
    UNUSUAL_CAUTION = "UNUSUAL_CAUTION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class OratsMetrics:
    candidate: OptionCandidate
    implied_volatility: float
    historical_volatility: float
    iv_percentile: float
    expected_move_pct: float
    skew: float
    term_slope: float
    average_contract_volume: float
    sweep_count: int = 0
    trade_count: int = 0
    multi_leg_pct: float | None = None
    opening_trade_pct: float | None = None

    def __post_init__(self) -> None:
        if min(
            self.implied_volatility,
            self.historical_volatility,
            self.expected_move_pct,
            self.average_contract_volume,
        ) < 0:
            raise ValueError("ORATS volatility and volume metrics cannot be negative")
        if not 0 <= self.iv_percentile <= 100:
            raise ValueError("iv_percentile must be between 0 and 100")
        for name, value in (
            ("multi_leg_pct", self.multi_leg_pct),
            ("opening_trade_pct", self.opening_trade_pct),
        ):
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.sweep_count < 0 or self.trade_count < 0:
            raise ValueError("flow counts cannot be negative")

    @property
    def iv_rv_spread(self) -> float:
        return self.implied_volatility - self.historical_volatility

    @property
    def relative_volume(self) -> float | None:
        if self.average_contract_volume <= 0:
            return None
        return self.candidate.volume / self.average_contract_volume


@dataclass(frozen=True)
class IntelligencePolicy:
    unusual_relative_volume: float = 2.0
    minimum_volume_oi: float = 0.5
    minimum_sweep_share: float = 0.1
    maximum_volume_participation: float = 0.05
    maximum_oi_participation: float = 0.02


@dataclass(frozen=True)
class OratsIntelligence:
    classification: FlowClassification
    reasons: tuple[str, ...]
    iv_rv_spread: float
    relative_volume: float | None
    volume_to_open_interest: float
    expected_move_pct: float
    iv_percentile: float
    skew: float
    term_slope: float
    capacity_contracts: int
    standalone_trade_signal: bool = False


class OratsIntelligenceEngine:
    """Produce confirmation intelligence; never emit a standalone entry signal."""

    def __init__(self, policy: IntelligencePolicy | None = None) -> None:
        self.policy = policy or IntelligencePolicy()

    def analyze(self, metrics: OratsMetrics) -> OratsIntelligence:
        candidate = metrics.candidate
        relative_volume = metrics.relative_volume
        reasons: list[str] = []
        if relative_volume is None:
            classification = FlowClassification.INSUFFICIENT_DATA
            reasons.append("AVERAGE_VOLUME_UNAVAILABLE")
        else:
            unusual_volume = relative_volume >= self.policy.unusual_relative_volume
            unusual_oi = candidate.volume_to_open_interest >= self.policy.minimum_volume_oi
            sweep_share = (
                metrics.sweep_count / metrics.trade_count if metrics.trade_count > 0 else 0.0
            )
            unusual_sweeps = sweep_share >= self.policy.minimum_sweep_share
            if unusual_volume:
                reasons.append("RELATIVE_VOLUME_ELEVATED")
            if unusual_oi:
                reasons.append("VOLUME_TO_OI_ELEVATED")
            if unusual_sweeps:
                reasons.append("SWEEP_SHARE_ELEVATED")
            if unusual_volume and (unusual_oi or unusual_sweeps):
                classification = FlowClassification.UNUSUAL_CONFIRMATION
            elif unusual_volume or unusual_oi or unusual_sweeps:
                classification = FlowClassification.UNUSUAL_CAUTION
            else:
                classification = FlowClassification.NORMAL
                reasons.append("FLOW_WITHIN_NORMAL_RANGE")

        volume_capacity = int(candidate.volume * self.policy.maximum_volume_participation)
        oi_capacity = int(candidate.open_interest * self.policy.maximum_oi_participation)
        capacity = max(0, min(volume_capacity, oi_capacity))
        return OratsIntelligence(
            classification=classification,
            reasons=tuple(reasons),
            iv_rv_spread=metrics.iv_rv_spread,
            relative_volume=relative_volume,
            volume_to_open_interest=candidate.volume_to_open_interest,
            expected_move_pct=metrics.expected_move_pct,
            iv_percentile=metrics.iv_percentile,
            skew=metrics.skew,
            term_slope=metrics.term_slope,
            capacity_contracts=capacity,
            standalone_trade_signal=False,
        )
