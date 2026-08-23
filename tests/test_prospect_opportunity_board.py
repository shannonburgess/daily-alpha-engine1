from datetime import UTC, datetime

import pytest

from daily_alpha.candidates import CandidateAssessment, CandidateBucket
from daily_alpha.prospect_opportunity_board import (
    SIGNAL_CONTEXT,
    OpportunityBoardFilter,
    ProspectOpportunityBoard,
    ProspectOpportunityBoardError,
    build_prospect_opportunity_board,
)

AS_OF = datetime(2026, 8, 23, 19, 0, tzinfo=UTC)


def _candidate(
    symbol: str,
    score: float,
    *,
    bucket: CandidateBucket = CandidateBucket.ENTRY_WATCH,
    status: str = "EMERGING",
    fallback_reason: str = "",
    sector: str = "Technology",
    instrument_selected: str = "NONE",
) -> CandidateAssessment:
    return CandidateAssessment(
        symbol=symbol,
        ovtlyr_status=status,
        bucket=bucket,
        score=score,
        instrument_selected=instrument_selected,
        fallback_reason=fallback_reason,
        sector=sector,
        sector_net_score=10,
        pine_entry=bucket is not CandidateBucket.ENTRY_WATCH,
        risk_gate_passed=True,
        optionable=True,
    )


def test_v1_surfaces_top_three_and_all_fifty_qualifying_opportunities() -> None:
    candidates = tuple(_candidate(f"S{i:02d}", float(100 - i)) for i in range(50))

    board = build_prospect_opportunity_board(
        items=candidates,
        as_of=AS_OF,
        source_revision="candidate-snapshot-2026-08-23",
    )

    assert board.total_qualifying == 50
    assert len(board.top_picks) == 3
    assert len(board.additional_opportunities) == 47
    assert len(board.opportunities) == 50
    assert [item.rank for item in board.opportunities] == list(range(1, 51))
    assert [item.symbol for item in board.top_picks] == ["S00", "S01", "S02"]
    assert board.additional_opportunities[0].symbol == "S03"
    assert board.additional_opportunities[-1].symbol == "S49"


