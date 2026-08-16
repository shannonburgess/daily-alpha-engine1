from daily_alpha.smart_money_sources import (
    load_sec_13f_directory,
    parse_amount_range,
    parse_congressional_trade,
)


def test_parse_amount_range_preserves_disclosure_band():
    assert parse_amount_range("$1,001 - $15,000") == (1001.0, 15000.0)
    assert parse_amount_range("Over $50,000,000") == (50_000_000.0, None)


def test_parse_congressional_trade_normalizes_purchase():
    trade = parse_congressional_trade(
        {
            "member": "Jane Doe",
            "chamber": "senate",
            "ticker": "nvda",
            "asset": "NVIDIA Corporation",
            "trade_type": "buy",
            "amount": "$15,001 - $50,000",
            "tx_date": "2026-07-28",
            "disclosed": "2026-08-10",
            "link": "https://example.test/filing",
        }
    )
    assert trade is not None
    assert trade.symbol == "NVDA"
    assert trade.chamber == "Senate"
    assert trade.amount_low == 15001
    assert trade.amount_high == 50000


def test_sec_13f_loader_uses_initial_long_share_holdings(tmp_path):
    (tmp_path / "SUBMISSION.tsv").write_text(
        "ACCESSION_NUMBER\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
        "A1\t13F-HR\t0000000001\t30-JUN-2026\n"
        "A2\t13F-HR/A\t0000000001\t30-JUN-2026\n",
        encoding="utf-8",
    )
    (tmp_path / "COVERPAGE.tsv").write_text(
        "ACCESSION_NUMBER\tFILINGMANAGER_NAME\nA1\tManager One\nA2\tManager One\n",
        encoding="utf-8",
    )
    (tmp_path / "INFOTABLE.tsv").write_text(
        "ACCESSION_NUMBER\tNAMEOFISSUER\tCUSIP\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\n"
        "A1\tAlpha Corp\t123456789\t100000\t1000\tSH\t\n"
        "A1\tOption Corp\t999999999\t50000\t100\tSH\tPUT\n"
        "A2\tAmended Corp\t888888888\t30000\t100\tSH\t\n",
        encoding="utf-8",
    )
    holdings = load_sec_13f_directory(tmp_path, symbol_map={"123456789": "AAA"})
    assert len(holdings) == 1
    item = holdings[0]
    assert item.manager_cik == "1"
    assert item.manager_name == "Manager One"
    assert item.symbol == "AAA"
    assert item.shares == 1000
