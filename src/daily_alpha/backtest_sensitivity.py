"""Source-neutral close-location sensitivity helpers for the earnings Gap & Go sleeve."""

from __future__ import annotations

from typing import Any


def reclassify_gap_go(
    bars: list[Any], rows: list[dict[str, Any]], *, close_location: float
) -> list[dict[str, Any]]:
    """Reclassify supplied point-in-time rows under an explicit research threshold."""
    adjusted: list[dict[str, Any]] = []
    for bar, original in zip(bars, rows, strict=True):
        row = dict(original)
        upper20 = row.get("upper20")
        earnings_breakout = upper20 is not None and bar.close > float(upper20)
        rsi = row.get("rsi")
        gap_go = bool(
            row.get("is_earnings_up_gap")
            and bar.close >= bar.open
            and float(row.get("close_location", 0.0)) >= close_location
            and float(row.get("gap_retention", 0.0)) >= 0.70
            and float(row.get("relative_volume", 0.0)) >= 1.50
            and rsi is not None
            and float(rsi) <= 85.0
            and int(row.get("trend_state", 0)) == 1
            and earnings_breakout
        )
        gap_crap = False
        if row.get("is_earnings_up_gap") and not gap_go:
            gap_dollars = float(row.get("gap_dollars", 0.0))
            retention = float(row.get("gap_retention", 0.0))
            previous_close = (
                bar.close - retention * gap_dollars if gap_dollars > 0 else bar.close
            )
            gap_crap = bool(
                bar.close < previous_close
                or retention < 0.50
                or (
                    bar.close < bar.open
                    and float(row.get("close_location", 0.0)) < 0.50
                )
            )
        row["gap_go"] = gap_go
        row["gap_go_early"] = bool(
            row.get("is_earnings_up_gap")
            and not gap_go
            and float(row.get("close_location", 0.0)) >= 0.60
        )
        row["gap_crap"] = gap_crap
        row["gap_wait"] = bool(
            row.get("is_earnings_up_gap") and not gap_go and not gap_crap
        )
        adjusted.append(row)
    return adjusted
