"""Pre-registered research selectors for sector-residual momentum challenger #156.

These helpers operate only on already-qualified R2 research states. They do not generate
trading instructions, mutate portfolios, or authorize PAPER/live execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from daily_alpha.sector_residual_research import (
    ResidualMomentumPolicy,
    SectorResidualMomentumState,
)


class ResidualResearchVariant(StrEnum):
    """Frozen first-pass challenger variants from issue #156."""

    CONTROL = "CONTROL"
    RESIDUAL_POSITIVE = "RESIDUAL_POSITIVE"
    WITHIN_SECTOR_P50 = "WITHIN_SECTOR_P50"
    WITHIN_SECTOR_P65 = "WITHIN_SECTOR_P65"
    RANKING_ONLY = "RANKING_ONLY"


@dataclass(frozen=True, slots=True)
class ResidualVariantDecision:
    """Research-only inclusion/ranking decision for one qualified candidate."""

    security_id: str
    ticker: str
    variant: ResidualResearchVariant
    included: bool
    ranking_score: float | None
    research_only: bool = True
    paper_entry_authorized: bool = False
    portfolio_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def evaluate_residual_variant(
    state: SectorResidualMomentumState,
    variant: ResidualResearchVariant,
    *,
    policy: ResidualMomentumPolicy | None = None,
) -> ResidualVariantDecision:
    """Apply exactly one pre-registered challenger rule to a qualified R2 state.

    CONTROL and RANKING_ONLY never exclude a qualified control candidate. RANKING_ONLY
    exposes the residual score solely as a research tie-break/ranking feature. The P50/P65
    challengers intentionally implement the issue's percentile tests independently of the
    separate RESIDUAL_POSITIVE challenger rather than silently combining thresholds.
    """

    policy = policy or ResidualMomentumPolicy()
    if variant is ResidualResearchVariant.CONTROL:
        included = True
        ranking_score = None
    elif variant is ResidualResearchVariant.RESIDUAL_POSITIVE:
        included = state.residual_score > policy.positive_residual_floor
        ranking_score = None
    elif variant is ResidualResearchVariant.WITHIN_SECTOR_P50:
        included = state.within_sector_percentile >= policy.confirmation_percentile
        ranking_score = None
    elif variant is ResidualResearchVariant.WITHIN_SECTOR_P65:
        included = state.within_sector_percentile >= policy.leader_percentile
        ranking_score = None
    elif variant is ResidualResearchVariant.RANKING_ONLY:
        included = True
        ranking_score = state.residual_score
    else:  # pragma: no cover - defensive against future enum extension
        raise ValueError(f"unsupported residual research variant: {variant}")

    return ResidualVariantDecision(
        security_id=state.security_id,
        ticker=state.ticker,
        variant=variant,
        included=included,
        ranking_score=ranking_score,
    )


def evaluate_all_pre_registered_variants(
    state: SectorResidualMomentumState,
    *,
    policy: ResidualMomentumPolicy | None = None,
) -> tuple[ResidualVariantDecision, ...]:
    """Return deterministic decisions for every frozen first-pass challenger."""

    return tuple(
        evaluate_residual_variant(state, variant, policy=policy)
        for variant in ResidualResearchVariant
    )
