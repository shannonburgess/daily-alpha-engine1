import datetime as dt

from daily_alpha.candidates import CandidateAssessment, CandidateBucket
from daily_alpha.newsletter_delivery import AwsNewsletterEmailDelivery, NewsletterEmailConfig
from daily_alpha.prospect_opportunity_board import (
    OpportunityBoardFilter,
    build_prospect_opportunity_board,
)
from daily_alpha.prospect_opportunity_outputs import (
    ProspectOutputChannel,
    build_all_v1_prospect_outputs,
    build_prospect_api_page,
    build_prospect_output,
    render_prospect_newsletter_html,
)

AS_OF = dt.datetime(2026, 8, 23, 19, 0, tzinfo=dt.UTC)


class _FakeSes:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.requests.append(kwargs)
        return {"MessageId": "prospect-v1-message"}


def _candidate(symbol: str, score: float) -> CandidateAssessment:
    return CandidateAssessment(
        symbol=symbol,
        ovtlyr_status="EMERGING",
        bucket=CandidateBucket.ENTRY_WATCH,
        score=score,
        instrument_selected="STOCK",
        fallback_reason="",
        sector="Technology",
        sector_net_score=8,
        pine_entry=False,
        risk_gate_passed=True,
        optionable=True,
    )


def _board(count: int):
    return build_prospect_opportunity_board(
        items=tuple(_candidate(f"Q{i:02d}", float(100 - i)) for i in range(count)),
        as_of=AS_OF,
        source_revision="prospect-output-fixture-v1",
    )


def test_all_v1_output_channels_share_exact_board_and_complete_set() -> None:
    board = _board(50)

    outputs = build_all_v1_prospect_outputs(board)

    assert {output.channel for output in outputs} == set(ProspectOutputChannel)
    assert {output.board_id for output in outputs} == {board.board_id}
    assert {output.total_qualifying for output in outputs} == {50}
    canonical_ids = tuple(item.candidate_id for item in board.opportunities)
    for output in outputs:
        assert tuple(item.candidate_id for item in output.complete_qualifying) == canonical_ids
        assert tuple(item.candidate_id for item in output.top_picks) == canonical_ids[:3]
        assert output.trading_authorized is False
        assert output.live_trading_enabled is False


def test_newsletter_output_contains_top_three_and_all_other_47() -> None:
    board = _board(50)

    html = render_prospect_newsletter_html(board)

    assert "Daily Alpha Research" in html
    assert "Top 3 ConvexRidge Picks" in html
    assert "Additional Qualified Opportunities" in html
    assert f'data-board-id="{board.board_id}"' in html
    assert 'data-total-qualifying="50"' in html
    for opportunity in board.opportunities:
        assert opportunity.symbol in html
    assert html.index("Q00") < html.index("Additional Qualified Opportunities")
    assert html.index("Q01") < html.index("Additional Qualified Opportunities")
    assert html.index("Q02") < html.index("Additional Qualified Opportunities")
    assert html.index("Q03") > html.index("Additional Qualified Opportunities")
    assert html.index("Q49") > html.index("Additional Qualified Opportunities")


def test_newsletter_does_not_fill_missing_top_three_slots() -> None:
    board = _board(2)

    output = build_prospect_output(board, channel=ProspectOutputChannel.NEWSLETTER)
    html = render_prospect_newsletter_html(board)

    assert len(output.top_picks) == 2
    assert output.total_qualifying == 2
    assert "Q00" in html
    assert "Q01" in html
    assert "Rank #3" not in html


def test_api_output_serializes_all_fifty_not_only_featured_three() -> None:
    board = _board(50)

    payload = build_prospect_output(board, channel=ProspectOutputChannel.API).to_dict()

    assert payload["channel"] == "API"
    assert payload["total_qualifying"] == 50
    assert len(payload["top_picks"]) == 3
    assert len(payload["complete_qualifying"]) == 50
    assert payload["board_id"] == board.board_id


def test_api_query_page_filters_and_paginates_without_mutating_canonical_set() -> None:
    board = _board(50)
    canonical_ids = tuple(item.candidate_id for item in board.opportunities)
    query = OpportunityBoardFilter(symbols=tuple(f"Q{i:02d}" for i in range(10, 30)))

    first = build_prospect_api_page(board, query=query, offset=0, limit=7)
    second = build_prospect_api_page(board, query=query, offset=7, limit=7)
    third = build_prospect_api_page(board, query=query, offset=14, limit=7)

    assert {page.board_id for page in (first, second, third)} == {board.board_id}
    assert {page.filter_id for page in (first, second, third)} == {query.filter_id}
    assert {page.total_qualifying for page in (first, second, third)} == {50}
    assert {page.total_matched for page in (first, second, third)} == {20}
    assert [item.symbol for page in (first, second, third) for item in page.opportunities] == [
        f"Q{i:02d}" for i in range(10, 30)
    ]
    assert first.has_more is True
    assert second.has_more is True
    assert third.has_more is False
    assert tuple(item.candidate_id for item in board.opportunities) == canonical_ids
    assert board.total_qualifying == 50

    payload = first.to_dict()
    assert payload["channel"] == "API"
    assert payload["total_qualifying"] == 50
    assert payload["total_matched"] == 20
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False


def test_dashboard_output_uses_same_canonical_board_identity() -> None:
    board = _board(7)

    newsletter = build_prospect_output(board, channel=ProspectOutputChannel.NEWSLETTER)
    dashboard = build_prospect_output(board, channel=ProspectOutputChannel.DASHBOARD)
    api = build_prospect_output(board, channel=ProspectOutputChannel.API)

    assert newsletter.board_id == dashboard.board_id == api.board_id == board.board_id
    assert newsletter.complete_qualifying == dashboard.complete_qualifying == api.complete_qualifying
    assert newsletter.top_picks == dashboard.top_picks == api.top_picks


def test_prospect_newsletter_is_compatible_with_existing_ses_delivery_boundary() -> None:
    board = _board(50)
    html = render_prospect_newsletter_html(board)
    ses = _FakeSes()
    delivery = AwsNewsletterEmailDelivery(
        config=NewsletterEmailConfig(
            sender="sender@example.com",
            recipients=("prospect@example.com",),
        ),
        s3_client=object(),
        sesv2_client=ses,
        bucket="fixture-bucket",
    )

    result = delivery.send_html(
        html=html,
        report_date="2026-08-23",
        session="prospect_v1",
        run_id=board.board_id,
        source_key="daily-alpha/outputs/prospect-v1/opportunity-board.html",
    )

    assert result["status"] == "SENT"
    assert result["message_id"] == "prospect-v1-message"
    assert result["recipient_count"] == 1
    assert result["source_key"] == "daily-alpha/outputs/prospect-v1/opportunity-board.html"
    assert len(ses.requests) == 1
    sent_html = ses.requests[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert sent_html == html
    assert f'data-board-id="{board.board_id}"' in sent_html
    assert 'data-total-qualifying="50"' in sent_html