def test_top_three_are_members_of_the_same_complete_canonical_board() -> None:
    board = build_prospect_opportunity_board(
        items=tuple(_candidate(f"X{i}", float(10 - i)) for i in range(6)),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    canonical_ids = {item.candidate_id for item in board.opportunities}
    assert {item.candidate_id for item in board.top_picks} <= canonical_ids
    assert tuple(item.rank for item in board.top_picks) == (1, 2, 3)


def test_fewer_than_three_qualifiers_does_not_manufacture_picks() -> None:
    board = build_prospect_opportunity_board(
        items=(_candidate("MU", 90.0), _candidate("NVDA", 80.0)),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    assert board.total_qualifying == 2
    assert len(board.top_picks) == 2
    assert board.additional_opportunities == ()


def test_ready_setups_rank_ahead_of_entry_watch_without_truncating_board() -> None:
    board = build_prospect_opportunity_board(
        items=(
            _candidate("WATCH", 999.0, bucket=CandidateBucket.ENTRY_WATCH),
            _candidate("STOCK", 1.0, bucket=CandidateBucket.STOCK_FALLBACK),
            _candidate("OPTION", 1.0, bucket=CandidateBucket.OPTION_SETUP),
            _candidate("WATCH2", 998.0, bucket=CandidateBucket.ENTRY_WATCH),
        ),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    assert [item.symbol for item in board.opportunities] == [
        "OPTION",
        "STOCK",
        "WATCH",
        "WATCH2",
    ]
    assert board.total_qualifying == 4


def test_filtered_candidates_remain_auditable_instead_of_silently_disappearing() -> None:
    board = build_prospect_opportunity_board(
        items=(
            _candidate("GOOD", 90.0),
            _candidate(
                "BAD_DATA",
                80.0,
                bucket=CandidateBucket.DATA_ERROR,
                fallback_reason="ORATS_DATA_ERROR",
            ),
            _candidate("NOPE", 70.0, bucket=CandidateBucket.NO_TRADE),
        ),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    assert board.total_qualifying == 1
    assert {item.symbol for item in board.filtered} == {"BAD_DATA", "NOPE"}
    reasons = {item.symbol: item.reason for item in board.filtered}
    assert reasons["BAD_DATA"] == "ORATS_DATA_ERROR"
    assert reasons["NOPE"] == "NOT_CURRENTLY_QUALIFIED"


def test_pagination_never_changes_canonical_qualifying_count() -> None:
    board = build_prospect_opportunity_board(
        items=tuple(_candidate(f"P{i:02d}", float(100 - i)) for i in range(50)),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    first = board.page(offset=0, limit=20)
    second = board.page(offset=20, limit=20)
    third = board.page(offset=40, limit=20)

    assert first.total_qualifying == second.total_qualifying == third.total_qualifying == 50
    assert first.total_matched == second.total_matched == third.total_matched == 50
    assert len(first.opportunities) == 20
    assert len(second.opportunities) == 20
    assert len(third.opportunities) == 10
    assert first.has_more is True
    assert second.has_more is True
    assert third.has_more is False
    assert [item.symbol for page in (first, second, third) for item in page.opportunities] == [
        item.symbol for item in board.opportunities
    ]


def test_filters_are_query_views_and_never_change_canonical_membership_or_rank() -> None:
    board = build_prospect_opportunity_board(
        items=(
            _candidate("A", 100.0, status="LEADER", sector="Technology"),
            _candidate("B", 99.0, status="EMERGING", sector="Healthcare"),
            _candidate("C", 98.0, status="LEADER", sector="Technology"),
            _candidate("D", 97.0, status="LEADER", sector="Healthcare"),
        ),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )
    canonical_ids = tuple(item.candidate_id for item in board.opportunities)
    query = OpportunityBoardFilter(
        lifecycle_statuses=("leader",),
        sectors=("technology",),
    )

    page = board.page(query=query, offset=0, limit=10)

    assert page.board_id == board.board_id
    assert page.total_qualifying == 4
    assert page.total_matched == 2
    assert [(item.rank, item.symbol) for item in page.opportunities] == [(1, "A"), (3, "C")]
    assert tuple(item.candidate_id for item in board.opportunities) == canonical_ids
    assert board.top_picks == board.opportunities[:3]


def test_filtered_pagination_preserves_full_count_and_reconstructs_all_matches() -> None:
    board = build_prospect_opportunity_board(
        items=tuple(
            _candidate(
                f"F{i:02d}",
                float(100 - i),
                sector="Technology" if i % 2 == 0 else "Healthcare",
            )
            for i in range(50)
        ),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )
    query = OpportunityBoardFilter(sectors=("healthcare",))

    first = board.page(query=query, offset=0, limit=10)
    second = board.page(query=query, offset=10, limit=10)
    third = board.page(query=query, offset=20, limit=10)

    assert {page.total_qualifying for page in (first, second, third)} == {50}
    assert {page.total_matched for page in (first, second, third)} == {25}
    assert first.filter_id == second.filter_id == third.filter_id == query.filter_id
    assert first.has_more is True
    assert second.has_more is True
    assert third.has_more is False
    assert len(first.opportunities) == 10
    assert len(second.opportunities) == 10
    assert len(third.opportunities) == 5
    assert [item.symbol for page in (first, second, third) for item in page.opportunities] == [
        item.symbol for item in board.opportunities if item.sector == "Healthcare"
    ]


def test_filter_identity_is_normalized_order_independent_and_fail_closed() -> None:
    first = OpportunityBoardFilter(
        symbols=("nvda", "MU"),
        lifecycle_statuses=("leader", "emerging"),
        sectors=("technology",),
    )
    second = OpportunityBoardFilter(
        sectors=("TECHNOLOGY",),
        lifecycle_statuses=("EMERGING", "LEADER"),
        symbols=("mu", "NVDA"),
    )

    assert first == second
    assert first.filter_id == second.filter_id

    with pytest.raises(ProspectOpportunityBoardError, match="FILTER_BUCKET_NOT_QUALIFYING"):
        OpportunityBoardFilter(buckets=(CandidateBucket.DATA_ERROR.value,))

    with pytest.raises(ProspectOpportunityBoardError, match="FILTER_SECTOR_VALUE_REQUIRED"):
        OpportunityBoardFilter(sectors=("",))


def test_board_identity_is_input_order_independent() -> None:
    first = build_prospect_opportunity_board(
        items=(_candidate("MU", 90.0), _candidate("NVDA", 80.0)),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )
    second = build_prospect_opportunity_board(
        items=(_candidate("NVDA", 80.0), _candidate("MU", 90.0)),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    assert first.board_id == second.board_id


def test_duplicate_symbol_fails_closed() -> None:
    with pytest.raises(ProspectOpportunityBoardError, match="DUPLICATE_SYMBOL"):
        build_prospect_opportunity_board(
            items=(_candidate("MU", 90.0), _candidate("mu", 80.0)),
            as_of=AS_OF,
            source_revision="snapshot-v1",
        )


def test_prospect_board_cannot_authorize_portfolio_or_execution() -> None:
    board = build_prospect_opportunity_board(
        items=(_candidate("MU", 90.0),),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    assert board.signal_context == SIGNAL_CONTEXT
    assert board.portfolio_recommendation_authorized is False
    assert board.paper_mutation_authorized is False
    assert board.trading_authorized is False
    assert board.live_trading_enabled is False

    with pytest.raises(ProspectOpportunityBoardError, match="CANNOT_GRANT_EXECUTION_AUTHORITY"):
        ProspectOpportunityBoard(
            as_of=board.as_of,
            source_revision=board.source_revision,
            opportunities=board.opportunities,
            filtered=board.filtered,
            trading_authorized=True,
        )


def test_serialization_contains_top_three_additional_and_full_board() -> None:
    board = build_prospect_opportunity_board(
        items=tuple(_candidate(f"Z{i}", float(10 - i)) for i in range(5)),
        as_of=AS_OF,
        source_revision="snapshot-v1",
    )

    payload = board.to_dict()

    assert payload["total_qualifying"] == 5
    assert len(payload["top_picks"]) == 3
    assert len(payload["additional_opportunities"]) == 2
    assert len(payload["full_qualified_opportunity_board"]) == 5
