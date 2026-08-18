"""Run the R2 downside study with an economic total-return proxy for SGOV reserve.

ORATS OHLC bars for SGOV do not credit cash distributions, so a price-only ETF
series materially understates the treasury-reserve sleeve. For this research-only
phase we replace SGOV price bars with a synthetic 0-3 month Treasury reserve index
using the Federal Reserve DGS3MO yield series less SGOV's stated 0.09% annual
expense ratio. This is a conservative carry approximation, not an exact SGOV
shareholder total-return reconstruction.

The fetched FRED observation set is hashed into the output for provenance. Any
fetch/parse/data-gap failure aborts the study rather than silently reverting to
price-only SGOV.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import run_r2_downside_overlay as base

from daily_alpha.backtest import Bar

FRED_DGS3MO_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
SGOV_EXPENSE_RATIO = 0.0009


def fetch_dgs3mo() -> tuple[dict[date, float], str]:
    request = Request(FRED_DGS3MO_CSV, headers={"User-Agent": "DailyAlphaResearch/1.0"})
    with urlopen(request, timeout=45) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    rows = csv.DictReader(io.StringIO(text))
    out: dict[date, float] = {}
    for row in rows:
        raw_date = row.get("DATE") or row.get("observation_date")
        raw_yield = row.get("DGS3MO")
        if not raw_date or raw_yield in (None, "", "."):
            continue
        out[date.fromisoformat(raw_date[:10])] = float(raw_yield)
    if not out:
        raise RuntimeError("FRED DGS3MO returned no usable observations")
    return out, digest


def treasury_reserve_bars(template: list[Bar], yields: dict[date, float]) -> list[Bar]:
    if not template:
        raise RuntimeError("SGOV template history is empty")
    known_dates = sorted(yields)
    cursor = 0
    current_yield: float | None = None
    level = 100.0
    out: list[Bar] = []
    previous_date: date | None = None

    for original in sorted(template, key=lambda b: b.trade_date):
        d = original.trade_date
        while cursor < len(known_dates) and known_dates[cursor] <= d:
            current_yield = yields[known_dates[cursor]]
            cursor += 1
        if current_yield is None:
            continue
        calendar_days = max(1, (d - previous_date).days) if previous_date else 1
        annual_net = max(current_yield / 100.0 - SGOV_EXPENSE_RATIO, 0.0)
        growth = (1.0 + annual_net) ** (calendar_days / 365.25)
        opn = level
        close = level * growth
        out.append(
            Bar(
                trade_date=d,
                open=opn,
                high=max(opn, close),
                low=min(opn, close),
                close=close,
                volume=original.volume,
                earnings_event=False,
            )
        )
        level = close
        previous_date = d

    if len(out) < 750:
        raise RuntimeError(f"Only {len(out)} treasury-reserve proxy bars available")
    return out


def main() -> None:
    original_fetch_all = base.fetch_all
    dgs3mo, digest = fetch_dgs3mo()

    def patched_fetch_all(token: str):
        data, failures = original_fetch_all(token)
        if "SGOV" not in data:
            raise RuntimeError("SGOV template history unavailable for reserve proxy")
        data["SGOV"] = treasury_reserve_bars(data["SGOV"], dgs3mo)
        return data, failures

    base.fetch_all = patched_fetch_all
    base.main()

    path = Path("r2-downside-overlay.json")
    payload = json.loads(path.read_text())
    payload["methodology"]["treasury_reserve"] = {
        "vehicle_label": "SGOV",
        "research_return_model": "DGS3MO daily carry less 0.09% annual expense ratio",
        "exact_sgov_total_return": False,
        "fred_series": "DGS3MO",
        "source_url": FRED_DGS3MO_CSV,
        "source_sha256": digest,
        "fail_closed": True,
        "note": "Promotion requires exact distribution-adjusted SGOV total-return evidence or broker-grade reserve accounting.",
    }
    path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
