"""Run R2 downside study with a distribution-aware Treasury reserve proxy.

ORATS daily SGOV OHLC is price-only, while the current ORATS entitlement returns
HTTP 403 for historical SGOV dividend data. Rather than understate reserve return
or invent distributions, this research wrapper replaces the SGOV price path with
a transparent 3-month U.S. Treasury carry proxy sourced from FRED DGS3MO, less the
current 0.09% SGOV expense ratio.

The proxy is deliberately conservative and is not exact SGOV shareholder total
return. It uses only the latest Treasury yield observation strictly before each
trading date, hashes the downloaded source, and aborts on fetch/parse/coverage
failure. Research only; no execution path imports this module.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import run_r2_downside_overlay as base
from daily_alpha.backtest import Bar

FRED_DGS3MO_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
FRED_RETRY_DELAYS_SECONDS = (0, 2, 5)
SGOV_EXPENSE_RATIO = 0.0009


def fetch_treasury_yields() -> tuple[dict[date, float], str]:
    request = Request(
        FRED_DGS3MO_CSV,
        headers={
            "Accept": "text/csv",
            "User-Agent": "DailyAlphaResearch/0.1 (+research-only)",
        },
    )
    raw: bytes | None = None
    last_error: Exception | None = None
    max_attempts = len(FRED_RETRY_DELAYS_SECONDS)
    for attempt, delay in enumerate(FRED_RETRY_DELAYS_SECONDS, start=1):
        if delay:
            time.sleep(delay)
        try:
            with urlopen(request, timeout=45) as response:
                raw = response.read()
            break
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt == max_attempts:
                raise RuntimeError(f"FRED DGS3MO HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == max_attempts:
                raise RuntimeError("FRED DGS3MO fetch failed after retries") from exc
    if raw is None:
        raise RuntimeError("FRED DGS3MO fetch returned no bytes") from last_error

    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError("FRED DGS3MO response is not UTF-8 CSV") from exc

    rows = csv.DictReader(io.StringIO(text))
    if rows.fieldnames is None or "DGS3MO" not in rows.fieldnames:
        raise TypeError("FRED DGS3MO response has unexpected CSV columns")

    yields: dict[date, float] = {}
    for row in rows:
        raw_date = row.get("observation_date") or row.get("DATE")
        raw_yield = row.get("DGS3MO")
        if not raw_date or raw_yield in (None, "", "."):
            continue
        try:
            d = date.fromisoformat(raw_date[:10])
            rate = float(raw_yield)
        except (ValueError, TypeError):
            continue
        if d <= base.END and rate >= 0:
            yields[d] = rate

    if not yields:
        raise RuntimeError("FRED returned no usable DGS3MO observations")
    if min(yields) > base.START:
        raise RuntimeError("FRED DGS3MO history does not cover study start")
    if max(yields) < base.END.replace(day=max(1, base.END.day - 10)):
        raise RuntimeError("FRED DGS3MO history is stale for study end")
    return yields, digest


def treasury_proxy_bars(
    dates: list[date], yields: dict[date, float]
) -> dict[date, Bar]:
    ordered_obs = sorted(yields)
    obs_idx = 0
    latest_rate: float | None = None
    value = 100.0
    previous_date: date | None = None
    out: dict[date, Bar] = {}

    for d in dates:
        # Strictly prior observation prevents same-day release timing from leaking
        # into a return already accruing during that trading session.
        while obs_idx < len(ordered_obs) and ordered_obs[obs_idx] < d:
            latest_rate = yields[ordered_obs[obs_idx]]
            obs_idx += 1
        if latest_rate is None:
            raise RuntimeError(f"No prior DGS3MO observation available for {d}")

        open_value = value
        calendar_days = 1 if previous_date is None else max(1, (d - previous_date).days)
        net_annual_yield = max(0.0, latest_rate / 100.0 - SGOV_EXPENSE_RATIO)
        value = open_value * (1.0 + net_annual_yield * calendar_days / 365.0)
        out[d] = Bar(
            trade_date=d,
            open=open_value,
            high=max(open_value, value),
            low=min(open_value, value),
            close=value,
            volume=0.0,
            earnings_event=False,
        )
        previous_date = d
    return out


def main() -> None:
    yields, digest = fetch_treasury_yields()
    original_simulate = base.simulate

    def patched_simulate(
        scenario: base.Scenario,
        by_date: dict[str, dict[date, Any]],
        states: dict[str, dict[date, base.SignalState]],
        dates: list[date],
    ) -> dict[str, Any]:
        if not scenario.use_sgov:
            return original_simulate(scenario, by_date, states, dates)
        patched = dict(by_date)
        patched["SGOV"] = treasury_proxy_bars(dates, yields)
        return original_simulate(scenario, patched, states, dates)

    base.simulate = patched_simulate
    try:
        base.main()
    finally:
        base.simulate = original_simulate

    path = Path("r2-downside-overlay.json")
    payload = json.loads(path.read_text())
    payload["methodology"]["treasury_reserve"] = {
        "intended_vehicle": "SGOV",
        "research_return_proxy": "FRED DGS3MO carry less 0.09% annual expense ratio",
        "fred_series": "DGS3MO",
        "source_url": FRED_DGS3MO_CSV,
        "source_sha256": digest,
        "expense_ratio": SGOV_EXPENSE_RATIO,
        "timing": "latest yield observation strictly before each trading date",
        "taxes": "excluded",
        "fail_closed": True,
        "exact_sgov_total_return": False,
        "note": (
            "Current ORATS entitlement returns HTTP 403 for historical SGOV dividends. "
            "This proxy avoids price-only SGOV understatement but must be replaced by "
            "distribution-adjusted or broker-grade SGOV total return before promotion."
        ),
    }
    path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
