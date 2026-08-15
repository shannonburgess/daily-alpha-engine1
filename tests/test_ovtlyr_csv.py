import json

from daily_alpha.ovtlyr import compare_universes, load_ovtlyr_csv
from daily_alpha.ovtlyr_report import write_comparison_outputs


def test_csv_aliases_and_output_files(tmp_path):
    previous = tmp_path / "previous.csv"
    current = tmp_path / "current.csv"
    previous.write_text(
        "Ticker,Status,Overlay Start Date,Sector,Options Available\n"
        "AAA,Buy,2026-08-14,Technology,Yes\n",
        encoding="utf-8",
    )
    current.write_text(
        "Ticker,Status,Overlay Start Date,Sector,Options Available,Trend,Momentum\n"
        "AAA,Buy,2026-08-14,Technology,Yes,Up,Strong\n"
        "BBB,Buy,2026-08-15,Industrials,No,Up,Accelerating\n",
        encoding="utf-8",
    )

    classified = compare_universes(
        load_ovtlyr_csv(previous),
        load_ovtlyr_csv(current),
    )
    outputs = write_comparison_outputs(tmp_path / "out", classified, [])

    data = json.loads(outputs["comparison_json"].read_text(encoding="utf-8"))
    assert {item["symbol"] for item in data} == {"AAA", "BBB"}
    assert next(item for item in data if item["symbol"] == "BBB")["optionable"] is False
    assert outputs["comparison_csv"].exists()


def test_loads_real_ovtlyr_export_headers(tmp_path):
    source = tmp_path / "ovtlyr.csv"
    source.write_text(
        "Symbol,Sector/Index,Current Signal Status,Signal Start Date,Overlay,"
        "Fear & Greed Heatmap Direction\n"
        "AAA,Technology,Buy,Aug 14 2026,Uptrend,Moving Up\n",
        encoding="utf-8",
    )

    record = load_ovtlyr_csv(source)[0]

    assert record.symbol == "AAA"
    assert record.signal == "BUY"
    assert record.signal_date == "Aug 14 2026"
    assert record.sector == "Technology"
    assert record.trend == "UPTREND"
    assert record.momentum == "MOVING UP"
