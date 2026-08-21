"""Research-only turnover hysteresis for scalable Daily Alpha portfolio studies.

This module deliberately has no connection to execution. It tests whether separate
entry, hold, and replacement thresholds can reduce unnecessary portfolio churn
without weakening hard exits or thesis invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HysteresisAction(StrEnum):
    """Research classification for one point-in-time portfolio decision."""

    ENTER = "ENTER"
    HOLD = "HOLD"
    HOLD_PERSISTENCE = "HOLD_PERSISTENCE"
    REPLACE = "REPLACE"
    EXIT_SOFT = "EXIT_SOFT"
    EXIT_HARD = "EXIT_HARD"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class HysteresisConfig:
    """Explicit research thresholds.

    Score values are model-score units, not returns or probabilities. Thresholds
    must be selected from training/walk-forward history rather than the full sample.
    """

    entry_score_min: float
    hold_score_min: float
    replace_edge_min: float
    soft_persistence_days: int = 0
    entry_rank_max: int | None = None
    hold_rank_max: int | None = None

    def __post_init__(self) -> None:
        if self.hold_score_min > self.entry_score_min:
            raise ValueError("hold_score_min must be <= entry_score_min")
        if self.replace_edge_min < 0:
            raise ValueError("replace_edge_min must be non-negative")
        if self.soft_persistence_days < 0:
            raise ValueError("soft_persistence_days must be non-negative")
        if self.entry_rank_max is not None and self.entry_rank_max <= 0:
            raise ValueError("entry_rank_max must be positive when supplied")
        if self.hold_rank_max is not None and self.hold_rank_max <= 0:
            raise ValueError("hold_rank_max must be positive when supplied")
        if (
            self.entry_rank_max is not None
            and self.hold_rank_max is not None
            and self.hold_rank_max < self.entry_rank_max
        ):
            raise ValueError("hold_rank_max must be >= entry_rank_max")


@dataclass(frozen=True)
class CandidateState:
    """Point-in-time candidate state used by the research decision model."""

    score: float
    rank: int | None = None

    def __post_init__(self) -> None:
        if self.rank is not None and self.rank <= 0:
            raise ValueError("rank must be positive when supplied")


@dataclass(frozen=True)
class HysteresisDecision:
    """Auditable result from the research-only hysteresis classifier."""

    action: HysteresisAction
    reason: str
    incumbent_score: float | None
    challenger_score: float | None
    challenger_edge: float | None
    effective_replace_edge_min: float
    days_below_hold: int
    research_only: bool = True



def _rank_qualifies(rank: int | None, maximum: int | None) -> bool:
    if maximum is None:
        return True
    return rank is not None and rank <= maximum



def qualifies_for_entry(candidate: CandidateState, config: HysteresisConfig) -> bool:
    """Return whether a point-in-time candidate qualifies as a *new* holding."""

    return candidate.score >= config.entry_score_min and _rank_qualifies(
        candidate.rank, config.entry_rank_max
    )



def qualifies_for_hold(incumbent: CandidateState, config: HysteresisConfig) -> bool:
    """Return whether an existing position remains inside the softer hold region."""

    return incumbent.score >= config.hold_score_min and _rank_qualifies(
        incumbent.rank, config.hold_rank_max
    )



def evaluate_hysteresis(
    *,
    incumbent: CandidateState | None,
    challenger: CandidateState | None,
    config: HysteresisConfig,
    days_below_hold: int = 0,
    hard_exit: bool = False,
    additional_replace_edge: float = 0.0,
) -> HysteresisDecision:
    """Classify a point-in-time research portfolio decision.

    ``additional_replace_edge`` lets a capacity study raise the replacement hurdle
    for expected implementation cost or liquidity pressure. It remains in model-score
    units and must be computed by the caller; this module never converts basis points
    into model score.

    A hard exit always dominates hysteresis. This prevents the research experiment
    from weakening Pine/Turtle exits, failed-breakout exits, earnings-risk exits,
    DATA_ERROR safety behavior, or explicit thesis invalidation.
    """

    if days_below_hold < 0:
        raise ValueError("days_below_hold must be non-negative")
    if additional_replace_edge < 0:
        raise ValueError("additional_replace_edge must be non-negative")

    effective_edge = config.replace_edge_min + additional_replace_edge
    incumbent_score = incumbent.score if incumbent is not None else None
    challenger_score = challenger.score if challenger is not None else None
    challenger_edge = (
        challenger.score - incumbent.score
        if incumbent is not None and challenger is not None
        else None
    )

    if hard_exit and incumbent is not None:
        return HysteresisDecision(
            action=HysteresisAction.EXIT_HARD,
            reason="hard exit overrides turnover hysteresis",
            incumbent_score=incumbent_score,
            challenger_score=challenger_score,
            challenger_edge=challenger_edge,
            effective_replace_edge_min=effective_edge,
            days_below_hold=days_below_hold,
        )

    if incumbent is None:
        if challenger is not None and qualifies_for_entry(challenger, config):
            return HysteresisDecision(
                action=HysteresisAction.ENTER,
                reason="flat portfolio and challenger meets entry threshold",
                incumbent_score=None,
                challenger_score=challenger_score,
                challenger_edge=None,
                effective_replace_edge_min=effective_edge,
                days_below_hold=days_below_hold,
            )
        return HysteresisDecision(
            action=HysteresisAction.NO_ACTION,
            reason="no incumbent and no challenger qualifies for entry",
            incumbent_score=None,
            challenger_score=challenger_score,
            challenger_edge=None,
            effective_replace_edge_min=effective_edge,
            days_below_hold=days_below_hold,
        )

    challenger_can_enter = challenger is not None and qualifies_for_entry(challenger, config)
    replacement_has_edge = (
        challenger_can_enter
        and challenger_edge is not None
        and challenger_edge >= effective_edge
    )
    incumbent_can_hold = qualifies_for_hold(incumbent, config)

    if incumbent_can_hold:
        if replacement_has_edge:
            return HysteresisDecision(
                action=HysteresisAction.REPLACE,
                reason="qualified challenger exceeds replacement edge",
                incumbent_score=incumbent_score,
                challenger_score=challenger_score,
                challenger_edge=challenger_edge,
                effective_replace_edge_min=effective_edge,
                days_below_hold=days_below_hold,
            )
        return HysteresisDecision(
            action=HysteresisAction.HOLD,
            reason="incumbent remains inside hold region",
            incumbent_score=incumbent_score,
            challenger_score=challenger_score,
            challenger_edge=challenger_edge,
            effective_replace_edge_min=effective_edge,
            days_below_hold=days_below_hold,
        )

    if days_below_hold < config.soft_persistence_days:
        if replacement_has_edge:
            return HysteresisDecision(
                action=HysteresisAction.REPLACE,
                reason="incumbent below hold region and qualified challenger has enough edge",
                incumbent_score=incumbent_score,
                challenger_score=challenger_score,
                challenger_edge=challenger_edge,
                effective_replace_edge_min=effective_edge,
                days_below_hold=days_below_hold,
            )
        return HysteresisDecision(
            action=HysteresisAction.HOLD_PERSISTENCE,
            reason="incumbent below hold region but soft persistence window remains",
            incumbent_score=incumbent_score,
            challenger_score=challenger_score,
            challenger_edge=challenger_edge,
            effective_replace_edge_min=effective_edge,
            days_below_hold=days_below_hold,
        )

    if replacement_has_edge:
        return HysteresisDecision(
            action=HysteresisAction.REPLACE,
            reason="soft persistence exhausted and qualified challenger has enough edge",
            incumbent_score=incumbent_score,
            challenger_score=challenger_score,
            challenger_edge=challenger_edge,
            effective_replace_edge_min=effective_edge,
            days_below_hold=days_below_hold,
        )

    return HysteresisDecision(
        action=HysteresisAction.EXIT_SOFT,
        reason="incumbent failed hold region after persistence window",
        incumbent_score=incumbent_score,
        challenger_score=challenger_score,
        challenger_edge=challenger_edge,
        effective_replace_edge_min=effective_edge,
        days_below_hold=days_below_hold,
    )
