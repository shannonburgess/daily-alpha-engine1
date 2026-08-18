"""Run R2 downside study with distribution-aware SGOV reserve accounting.

ORATS daily OHLC bars for SGOV are price-only. This wrapper fetches ORATS dividend
history and credits each SGOV cash distribution only to shares held before the
ex-dividend open. That preserves the actual ETF price path while making the reserve
sleeve economically total-return aware. No synthetic Treasury yield proxy is used.

Research only. Any dividend-fetch/parse failure aborts rather than silently falling
back to price-only SGOV.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import run_r2_downside_overlay as base

ORATS_DIVIDEND_ENDPOINT = "https://api.orats.io/data/hist/divs"
ORATS_RETRY_DELAYS_SECONDS = (0, 2, 5)


def fetch_sgov_dividends(token: str) -> tuple[dict[date, float], str]:
    query = urlencode(
        {
            "tickers": "SGOV",
            "fields[divs]": "ticker,exDate,divAmt,declaredDate",
        }
    )
    request = Request(
        f"{ORATS_DIVIDEND_ENDPOINT}?{query}",
        headers={"Accept": "application/json", "Authorization": token},
    )
    raw: bytes | None = None
    last_error: Exception | None = None
    max_attempts = len(ORATS_RETRY_DELAYS_SECONDS)
    for attempt, delay in enumerate(ORATS_RETRY_DELAYS_SECONDS, start=1):
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
                raise RuntimeError(f"ORATS SGOV dividend HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == max_attempts:
                raise RuntimeError("ORATS SGOV dividend fetch failed after retries") from exc
    if raw is None:
        raise RuntimeError("ORATS SGOV dividend fetch returned no bytes") from last_error

    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("ORATS SGOV dividend response is not valid JSON") from exc
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("ORATS SGOV dividend response has unexpected shape")

    dividends: defaultdict[date, float] = defaultdict(float)
    for row in rows:
        if not isinstance(row, dict) or not row.get("exDate"):
            continue
        ex_date = date.fromisoformat(str(row["exDate"])[:10])
        if ex_date < base.START or ex_date > base.END:
            continue
        amount = float(row.get("divAmt") or 0.0)
        if amount > 0:
            dividends[ex_date] += amount
    if not dividends:
        raise RuntimeError("ORATS returned no positive SGOV distributions in study window")
    return dict(dividends), digest


def simulate_with_sgov_distributions(
    scenario: base.Scenario,
    by_date: dict[str, dict[date, Any]],
    states: dict[str, dict[date, base.SignalState]],
    dates: list[date],
    dividends: dict[date, float],
) -> dict[str, Any]:
    cash = base.INITIAL_NAV
    shares: dict[str, float] = {}
    nav_curve: list[tuple[date, float]] = []
    turnover = 0.0
    contrib: defaultdict[str, float] = defaultdict(float)
    peak_nav = base.INITIAL_NAV
    gross_series: list[float] = []
    net_series: list[float] = []

    for idx, d in enumerate(dates):
        # A holder from the prior close is entitled to the ex-date distribution.
        # Credit it before the opening rebalance; shares bought on the ex-date open
        # do not receive the distribution.
        if idx > 0 and "SGOV" in shares:
            distribution = shares["SGOV"] * dividends.get(d, 0.0)
            if distribution:
                cash += distribution
                contrib["SGOV_DISTRIBUTION"] += distribution

        signal_date = dates[idx - 1] if idx > 0 else None
        decision_idx = idx - 1 if idx > 0 else None
        open_nav = cash + sum(q * by_date[s][d].open for s, q in shares.items())
        peak_nav = max(peak_nav, open_nav)
        targets = base.target_weights(
            scenario,
            signal_date,
            decision_idx,
            states,
            by_date,
            dates,
            open_nav,
            peak_nav,
        )

        all_symbols = set(shares) | set(targets)
        for symbol in sorted(all_symbols):
            px = by_date[symbol][d].open
            current = shares.get(symbol, 0.0) * px
            target = open_nav * targets.get(symbol, 0.0)
            trade = target - current
            if abs(trade) < 1e-6:
                continue
            kind = base.classify_asset(symbol, targets.get(symbol, 0.0))
            cost = abs(trade) * base.COST_BPS[kind] / 10_000.0
            cash -= trade + cost
            contrib[f"{kind}_COST"] -= cost
            turnover += abs(trade)
            new_q = target / px
            if abs(new_q) < 1e-12:
                shares.pop(symbol, None)
            else:
                shares[symbol] = new_q

        close_nav = cash + sum(q * by_date[s][d].close for s, q in shares.items())
        for symbol, q in shares.items():
            fallback_weight = q * by_date[symbol][d].open / open_nav if open_nav else 0.0
            kind = base.classify_asset(symbol, targets.get(symbol, fallback_weight))
            contrib[kind] += q * (by_date[symbol][d].close - by_date[symbol][d].open)

        gross_series.append(sum(abs(w) for s, w in targets.items() if s != "SGOV"))
        net_series.append(sum(w for s, w in targets.items() if s != "SGOV"))
        nav_curve.append((d, close_nav))
        peak_nav = max(peak_nav, close_nav)

    return base.summarize(
        nav_curve,
        gross_series,
        net_series,
        turnover,
        contrib,
        by_date,
    )


def main() -> None:
    token = os.environ.get("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")
    dividends, digest = fetch_sgov_dividends(token)
    original_simulate = base.simulate

    def patched_simulate(scenario, by_date, states, dates):
        return simulate_with_sgov_distributions(
            scenario,
            by_date,
            states,
            dates,
            dividends,
        )

    base.simulate = patched_simulate
    try:
        base.main()
    finally:
        base.simulate = original_simulate

    path = Path("r2-downside-overlay.json")
    payload = json.loads(path.read_text())
    payload["methodology"]["treasury_reserve"] = {
        "vehicle": "SGOV",
        "return_basis": "ORATS price OHLC plus actual ORATS cash distributions",
        "distribution_endpoint": ORATS_DIVIDEND_ENDPOINT,
        "distribution_source_sha256": digest,
        "distribution_count": len(dividends),
        "taxes": "excluded",
        "fail_closed": True,
        "note": "Expense ratio is already reflected in SGOV NAV/price; distributions are credited only to prior-close holders.",
    }
    path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
