import datetime as dt

from daily_alpha.candidates import CandidateAssessment, CandidateBucket
from daily_alpha.prospect_launch_gate import evaluate_prospect_initial_rollout_gate
from daily_alpha.prospect_opportunity_board import build_prospect_opportunity_board
from daily_alpha.prospect_opportunity_outputs import (
    ProspectOutputChannel,
    build_all_v1_prospect_outputs,
    render_prospect_newsletter_html,
)

AS_OF = dt.datetime(2026, 8, 23, 20, 0, tzinfo=dt.UTC)


def _candidate(symbol: str, score: float) -> CandidateAssessment:
    return CandidateAssessment(
        symbol=symbol,
        ovtlyr_status="EMERGING",
        bucket=CandidateBucket.ENTRY_WATCH,
        score=score,
        instrument_selected="STOCK",
        fallback_reason="",
        sector="Technology",
        sector_net_score=7,
        pine_entry=False,
        risk_gate_passed=True,
        optionable=True,
    )


def _board(count: int = 50):
    return build_prospect_opportunity_board(
        items=tuple(_candidate(f"L{i:02d}", float(100 - i)) for i in range(count)),
        as_of=AS_OF,
        source_revision="prospect-launch-gate-fixture-v1",
    )


def test_initial_rollout_gate_passes_only_with_all_channels_complete_board_and_delivery() -> None:
    board = _board(50)
    outputs = build_all_v1_prospect_outputs(board)
    html = render_prospect_newsletter_html(board)

    gate = evaluate_prospect_initial_rollout_gate(
        board=board,
        outputs=outputs,
        newsletter_html=html,
        delivery_contract_validated=True,
    )

    assert gate.ready is True
    assert gate.reasons == ()
    assert gate.total_qualifying == 50
    assert set(gate.verified_channels) == {channel.value for channel in ProspectOutputChannel}
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False


def test_initial_rollout_gate_fails_when_dashboard_channel_is_missing() -> None:
    board = _board(5)
    outputs = tuple(
        output
        for output in build_all_v1_prospect_outputs(board)
        if output.channel is not ProspectOutputChannel.DASHBOARD
    )

    gate = evaluate_prospect_initial_rollout_gate(
        board=board,
        outputs=outputs,
        newsletter_html=render_prospect_newsletter_html(board),
        delivery_contract_validated=True,
    )

    assert gate.ready is False
    assert "MISSING_REQUIRED_CHANNEL:DASHBOARD" in gate.reasons


def test_initial_rollout_gate_fails_when_delivery_contract_is_not_validated() -> None:
    board = _board(4)

    gate = evaluate_prospect_initial_rollout_gate(
        board=board,
        outputs=build_all_v1_prospect_outputs(board),
        newsletter_html=render_prospect_newsletter_html(board),
        delivery_contract_validated=False,
    )

    assert gate.ready is False
    assert "NEWSLETTER_DELIVERY_CONTRACT_NOT_VALIDATED" in gate.reasons


def test_initial_rollout_gate_fails_when_newsletter_omits_one_of_fifty() -> None:
    board = _board(50)
    html = render_prospect_newsletter_html(board).replace("L49", "OMITTED", 1)

    gate = evaluate_prospect_initial_rollout_gate(
        board=board,
        outputs=build_all_v1_prospect_outputs(board),
        newsletter_html=html,
        delivery_contract_validated=True,
    )

    assert gate.ready is False
    assert "NEWSLETTER_CANONICAL_OPPORTUNITY_MISSING" in gate.reasons


def test_initial_rollout_gate_requires_canonical_board_identity_in_newsletter() -> None:
    board = _board(3)
    html = render_prospect_newsletter_html(board).replace(board.board_id, "wrong-board", 1)

    gate = evaluate_prospect_initial_rollout_gate(
        board=board,
        outputs=build_all_v1_prospect_outputs(board),
        newsletter_html=html,
        delivery_contract_validated=True,
    )

    assert gate.ready is False
    assert "NEWSLETTER_BOARD_ID_MISMATCH" in gate.reasons
