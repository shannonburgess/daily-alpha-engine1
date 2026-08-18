"""Dry-run desired-state planning for ranked-candidate TradingView alerts.

This module never calls TradingView and never authorizes a trade. It creates an
auditable desired-state diff that can later sit behind an explicit mutation approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .candidates import CandidateAssessment, CandidateBucket


class AlertPlanAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DISABLE = "DISABLE"
    MIGRATE_STRATEGY = "MIGRATE_STRATEGY"
    NO_CHANGE = "NO_CHANGE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class DesiredAlert:
    symbol: str
    strategy_version: str
    timeframe: str
    enabled: bool
    source_ranked_at: str
    review_after: str

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.source_ranked_at)
        datetime.fromisoformat(self.review_after)
        if not all((self.symbol, self.strategy_version, self.timeframe)):
            raise ValueError("alert symbol, strategy_version and timeframe are required")


@dataclass(frozen=True)
class ObservedAlert:
    alert_key: str
    symbol: str
    strategy_version: str
    timeframe: str
    enabled: bool

    def __post_init__(self) -> None:
        if not all((self.alert_key, self.symbol, self.strategy_version, self.timeframe)):
            raise ValueError("observed alert identity and configuration are required")


@dataclass(frozen=True)
class AlertPlanItem:
    symbol: str
    action: AlertPlanAction
    desired: DesiredAlert | None
    observed: ObservedAlert | None
    reason: str


@dataclass(frozen=True)
class AlertPlan:
    source_ranked_at: str
    strategy_version: str
    dry_run: bool
    mutation_allowed: bool
    items: tuple[AlertPlanItem, ...]

    @property
    def has_data_error(self) -> bool:
        return any(item.action == AlertPlanAction.DATA_ERROR for item in self.items)

    @property
    def proposed_mutations(self) -> tuple[AlertPlanItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.action
            in {
                AlertPlanAction.CREATE,
                AlertPlanAction.UPDATE,
                AlertPlanAction.DISABLE,
                AlertPlanAction.MIGRATE_STRATEGY,
            }
        )


ALERT_ELIGIBLE_BUCKETS = frozenset(
    {
        CandidateBucket.OPTION_SETUP,
        CandidateBucket.STOCK_FALLBACK,
        CandidateBucket.ENTRY_WATCH,
    }
)


def desired_alerts_from_ranked_candidates(
    *,
    candidates: tuple[CandidateAssessment, ...],
    strategy_version: str,
    timeframe: str,
    source_ranked_at: str,
    review_after: str,
) -> tuple[DesiredAlert, ...]:
    """Translate candidate state into monitoring-alert desired state only."""

    datetime.fromisoformat(source_ranked_at)
    datetime.fromisoformat(review_after)
    if not strategy_version or not timeframe:
        raise ValueError("strategy_version and timeframe are required")

    symbols = sorted(
        {
            candidate.symbol
            for candidate in candidates
            if candidate.bucket in ALERT_ELIGIBLE_BUCKETS
        }
    )
    return tuple(
        DesiredAlert(
            symbol=symbol,
            strategy_version=strategy_version,
            timeframe=timeframe,
            enabled=True,
            source_ranked_at=source_ranked_at,
            review_after=review_after,
        )
        for symbol in symbols
    )


def plan_alert_changes(
    *,
    desired: tuple[DesiredAlert, ...],
    observed: tuple[ObservedAlert, ...],
    source_ranked_at: str,
    strategy_version: str,
    source_fresh: bool,
    source_complete: bool,
) -> AlertPlan:
    """Build a deterministic dry-run diff; mutations are always disabled here."""

    datetime.fromisoformat(source_ranked_at)
    if not strategy_version:
        raise ValueError("strategy_version is required")

    if not source_fresh or not source_complete:
        reason = "STALE_CANDIDATE_SOURCE" if not source_fresh else "INCOMPLETE_CANDIDATE_SOURCE"
        return AlertPlan(
            source_ranked_at=source_ranked_at,
            strategy_version=strategy_version,
            dry_run=True,
            mutation_allowed=False,
            items=(AlertPlanItem("*", AlertPlanAction.DATA_ERROR, None, None, reason),),
        )

    desired_by_symbol = {item.symbol: item for item in desired}
    observed_by_symbol = {item.symbol: item for item in observed}
    if len(desired_by_symbol) != len(desired):
        raise ValueError("desired alert symbols must be unique")
    if len(observed_by_symbol) != len(observed):
        raise ValueError("observed alert symbols must be unique")

    items: list[AlertPlanItem] = []
    for symbol in sorted(desired_by_symbol | observed_by_symbol):
        target = desired_by_symbol.get(symbol)
        current = observed_by_symbol.get(symbol)

        if target is None and current is not None:
            action = AlertPlanAction.DISABLE if current.enabled else AlertPlanAction.NO_CHANGE
            reason = "CANDIDATE_REMOVED" if current.enabled else "ALREADY_DISABLED"
        elif target is not None and current is None:
            action = AlertPlanAction.CREATE
            reason = "CANDIDATE_ADDED"
        elif target is not None and current is not None:
            if current.strategy_version != target.strategy_version:
                action = AlertPlanAction.MIGRATE_STRATEGY
                reason = "EXPLICIT_STRATEGY_VERSION_MIGRATION_REQUIRED"
            elif current.timeframe != target.timeframe or current.enabled != target.enabled:
                action = AlertPlanAction.UPDATE
                reason = "CONFIGURATION_DRIFT"
            else:
                action = AlertPlanAction.NO_CHANGE
                reason = "DESIRED_STATE_MATCHES_OBSERVED"
        else:
            raise RuntimeError("unreachable alert planning state")

        items.append(AlertPlanItem(symbol, action, target, current, reason))

    return AlertPlan(
        source_ranked_at=source_ranked_at,
        strategy_version=strategy_version,
        dry_run=True,
        mutation_allowed=False,
        items=tuple(items),
    )
