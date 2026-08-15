"""Reproducible quantitative research, model registry, and promotion controls."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
import json
from math import sqrt
import random
from statistics import fmean, stdev


class ExperimentStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PromotionStage(StrEnum):
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE_DISABLED = "LIVE_DISABLED"


@dataclass(frozen=True)
class ResearchThresholds:
    minimum_out_of_sample_trades: int
    minimum_sharpe: float
    minimum_profit_factor: float
    maximum_drawdown: float
    minimum_positive_parameter_share: float

    def __post_init__(self) -> None:
        if self.minimum_out_of_sample_trades <= 0:
            raise ValueError("minimum sample must be positive")
        if self.minimum_profit_factor <= 0 or self.maximum_drawdown <= 0:
            raise ValueError("risk thresholds must be positive")
        if not 0 <= self.minimum_positive_parameter_share <= 1:
            raise ValueError("parameter share must be between zero and one")


@dataclass(frozen=True)
class ExperimentManifest:
    experiment_id: str
    strategy_version: str
    code_version: str
    model_version: str
    feature_version: str
    data_version: str
    config_version: str
    universe_as_of: str
    train_range: tuple[str, str]
    validation_range: tuple[str, str]
    test_range: tuple[str, str]
    parameters: tuple[tuple[str, str], ...]
    thresholds: ResearchThresholds
    hypothesis: str
    multiple_testing_disclosure: str
    created_at: str

    def __post_init__(self) -> None:
        required = (
            self.experiment_id,
            self.strategy_version,
            self.code_version,
            self.model_version,
            self.feature_version,
            self.data_version,
            self.config_version,
            self.hypothesis,
            self.multiple_testing_disclosure,
            self.created_at,
        )
        if not all(required):
            raise ValueError("manifest identity, versions, and disclosures are required")
        universe_date = date.fromisoformat(self.universe_as_of)
        ranges = tuple(
            (date.fromisoformat(start), date.fromisoformat(end))
            for start, end in (self.train_range, self.validation_range, self.test_range)
        )
        if any(start > end for start, end in ranges):
            raise ValueError("partition start must not follow its end")
        if not ranges[0][1] < ranges[1][0] <= ranges[1][1] < ranges[2][0]:
            raise ValueError("research partitions overlap or are out of order")
        if universe_date > ranges[2][1]:
            raise ValueError("point-in-time universe cannot postdate the test period")

    @property
    def manifest_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class BacktestTrade:
    trade_id: str
    closed_on: str
    net_pnl: float
    capital_deployed: float
    benchmark_return: float
    factor_return: float
    turnover: float
    capacity: float
    mae: float
    mfe: float
    holding_days: float
    strategy: str
    regime: str
    sector: str
    score_band: str
    instrument: str
    out_of_sample: bool = True

    def __post_init__(self) -> None:
        date.fromisoformat(self.closed_on)
        if not self.trade_id or not all(
            (self.strategy, self.regime, self.sector, self.score_band)
        ):
            raise ValueError("trade identity and reporting dimensions are required")
        if self.instrument not in {"OPTION", "STOCK"}:
            raise ValueError("instrument must be OPTION or STOCK")
        if self.capital_deployed <= 0 or self.capacity < 0 or self.holding_days < 0:
            raise ValueError("capital, capacity, and holding period are invalid")

    @property
    def net_return(self) -> float:
        return self.net_pnl / self.capital_deployed


@dataclass(frozen=True)
class ResearchMetrics:
    trades: int
    total_return: float
    cagr: float
    volatility: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float
    hit_rate: float
    expectancy: float
    profit_factor: float | None
    turnover: float
    capacity: float
    average_mae: float
    average_mfe: float
    average_holding_days: float
    benchmark_return: float
    factor_return: float
    benchmark_alpha: float
    factor_alpha: float


@dataclass(frozen=True)
class ParameterStability:
    tested: int
    positive: int
    positive_share: float
    metric_range: float
    stable: bool


@dataclass(frozen=True)
class MonteCarloResult:
    simulations: int
    seed: int
    median_terminal_return: float
    drawdown_p95: float
    loss_probability: float


@dataclass(frozen=True)
class ExperimentRecord:
    manifest: ExperimentManifest
    status: ExperimentStatus
    metrics: ResearchMetrics | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == ExperimentStatus.COMPLETED and self.metrics is None:
            raise ValueError("completed experiment requires metrics")
        if self.status == ExperimentStatus.FAILED and not self.failure_reason:
            raise ValueError("failed experiment requires a retained failure reason")


@dataclass(frozen=True)
class ModelRegistryEntry:
    model_id: str
    strategy_version: str
    model_version: str
    feature_version: str
    data_version: str
    config_version: str
    experiment_id: str
    reviewed_by: str

    def __post_init__(self) -> None:
        if not all(asdict(self).values()):
            raise ValueError("model registry fields and named reviewer are required")


@dataclass(frozen=True)
class PromotionDecision:
    stage: PromotionStage
    approved: bool
    reasons: tuple[str, ...]


class ExperimentRegistry:
    """Append-only registry that retains successful and failed experiments."""

    def __init__(self) -> None:
        self._records: list[ExperimentRecord] = []

    @property
    def records(self) -> tuple[ExperimentRecord, ...]:
        return tuple(self._records)

    def add(self, record: ExperimentRecord) -> None:
        if any(
            item.manifest.experiment_id == record.manifest.experiment_id
            for item in self._records
        ):
            raise ValueError("experiment_id is immutable and must be unique")
        self._records.append(record)


def summarize_research(trades: Iterable[BacktestTrade]) -> ResearchMetrics:
    records = tuple(sorted(trades, key=lambda trade: (trade.closed_on, trade.trade_id)))
    returns = [trade.net_return for trade in records]
    gross_profit = sum(max(trade.net_pnl, 0.0) for trade in records)
    gross_loss = -sum(min(trade.net_pnl, 0.0) for trade in records)
    total_return = _compound(returns)
    years = _elapsed_years(records)
    cagr = (1 + total_return) ** (1 / years) - 1 if years and total_return > -1 else total_return
    volatility = stdev(returns) * sqrt(252) if len(returns) > 1 else 0.0
    mean_return = fmean(returns) if returns else 0.0
    downside = [min(value, 0.0) for value in returns]
    downside_deviation = sqrt(fmean(value * value for value in downside)) if downside else 0.0
    drawdown = _max_drawdown(returns)
    benchmark = _compound([trade.benchmark_return for trade in records])
    factor = _compound([trade.factor_return for trade in records])
    return ResearchMetrics(
        trades=len(records),
        total_return=total_return,
        cagr=cagr,
        volatility=volatility,
        sharpe=mean_return / (stdev(returns) or 1) * sqrt(252) if len(returns) > 1 else None,
        sortino=mean_return / downside_deviation * sqrt(252) if downside_deviation else None,
        calmar=cagr / drawdown if drawdown else None,
        max_drawdown=drawdown,
        hit_rate=sum(value > 0 for value in returns) / len(returns) if returns else 0.0,
        expectancy=mean_return,
        profit_factor=gross_profit / gross_loss if gross_loss else None,
        turnover=sum(trade.turnover for trade in records),
        capacity=min((trade.capacity for trade in records), default=0.0),
        average_mae=fmean(trade.mae for trade in records) if records else 0.0,
        average_mfe=fmean(trade.mfe for trade in records) if records else 0.0,
        average_holding_days=fmean(trade.holding_days for trade in records) if records else 0.0,
        benchmark_return=benchmark,
        factor_return=factor,
        benchmark_alpha=total_return - benchmark,
        factor_alpha=total_return - factor,
    )


def grouped_metrics(
    trades: Iterable[BacktestTrade], dimension: str
) -> Mapping[str, ResearchMetrics]:
    allowed = {"strategy", "regime", "sector", "score_band", "instrument"}
    if dimension not in allowed:
        raise ValueError(f"dimension must be one of {sorted(allowed)}")
    groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in trades:
        groups[str(getattr(trade, dimension))].append(trade)
    return {name: summarize_research(records) for name, records in sorted(groups.items())}


def assess_parameter_stability(
    scores: Iterable[float], *, minimum_positive_share: float, maximum_range: float
) -> ParameterStability:
    values = tuple(scores)
    if not values or not 0 <= minimum_positive_share <= 1 or maximum_range < 0:
        raise ValueError("valid parameter scores and predeclared thresholds are required")
    positive = sum(value > 0 for value in values)
    metric_range = max(values) - min(values)
    share = positive / len(values)
    return ParameterStability(
        tested=len(values),
        positive=positive,
        positive_share=share,
        metric_range=metric_range,
        stable=share >= minimum_positive_share and metric_range <= maximum_range,
    )


def monte_carlo_trade_sequences(
    returns: Iterable[float], *, simulations: int = 1000, seed: int = 0
) -> MonteCarloResult:
    values = tuple(returns)
    if not values or simulations <= 0:
        raise ValueError("returns and positive simulations are required")
    generator = random.Random(seed)
    terminals: list[float] = []
    drawdowns: list[float] = []
    for _ in range(simulations):
        sample = [generator.choice(values) for _ in values]
        terminals.append(_compound(sample))
        drawdowns.append(_max_drawdown(sample))
    terminals.sort()
    drawdowns.sort()
    return MonteCarloResult(
        simulations=simulations,
        seed=seed,
        median_terminal_return=_percentile(terminals, 0.50),
        drawdown_p95=_percentile(drawdowns, 0.95),
        loss_probability=sum(value < 0 for value in terminals) / simulations,
    )


def compare_challenger(
    *,
    champion: ResearchMetrics,
    challenger: ResearchMetrics,
    stability: ParameterStability,
    thresholds: ResearchThresholds,
) -> PromotionDecision:
    reasons: list[str] = []
    if challenger.trades < thresholds.minimum_out_of_sample_trades:
        reasons.append("INSUFFICIENT_OUT_OF_SAMPLE_TRADES")
    if challenger.sharpe is None or challenger.sharpe < thresholds.minimum_sharpe:
        reasons.append("SHARPE_BELOW_THRESHOLD")
    if (
        challenger.profit_factor is None
        or challenger.profit_factor < thresholds.minimum_profit_factor
    ):
        reasons.append("PROFIT_FACTOR_BELOW_THRESHOLD")
    if challenger.max_drawdown > thresholds.maximum_drawdown:
        reasons.append("DRAWDOWN_ABOVE_THRESHOLD")
    if not stability.stable:
        reasons.append("PARAMETER_INSTABILITY")
    if champion.sharpe is not None and (challenger.sharpe or float("-inf")) <= champion.sharpe:
        reasons.append("NO_RISK_ADJUSTED_IMPROVEMENT")
    return PromotionDecision(
        stage=PromotionStage.RESEARCH if reasons else PromotionStage.PAPER,
        approved=not reasons,
        reasons=tuple(reasons or ("PREDECLARED_RISK_ADJUSTED_GATES_PASSED",)),
    )


def request_live_promotion() -> PromotionDecision:
    return PromotionDecision(
        stage=PromotionStage.LIVE_DISABLED,
        approved=False,
        reasons=("LIVE_TRADING_DISABLED_BY_POLICY",),
    )


def require_version_bump_and_review(
    previous: ModelRegistryEntry, candidate: ModelRegistryEntry
) -> None:
    changed = any(
        getattr(previous, field) != getattr(candidate, field)
        for field in ("model_version", "feature_version", "data_version", "config_version")
    )
    if not changed:
        raise ValueError("model change requires a version bump")
    if not candidate.reviewed_by:
        raise ValueError("model change requires review")


def _compound(returns: Iterable[float]) -> float:
    equity = 1.0
    for value in returns:
        equity *= 1 + value
    return equity - 1


def _elapsed_years(records: tuple[BacktestTrade, ...]) -> float:
    if len(records) < 2:
        return 0.0
    days = (
        date.fromisoformat(records[-1].closed_on)
        - date.fromisoformat(records[0].closed_on)
    ).days
    return max(days / 365.25, 1 / 365.25)


def _max_drawdown(returns: Iterable[float]) -> float:
    equity = peak = 1.0
    maximum = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    return maximum


def _percentile(values: list[float], percentile: float) -> float:
    return values[min(round((len(values) - 1) * percentile), len(values) - 1)]
