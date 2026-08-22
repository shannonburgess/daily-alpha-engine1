"""Forward PAPER model-validation performance analytics for SH24 and SH25.

This module is observability/research only.  A PAPER model-validation fill is an
internal accounting observation anchored to the confirmed signal price; it is never
represented as a brokerage fill.  The stock-primary contract is hard-coded here so
this analytics layer cannot re-introduce option execution or authorize trading.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from statistics import fmean
from typing import Iterable

PAPER_SHADOW_ACCOUNTS = ("PAPER_SHADOW_V24", "PAPER_SHADOW_V25")
MODEL_VALIDATION_FILL_BASIS = "CONFIRMED_SIGNAL_PRICE_MODEL_VALIDATION"
MIN_DESCRIPTIVE_SAMPLE = 30


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _normalized_label(value: str, fallback: str) -> str:
    normalized = value.strip().upper()
    return normalized or fallback


@dataclass(frozen=True)
class ForwardTradeObservation:
    """One closed stock PAPER model-validation trade.

    `initial_risk_per_share` and path extrema are optional because older evidence may
    not contain them.  Missing risk/MFE/MAE is never backfilled or converted to zero;
    coverage is reported explicitly in the summary.
    """

    trade_id: str
    account_id: str
    symbol: str
    entry_at: datetime
    exit_at: datetime
    entry_price: float
    exit_price: float
    shares: float
    initial_risk_per_share: float | None = None
    max_price_after_entry: float | None = None
    min_price_after_entry: float | None = None
    setup_type: str = "UNSPECIFIED"
    lifecycle_stage: str = "UNSPECIFIED"
    sector: str = "UNKNOWN"
    industry: str = "UNKNOWN"
    exit_reason: str = "UNSPECIFIED"
    instrument: str = "STOCK"
    fill_basis: str = MODEL_VALIDATION_FILL_BASIS
    brokerage_fill: bool = False
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.trade_id.strip():
            raise ValueError("TRADE_ID_REQUIRED")
        if self.account_id not in PAPER_SHADOW_ACCOUNTS:
            raise ValueError("UNKNOWN_PAPER_SHADOW_ACCOUNT")
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("SYMBOL_REQUIRED")
        entry_at = _aware_utc(self.entry_at, "ENTRY_AT")
        exit_at = _aware_utc(self.exit_at, "EXIT_AT")
        if exit_at < entry_at:
            raise ValueError("EXIT_PRECEDES_ENTRY")
        if self.entry_price <= 0 or self.exit_price <= 0 or self.shares <= 0:
            raise ValueError("TRADE_PRICES_AND_SHARES_MUST_BE_POSITIVE")
        if self.initial_risk_per_share is not None and self.initial_risk_per_share <= 0:
            raise ValueError("INITIAL_RISK_PER_SHARE_MUST_BE_POSITIVE")
        if self.max_price_after_entry is not None and self.max_price_after_entry <= 0:
            raise ValueError("MAX_PRICE_AFTER_ENTRY_MUST_BE_POSITIVE")
        if self.min_price_after_entry is not None and self.min_price_after_entry <= 0:
            raise ValueError("MIN_PRICE_AFTER_ENTRY_MUST_BE_POSITIVE")
        if (
            self.max_price_after_entry is not None
            and self.min_price_after_entry is not None
            and self.max_price_after_entry < self.min_price_after_entry
        ):
            raise ValueError("PATH_EXTREMA_INVALID")
        if self.instrument != "STOCK":
            raise ValueError("NEW_MODEL_VALIDATION_TRADES_MUST_BE_STOCK")
        if self.fill_basis != MODEL_VALIDATION_FILL_BASIS:
            raise ValueError("MODEL_VALIDATION_FILL_BASIS_REQUIRED")
        if self.brokerage_fill:
            raise ValueError("MODEL_VALIDATION_FILL_MUST_NOT_BE_BROKERAGE_FILL")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ValueError("MODEL_PERFORMANCE_MUST_REMAIN_RESEARCH_ONLY")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "entry_at", entry_at)
        object.__setattr__(self, "exit_at", exit_at)
        object.__setattr__(self, "setup_type", _normalized_label(self.setup_type, "UNSPECIFIED"))
        object.__setattr__(
            self,
            "lifecycle_stage",
            _normalized_label(self.lifecycle_stage, "UNSPECIFIED"),
        )
        object.__setattr__(self, "sector", _normalized_label(self.sector, "UNKNOWN"))
        object.__setattr__(self, "industry", _normalized_label(self.industry, "UNKNOWN"))
        object.__setattr__(self, "exit_reason", _normalized_label(self.exit_reason, "UNSPECIFIED"))

    @property
    def model_pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def r_multiple(self) -> float | None:
        if self.initial_risk_per_share is None:
            return None
        return (self.exit_price - self.entry_price) / self.initial_risk_per_share

    @property
    def mfe_r(self) -> float | None:
        if self.initial_risk_per_share is None or self.max_price_after_entry is None:
            return None
        return max(0.0, (self.max_price_after_entry - self.entry_price) / self.initial_risk_per_share)

    @property
    def mae_r(self) -> float | None:
        if self.initial_risk_per_share is None or self.min_price_after_entry is None:
            return None
        return min(0.0, (self.min_price_after_entry - self.entry_price) / self.initial_risk_per_share)

    @property
    def holding_minutes(self) -> float:
        return (self.exit_at - self.entry_at).total_seconds() / 60.0


@dataclass(frozen=True)
class NoTradeObservation:
    """One genuine strategy event that did not become a PAPER model-validation fill."""

    event_id: str
    account_id: str
    symbol: str
    observed_at: datetime
    reason: str
    setup_type: str = "UNSPECIFIED"
    lifecycle_stage: str = "UNSPECIFIED"
    sector: str = "UNKNOWN"
    industry: str = "UNKNOWN"
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("EVENT_ID_REQUIRED")
        if self.account_id not in PAPER_SHADOW_ACCOUNTS:
            raise ValueError("UNKNOWN_PAPER_SHADOW_ACCOUNT")
        symbol = self.symbol.strip().upper()
        reason = self.reason.strip().upper()
        if not symbol or not reason:
            raise ValueError("NO_TRADE_SYMBOL_AND_REASON_REQUIRED")
        observed_at = _aware_utc(self.observed_at, "OBSERVED_AT")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ValueError("MODEL_PERFORMANCE_MUST_REMAIN_RESEARCH_ONLY")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "setup_type", _normalized_label(self.setup_type, "UNSPECIFIED"))
        object.__setattr__(
            self,
            "lifecycle_stage",
            _normalized_label(self.lifecycle_stage, "UNSPECIFIED"),
        )
        object.__setattr__(self, "sector", _normalized_label(self.sector, "UNKNOWN"))
        object.__setattr__(self, "industry", _normalized_label(self.industry, "UNKNOWN"))


@dataclass(frozen=True)
class SliceSummary:
    n: int
    wins: int
    losses: int
    win_rate: float | None
    model_pnl: float
    r_observations: int
    r_coverage: float
    cumulative_r: float | None
    expectancy_r: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ModelPerformanceSummary:
    account_id: str
    n: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float | None
    cumulative_model_pnl: float
    average_winner_pnl: float | None
    average_loser_pnl: float | None
    profit_factor: float | None
    max_drawdown_pnl: float
    r_observations: int
    r_coverage: float
    cumulative_r: float | None
    expectancy_r: float | None
    average_winner_r: float | None
    average_loser_r: float | None
    max_drawdown_r: float | None
    mfe_observations: int
    mae_observations: int
    average_mfe_r: float | None
    average_mae_r: float | None
    average_holding_minutes: float | None
    rejection_count: int
    rejection_reasons: dict[str, int]
    by_setup_type: dict[str, SliceSummary]
    by_lifecycle_stage: dict[str, SliceSummary]
    by_sector: dict[str, SliceSummary]
    by_industry: dict[str, SliceSummary]
    evidence_status: str
    stock_primary: bool = True
    model_validation_only: bool = True
    promotion_authorized: bool = False
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("by_setup_type", "by_lifecycle_stage", "by_sector", "by_industry"):
            payload[key] = {name: summary.to_dict() for name, summary in getattr(self, key).items()}
        return payload


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _max_drawdown(values: list[float]) -> float:
    equity = peak = max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def _slice_summary(records: list[ForwardTradeObservation]) -> SliceSummary:
    pnl = [item.model_pnl for item in records]
    r_values = [value for item in records if (value := item.r_multiple) is not None]
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    n = len(records)
    return SliceSummary(
        n=n,
        wins=wins,
        losses=losses,
        win_rate=wins / n if n else None,
        model_pnl=sum(pnl),
        r_observations=len(r_values),
        r_coverage=len(r_values) / n if n else 0.0,
        cumulative_r=sum(r_values) if r_values else None,
        expectancy_r=_mean(r_values),
    )


def _slice(records: list[ForwardTradeObservation], field_name: str) -> dict[str, SliceSummary]:
    grouped: dict[str, list[ForwardTradeObservation]] = defaultdict(list)
    for item in records:
        grouped[str(getattr(item, field_name))].append(item)
    return {name: _slice_summary(grouped[name]) for name in sorted(grouped)}


def summarize_model_performance(
    account_id: str,
    trades: Iterable[ForwardTradeObservation],
    no_trades: Iterable[NoTradeObservation] = (),
) -> ModelPerformanceSummary:
    """Summarize one SH24/SH25 book without inferring missing evidence.

    Rejections are tracked separately and never increment trade N.  R, MFE and MAE
    coverage is explicit so partial historical evidence cannot masquerade as complete.
    """
    if account_id not in PAPER_SHADOW_ACCOUNTS:
        raise ValueError("UNKNOWN_PAPER_SHADOW_ACCOUNT")

    records = sorted(
        tuple(trades),
        key=lambda item: (item.exit_at, item.trade_id),
    )
    rejected = tuple(no_trades)
    if any(item.account_id != account_id for item in records):
        raise ValueError("TRADE_ACCOUNT_MISMATCH")
    if any(item.account_id != account_id for item in rejected):
        raise ValueError("NO_TRADE_ACCOUNT_MISMATCH")
    if len({item.trade_id for item in records}) != len(records):
        raise ValueError("DUPLICATE_TRADE_ID")
    if len({item.event_id for item in rejected}) != len(rejected):
        raise ValueError("DUPLICATE_NO_TRADE_EVENT_ID")

    pnl = [item.model_pnl for item in records]
    winners = [value for value in pnl if value > 0]
    losers = [value for value in pnl if value < 0]
    wins = len(winners)
    losses = len(losers)
    breakeven = len(records) - wins - losses
    gross_profit = sum(winners)
    gross_loss = -sum(losers)

    r_pairs = [(item, item.r_multiple) for item in records]
    r_values = [value for _, value in r_pairs if value is not None]
    winner_r = [value for _, value in r_pairs if value is not None and value > 0]
    loser_r = [value for _, value in r_pairs if value is not None and value < 0]
    mfe_values = [value for item in records if (value := item.mfe_r) is not None]
    mae_values = [value for item in records if (value := item.mae_r) is not None]
    n = len(records)
    r_coverage = len(r_values) / n if n else 0.0

    if n == 0:
        evidence_status = "NO_CLOSED_TRADES"
    elif r_coverage < 1.0:
        evidence_status = "R_EVIDENCE_INCOMPLETE"
    elif n < MIN_DESCRIPTIVE_SAMPLE:
        evidence_status = "SMALL_SAMPLE_DESCRIPTIVE_ONLY"
    else:
        evidence_status = "DESCRIPTIVE_FORWARD_EVIDENCE"

    return ModelPerformanceSummary(
        account_id=account_id,
        n=n,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=wins / n if n else None,
        cumulative_model_pnl=sum(pnl),
        average_winner_pnl=_mean(winners),
        average_loser_pnl=_mean(losers),
        profit_factor=(gross_profit / gross_loss if gross_loss > 0 else None),
        max_drawdown_pnl=_max_drawdown(pnl),
        r_observations=len(r_values),
        r_coverage=r_coverage,
        cumulative_r=sum(r_values) if r_values else None,
        expectancy_r=_mean(r_values),
        average_winner_r=_mean(winner_r),
        average_loser_r=_mean(loser_r),
        max_drawdown_r=_max_drawdown(r_values) if r_values else None,
        mfe_observations=len(mfe_values),
        mae_observations=len(mae_values),
        average_mfe_r=_mean(mfe_values),
        average_mae_r=_mean(mae_values),
        average_holding_minutes=_mean([item.holding_minutes for item in records]),
        rejection_count=len(rejected),
        rejection_reasons=dict(sorted(Counter(item.reason for item in rejected).items())),
        by_setup_type=_slice(records, "setup_type"),
        by_lifecycle_stage=_slice(records, "lifecycle_stage"),
        by_sector=_slice(records, "sector"),
        by_industry=_slice(records, "industry"),
        evidence_status=evidence_status,
    )


def summarize_shadow_books(
    trades: Iterable[ForwardTradeObservation],
    no_trades: Iterable[NoTradeObservation] = (),
) -> dict[str, ModelPerformanceSummary]:
    """Build fully separated SH24 CONTROL and SH25 CHALLENGER summaries."""
    trade_records = tuple(trades)
    rejected_records = tuple(no_trades)
    return {
        account_id: summarize_model_performance(
            account_id,
            (item for item in trade_records if item.account_id == account_id),
            (item for item in rejected_records if item.account_id == account_id),
        )
        for account_id in PAPER_SHADOW_ACCOUNTS
    }
