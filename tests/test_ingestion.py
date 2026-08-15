from pathlib import Path

from daily_alpha.ingestion import load_universe


def test_load_universe_accepts_common_column_aliases(tmp_path: Path):
    csv_path = tmp_path / "universe.csv"
    csv_path.write_text(
        "Ticker,Status,Overlay Start Date,Sector\n"
        "rdw,Buy,2026-08-10,Industrials\n",
        encoding="utf-8",
    )

    records = load_universe(csv_path)

    assert len(records) == 1
    assert records[0].symbol == "RDW"
    assert records[0].signal == "BUY"
    assert records[0].sector == "Industrials"
