"""Fail-closed initial-rollout gate for the V1 prospect/subscriber opportunity experience."""

from __future__ import annotations

from dataclasses import dataclass

from .prospect_opportunity_board import ProspectOpportunityBoard
from .prospect_opportunity_outputs import ProspectOpportunityOutput, ProspectOutputChannel


@dataclass(frozen=True, slots=True)
class ProspectInitialRolloutGate:
    board_id: str
    total_qualifying: int
    required_channels: tuple[str, ...]
    verified_channels: tuple[str, ...]
    delivery_contract_validated: bool
    reasons: tuple[str, ...]
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    @property
    def ready(self) -> bool:
        return not self.reasons


def evaluate_prospect_initial_rollout_gate(
    *,
    board: ProspectOpportunityBoard,
    outputs: tuple[ProspectOpportunityOutput, ...],
    newsletter_html: str,
    delivery_contract_validated: bool,
) -> ProspectInitialRolloutGate:
    """Require one canonical board across every required V1 customer/prospect output."""
    reasons: list[str] = []
    required = tuple(channel.value for channel in ProspectOutputChannel)
    channels = tuple(output.channel.value for output in outputs)
    if len(set(channels)) != len(channels):
        reasons.append("DUPLICATE_OUTPUT_CHANNEL")
    missing = tuple(sorted(set(required) - set(channels)))
    if missing:
        reasons.append("MISSING_REQUIRED_CHANNEL:" + ",".join(missing))
    extra = tuple(sorted(set(channels) - set(required)))
    if extra:
        reasons.append("UNSUPPORTED_OUTPUT_CHANNEL:" + ",".join(extra))

    canonical_ids = tuple(item.candidate_id for item in board.opportunities)
    canonical_top_ids = tuple(item.candidate_id for item in board.top_picks)
    for output in outputs:
        if output.board_id != board.board_id:
            reasons.append(f"{output.channel.value}_BOARD_ID_MISMATCH")
        if output.total_qualifying != board.total_qualifying:
            reasons.append(f"{output.channel.value}_TOTAL_QUALIFYING_MISMATCH")
        output_ids = tuple(item.candidate_id for item in output.complete_qualifying)
        if output_ids != canonical_ids:
            reasons.append(f"{output.channel.value}_CANONICAL_SET_MISMATCH")
        output_top_ids = tuple(item.candidate_id for item in output.top_picks)
        if output_top_ids != canonical_top_ids:
            reasons.append(f"{output.channel.value}_TOP_PICKS_MISMATCH")
        if output.trading_authorized or output.live_trading_enabled:
            reasons.append(f"{output.channel.value}_EXECUTION_AUTHORITY_INVALID")

    if not board.prospect_ready:
        reasons.append("CANONICAL_BOARD_NOT_PROSPECT_READY")
    if board.trading_authorized or board.live_trading_enabled:
        reasons.append("CANONICAL_BOARD_EXECUTION_AUTHORITY_INVALID")

    if "Top 3 ConvexRidge Picks" not in newsletter_html:
        reasons.append("NEWSLETTER_TOP3_SECTION_MISSING")
    if f'data-board-id="{board.board_id}"' not in newsletter_html:
        reasons.append("NEWSLETTER_BOARD_ID_MISMATCH")
    if f'data-total-qualifying="{board.total_qualifying}"' not in newsletter_html:
        reasons.append("NEWSLETTER_TOTAL_QUALIFYING_MISMATCH")
    if any(item.symbol not in newsletter_html for item in board.opportunities):
        reasons.append("NEWSLETTER_CANONICAL_OPPORTUNITY_MISSING")
    if not delivery_contract_validated:
        reasons.append("NEWSLETTER_DELIVERY_CONTRACT_NOT_VALIDATED")

    return ProspectInitialRolloutGate(
        board_id=board.board_id,
        total_qualifying=board.total_qualifying,
        required_channels=required,
        verified_channels=tuple(sorted(set(channels))),
        delivery_contract_validated=delivery_contract_validated,
        reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "ProspectInitialRolloutGate",
    "evaluate_prospect_initial_rollout_gate",
]
