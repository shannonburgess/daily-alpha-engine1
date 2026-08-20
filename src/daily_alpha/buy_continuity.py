"""Durable OVTLYR BUY-state continuity aligned to the canonical liquidity gate.

This research/newsletter model answers how long a symbol has remained in BUY state
and why it is or is not currently eligible for the actionable research shortlist.
It never authorizes execution.  Current ACTIVE_BUY eligibility can be bound to the
same immutable company-liquidity evidence used by issue #218, while ETFs retain
their separate liquidity/capacity path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .equity_liquidity import CANONICAL_COMPANY_MIN_AVERAGE_VOLUME
from .ovtlyr import OvtlyrRecord, load_ovtlyr_csv

_DATE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})")


@dataclass(frozen=True)
class BuyContinuityState:
    symbol: str
    first_seen_date: str
    first_buy_date: str | None
    current_buy_streak_start: str | None
    consecutive_buy_observations: int
    total_buy_observations: int
    last_seen_date: str
    last_meaningful_change_date: str
    current_signal: str
    active_buy: bool
    research_eligibility: str
    trend: str
    momentum: str
    sector: str
    industry: str
    optionable: bool | None
    partial_data: bool
    average_volume: float | None
    security_type: str = "UNKNOWN"
    liquidity_status: str = "NOT_EVALUATED"
    liquidity_detail: str = ""
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_buy_continuity(history_root: str | Path) -> tuple[BuyContinuityState, ...]:
    """Build continuity from immutable ``YYYY-MM-DD/universe.csv`` archive runs."""
    root = Path(history_root)
    dated_runs = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and _is_iso_date(path.name) and (path / "universe.csv").is_file()
    )
    if not dated_runs:
        raise ValueError("BUY_CONTINUITY_HISTORY_EMPTY")
    observations = [
        (run.name, tuple(load_ovtlyr_csv(run / "universe.csv"))) for run in dated_runs
    ]
    return _build_buy_continuity(observations)


def build_buy_continuity_from_csv_directory(
    csv_root: str | Path,
) -> tuple[BuyContinuityState, ...]:
    """Build continuity from flat dated OVTLYR CSVs downloaded for a shortlist run.

    Dates come from filenames, never filesystem modification times.  Duplicate date
    labels fail closed because chronology would otherwise be ambiguous.
    """
    root = Path(csv_root)
    dated_files: list[tuple[str, Path]] = []
    for path in root.glob("*.csv"):
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        match = _DATE_PATTERN.search(path.name)
        if match:
            dated_files.append((match.group(1), path))
    dated_files.sort(key=lambda item: (item[0], item[1].name))
    if not dated_files:
        raise ValueError("BUY_CONTINUITY_HISTORY_EMPTY")

    dates = [date for date, _ in dated_files]
    if len(dates) != len(set(dates)):
        raise ValueError("BUY_CONTINUITY_DUPLICATE_DATE")

    observations = [
        (date, tuple(load_ovtlyr_csv(path))) for date, path in dated_files
    ]
    return _build_buy_continuity(observations)


def apply_liquidity_snapshot(
    states: tuple[BuyContinuityState, ...],
    snapshot: Mapping[str, Any],
    *,
    expected_source_file: str,
) -> tuple[BuyContinuityState, ...]:
    """Bind ACTIVE_BUY research eligibility to issue #218's exact evidence contract.

    Company equities must be strictly above 1.5M 30-day average daily shares.  ETF
    rows are tagged ``ETF_SEPARATE_RULES`` and retain their pre-existing research
    eligibility.  Missing, duplicated, malformed, stale-contract, or unsafe evidence
    fails closed for an ACTIVE_BUY company rather than silently preserving eligibility.
    """
    if snapshot.get("trading_authorized") is not False:
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_SAFETY_FLAGS_INVALID")
    if snapshot.get("live_trading_enabled") is not False:
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_SAFETY_FLAGS_INVALID")
    if snapshot.get("company_threshold_semantics") != "STRICTLY_GREATER_THAN":
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_THRESHOLD_SEMANTICS_INVALID")
    try:
        threshold = float(snapshot.get("company_min_average_volume"))
    except (TypeError, ValueError) as exc:
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_THRESHOLD_INVALID") from exc
    if threshold != CANONICAL_COMPANY_MIN_AVERAGE_VOLUME:
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_THRESHOLD_CONTRACT_MISMATCH")
    if str(snapshot.get("source_file") or "") != expected_source_file:
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_SOURCE_MISMATCH")

    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("BUY_CONTINUITY_LIQUIDITY_ROWS_MISSING")
    by_symbol: dict[str, Mapping[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("BUY_CONTINUITY_LIQUIDITY_ROW_INVALID")
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("BUY_CONTINUITY_LIQUIDITY_SYMBOL_MISSING")
        if symbol in by_symbol:
            raise ValueError("BUY_CONTINUITY_LIQUIDITY_DUPLICATE_SYMBOL")
        by_symbol[symbol] = raw

    reconciled: list[BuyContinuityState] = []
    for state in states:
        if not state.active_buy:
            reconciled.append(state)
            continue

        row = by_symbol.get(state.symbol.upper())
        if row is None:
            reconciled.append(
                replace(
                    state,
                    research_eligibility="ACTIVE_BUY_LIQUIDITY_FILTERED",
                    security_type="UNKNOWN",
                    liquidity_status="LIQUIDITY_FILTERED",
                    liquidity_detail="LIQUIDITY_SYMBOL_EVIDENCE_MISSING",
                )
            )
            continue

        security_type = str(row.get("security_type") or "UNKNOWN").upper()
        status = str(row.get("status") or "LIQUIDITY_FILTERED").upper()
        detail = str(row.get("detail") or "")
        volume = _nonnegative_float_or_none(row.get("average_daily_share_volume_30d"))

        if security_type == "ETF":
            reconciled.append(
                replace(
                    state,
                    security_type=security_type,
                    liquidity_status="ETF_SEPARATE_RULES",
                    liquidity_detail="COMPANY_SHARE_VOLUME_GATE_NOT_APPLIED",
                )
            )
            continue

        company_pass = (
            security_type == "COMPANY_EQUITY"
            and status == "ELIGIBLE"
            and volume is not None
            and volume > threshold
        )
        if not company_pass:
            reconciled.append(
                replace(
                    state,
                    research_eligibility="ACTIVE_BUY_LIQUIDITY_FILTERED",
                    security_type=security_type,
                    liquidity_status="LIQUIDITY_FILTERED",
                    liquidity_detail=detail or "AT_OR_BELOW_OR_MISSING_VOLUME",
                )
            )
            continue

        reconciled.append(
            replace(
                state,
                security_type=security_type,
                liquidity_status="ELIGIBLE",
                liquidity_detail="COMPANY_VOLUME_STRICTLY_ABOVE_1_5M",
            )
        )

    return tuple(reconciled)


def write_buy_continuity_output(
    output_path: str | Path,
    states: tuple[BuyContinuityState, ...],
) -> Path:
    """Write one deterministic machine-readable continuity artifact."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    active = [state for state in states if state.active_buy]
    payload = {
        "summary": {
            "symbols": len(states),
            "active_buy": len(active),
            "eligible_active_buy": sum(
                state.research_eligibility == "ACTIVE_BUY_ELIGIBLE" for state in active
            ),
            "liquidity_filtered_active_buy": sum(
                state.research_eligibility == "ACTIVE_BUY_LIQUIDITY_FILTERED"
                for state in active
            ),
            "etf_active_buy": sum(
                state.liquidity_status == "ETF_SEPARATE_RULES" for state in active
            ),
            "company_min_average_volume": CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
            "company_threshold_semantics": "STRICTLY_GREATER_THAN",
            "research_only": True,
            "trading_authorized": False,
            "live_trading_enabled": False,
        },
        "states": [state.to_dict() for state in states],
    }
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _build_buy_continuity(
    observations: list[tuple[str, tuple[OvtlyrRecord, ...]]],
) -> tuple[BuyContinuityState, ...]:
    if not observations:
        raise ValueError("BUY_CONTINUITY_HISTORY_EMPTY")
    observations.sort(key=lambda item: item[0])
    dates = [date for date, _ in observations]
    if len(dates) != len(set(dates)):
        raise ValueError("BUY_CONTINUITY_DUPLICATE_DATE")

    latest_date = observations[-1][0]
    first_seen: dict[str, str] = {}
    first_buy: dict[str, str] = {}
    streak_start: dict[str, str | None] = {}
    streak_count: dict[str, int] = {}
    total_buy: dict[str, int] = {}
    last_seen: dict[str, str] = {}
    last_change: dict[str, str] = {}
    last_signature: dict[str, tuple[Any, ...]] = {}
    latest_records: dict[str, OvtlyrRecord] = {}

    for run_date, run_records in observations:
        records = {record.symbol: record for record in run_records}
        for symbol, record in records.items():
            first_seen.setdefault(symbol, run_date)
            last_seen[symbol] = run_date
            signature = _meaningful_signature(record)
            if symbol not in last_signature or signature != last_signature[symbol]:
                last_change[symbol] = run_date
                last_signature[symbol] = signature

            if record.signal == "BUY":
                first_buy.setdefault(symbol, run_date)
                total_buy[symbol] = total_buy.get(symbol, 0) + 1
                if streak_count.get(symbol, 0) == 0:
                    streak_start[symbol] = run_date
                streak_count[symbol] = streak_count.get(symbol, 0) + 1
            else:
                streak_start[symbol] = None
                streak_count[symbol] = 0

        for symbol in set(streak_count) - set(records):
            streak_start[symbol] = None
            streak_count[symbol] = 0

        if run_date == latest_date:
            latest_records = records

    states: list[BuyContinuityState] = []
    for symbol in sorted(first_seen):
        current = latest_records.get(symbol)
        if current is None:
            states.append(
                BuyContinuityState(
                    symbol=symbol,
                    first_seen_date=first_seen[symbol],
                    first_buy_date=first_buy.get(symbol),
                    current_buy_streak_start=None,
                    consecutive_buy_observations=0,
                    total_buy_observations=total_buy.get(symbol, 0),
                    last_seen_date=last_seen[symbol],
                    last_meaningful_change_date=last_change[symbol],
                    current_signal="MISSING",
                    active_buy=False,
                    research_eligibility="SYMBOL_MISSING_FROM_CURRENT_UNIVERSE",
                    trend="",
                    momentum="",
                    sector="Unknown",
                    industry="",
                    optionable=None,
                    partial_data=False,
                    average_volume=None,
                )
            )
            continue

        active_buy = current.signal == "BUY"
        states.append(
            BuyContinuityState(
                symbol=symbol,
                first_seen_date=first_seen[symbol],
                first_buy_date=first_buy.get(symbol),
                current_buy_streak_start=streak_start.get(symbol) if active_buy else None,
                consecutive_buy_observations=streak_count.get(symbol, 0) if active_buy else 0,
                total_buy_observations=total_buy.get(symbol, 0),
                last_seen_date=last_seen[symbol],
                last_meaningful_change_date=last_change[symbol],
                current_signal=current.signal,
                active_buy=active_buy,
                research_eligibility=_eligibility(current),
                trend=current.trend,
                momentum=current.momentum,
                sector=current.sector,
                industry=current.industry,
                optionable=current.optionable,
                partial_data=current.partial_data,
                average_volume=current.average_volume,
            )
        )

    return tuple(states)


def _eligibility(record: OvtlyrRecord) -> str:
    if record.signal != "BUY":
        return "SIGNAL_NO_LONGER_BUY"
    if record.partial_data:
        return "ACTIVE_BUY_PARTIAL_DATA"
    if record.optionable is False:
        return "ACTIVE_BUY_NOT_OPTIONABLE"
    return "ACTIVE_BUY_ELIGIBLE"


def _meaningful_signature(record: OvtlyrRecord) -> tuple[Any, ...]:
    return (
        record.signal,
        record.trend,
        record.momentum,
        record.sector,
        record.industry,
        record.optionable,
        record.partial_data,
        record.average_volume,
    )


def _nonnegative_float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _is_iso_date(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    year, month, day = value.split("-")
    return year.isdigit() and month.isdigit() and day.isdigit()
