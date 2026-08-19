"""Strict ORATS daily-bar adapter for research-only Strategy Forensics.

This module reuses the canonical historical ORATS transport already landed on
``main``. It does not create another historical-data client. Daily OHLC evidence
is normalized into point-in-time ``PriceBarObservation`` records at the regular
U.S. equity close, with deterministic source hashing so later forensic results
can be tied back to the exact historical rows used.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from hashlib import sha256
import json
import math
from typing import Any
from zoneinfo import ZoneInfo

from .orats_history_fetch import HistoricalRouter, fetch_daily_earnings_rows
from .orats_history_route import request_with_compatibility_fallback
from .strategy_forensics_observations import (
    DecisionObservation,
    ForensicsPathEvidence,
    PriceBarObservation,
    build_forensics_path,
)

_MARKET_TIMEZONE = ZoneInfo("America/New_York")
_REGULAR_CLOSE = time(hour=16)


@dataclass(frozen=True)
class OratsForensicsBarsEvidence:
    symbol: str
    requested_start: str
    requested_end: str
    source: str
    used_compatibility_fallback: bool
    rows_sha256: str
    bars: tuple[PriceBarObservation, ...]
    market_close_timezone: str = "America/New_York"
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bars"] = [bar.to_dict() for bar in self.bars]
        return payload


def fetch_orats_forensics_bars(
    symbol: str,
    *,
    start: date,
    end: date,
    token: str,
    router: HistoricalRouter = request_with_compatibility_fallback,
) -> OratsForensicsBarsEvidence:
    """Fetch point-in-time daily bars through the existing strict ORATS adapter."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("FORENSICS_ORATS_SYMBOL_REQUIRED")
    if start > end:
        raise ValueError("FORENSICS_ORATS_START_AFTER_END")
    if not token:
        raise ValueError("FORENSICS_ORATS_TOKEN_REQUIRED")

    history = fetch_daily_earnings_rows(
        normalized_symbol,
        warm_start=start,
        end=end,
        token=token,
        router=router,
    )
    selected_rows = tuple(
        row
        for row in history.daily_rows
        if start <= _trade_date(row) <= end
    )
    bars = price_bars_from_orats_daily_rows(
        selected_rows,
        symbol=normalized_symbol,
        source=history.daily_source,
    )
    if not bars:
        raise ValueError("FORENSICS_ORATS_NO_DAILY_BARS")

    return OratsForensicsBarsEvidence(
        symbol=normalized_symbol,
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        source=history.daily_source,
        used_compatibility_fallback=history.daily_used_compatibility_fallback,
        rows_sha256=_rows_sha256(selected_rows, normalized_symbol),
        bars=bars,
    )


def build_forensics_path_from_orats(
    decision: DecisionObservation,
    *,
    evaluation_cutoff: datetime,
    token: str,
    max_bars: int | None = None,
    router: HistoricalRouter = request_with_compatibility_fallback,
) -> tuple[ForensicsPathEvidence, OratsForensicsBarsEvidence]:
    """Build one cutoff-bounded forensic path from strict ORATS daily evidence."""
    if evaluation_cutoff.tzinfo is None or evaluation_cutoff.utcoffset() is None:
        raise ValueError("FORENSICS_CUTOFF_MUST_BE_TIMEZONE_AWARE")
    if evaluation_cutoff <= decision.observed_at:
        raise ValueError("FORENSICS_CUTOFF_MUST_FOLLOW_DECISION")

    market_evidence = fetch_orats_forensics_bars(
        decision.symbol,
        start=decision.observed_at.date(),
        end=evaluation_cutoff.date(),
        token=token,
        router=router,
    )
    path = build_forensics_path(
        decision,
        market_evidence.bars,
        evaluation_cutoff=evaluation_cutoff,
        max_bars=max_bars,
    )
    return path, market_evidence


def price_bars_from_orats_daily_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    source: str,
) -> tuple[PriceBarObservation, ...]:
    """Normalize strict historical daily rows without inventing missing evidence."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("FORENSICS_ORATS_SYMBOL_REQUIRED")
    if not source.strip():
        raise ValueError("FORENSICS_ORATS_SOURCE_REQUIRED")

    bars: list[PriceBarObservation] = []
    observed_dates: set[date] = set()
    for row in rows:
        row_symbol = str(row.get("ticker") or normalized_symbol).strip().upper()
        if row_symbol != normalized_symbol:
            raise ValueError("FORENSICS_ORATS_SYMBOL_MISMATCH")
        row_source = str(row.get("source") or "").strip()
        if row_source != source:
            raise ValueError("FORENSICS_ORATS_SOURCE_MISMATCH")

        trade_date = _trade_date(row)
        if trade_date in observed_dates:
            raise ValueError("FORENSICS_ORATS_DUPLICATE_TRADE_DATE")
        observed_dates.add(trade_date)

        high = _positive_finite(row.get("hiPx"), "FORENSICS_ORATS_HIGH_INVALID")
        low = _positive_finite(row.get("loPx"), "FORENSICS_ORATS_LOW_INVALID")
        close = _positive_finite(row.get("clsPx"), "FORENSICS_ORATS_CLOSE_INVALID")
        if high < low:
            raise ValueError("FORENSICS_ORATS_RANGE_INVALID")
        if not low <= close <= high:
            raise ValueError("FORENSICS_ORATS_CLOSE_OUTSIDE_RANGE")

        bars.append(
            PriceBarObservation(
                observed_at=datetime.combine(
                    trade_date,
                    _REGULAR_CLOSE,
                    tzinfo=_MARKET_TIMEZONE,
                ),
                high=high,
                low=low,
                close=close,
            )
        )

    return tuple(sorted(bars, key=lambda bar: bar.observed_at))


def _rows_sha256(rows: Iterable[Mapping[str, Any]], symbol: str) -> str:
    canonical_rows = []
    for row in rows:
        canonical_rows.append(
            {
                "ticker": str(row.get("ticker") or symbol).strip().upper(),
                "tradeDate": _trade_date(row).isoformat(),
                "hiPx": _positive_finite(row.get("hiPx"), "FORENSICS_ORATS_HIGH_INVALID"),
                "loPx": _positive_finite(row.get("loPx"), "FORENSICS_ORATS_LOW_INVALID"),
                "clsPx": _positive_finite(row.get("clsPx"), "FORENSICS_ORATS_CLOSE_INVALID"),
                "source": str(row.get("source") or "").strip(),
            }
        )
    canonical_rows.sort(key=lambda row: (row["tradeDate"], row["ticker"]))
    encoded = json.dumps(
        canonical_rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _trade_date(row: Mapping[str, Any]) -> date:
    raw = row.get("tradeDate")
    if raw in (None, ""):
        raise ValueError("FORENSICS_ORATS_TRADE_DATE_REQUIRED")
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise ValueError("FORENSICS_ORATS_TRADE_DATE_INVALID") from exc


def _positive_finite(value: Any, message: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(message)
    return number
