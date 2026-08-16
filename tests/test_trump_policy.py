from datetime import UTC, datetime

from daily_alpha.trump_policy import (
    TrumpPolicyCompany,
    build_trump_policy_snapshot,
    rank_trump_policy_companies,
    trump_policy_bonus,
)
from daily_alpha.white_house_policy import (
    _InvestmentTableParser,
    parse_investment_amount,
)


def company(symbol, investment, *, direct=False, affiliated=False):
    return TrumpPolicyCompany(
        rank=0,
        symbol=symbol,
        company=symbol,
        score=80.0,
        investment_usd=investment,
        sector="Technology & AI",
        investment_focus="U.S. manufacturing",
        source_type="WHITE_HOUSE_INVESTMENTS",
        source_url="https://www.whitehouse.gov/investments/",
        direct_trump_mention=direct,
        administration_beneficiary=not affiliated,
        trump_affiliated=affiliated,
    )


def test_amount_parser_handles_billions_and_millions():
    assert parse_investment_amount("$601 Billion") == 601_000_000_000
    assert parse_investment_amount("175 Million") == 175_000_000


def test_table_parser_extracts_white_house_rows():
    parser = _InvestmentTableParser()
    parser.feed(
        "<table><tr><th>Company</th><th>Investment</th><th>Sector</th><th>Investment Focus</th></tr>"
        "<tr><td>Apple</td><td>$600 Billion</td><td>Technology &amp; AI</td>"
        "<td>Manufacturing and training</td></tr></table>"
    )
    assert parser.rows[1] == [
        "Apple",
        "$600 Billion",
        "Technology & AI",
        "Manufacturing and training",
    ]


def test_bonus_is_bounded_and_affiliation_alone_is_neutral():
    apple = company("AAPL", 600_000_000_000, direct=True)
    djt = company("DJT", 0, affiliated=True)
    assert apple.research_bonus == 5.0
    assert djt.research_bonus == 0.0
    assert trump_policy_bonus("AAPL", (apple,)) == 5.0


def test_ranking_is_deterministic_and_snapshot_never_authorizes_trading():
    ranked = rank_trump_policy_companies(
        (
            company("AAPL", 600_000_000_000),
            company("NVDA", 500_000_000_000),
        ),
        limit=2,
    )
    assert [item.symbol for item in ranked] == ["AAPL", "NVDA"]
    assert [item.rank for item in ranked] == [1, 2]
    snapshot = build_trump_policy_snapshot(
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        companies=ranked,
        source_url="https://www.whitehouse.gov/investments/",
    )
    assert snapshot.trading_authorized is False
    assert snapshot.paper_execution_triggered is False
    assert snapshot.live_trading_enabled is False
    assert "not a list of stock recommendations" in snapshot.disclosures[0]
