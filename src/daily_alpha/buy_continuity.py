"""Durable OVTLYR BUY-state continuity derived from immutable dated archives.

This module answers a different question from day-over-day shortlist ranking: how long
has a symbol remained in BUY state, when did it last materially change, and why is
it no longer research-eligible? It never promotes a symbol into execution.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ovtlyr import OvtlyrRecord, load_ovtlyr_csv


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
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_buy_continuity(history_root: str | Path) -> tuple[BuyContinuityState, ...]:
    """Build current BUY continuity from immutable ``YYYY-MM-DD/universe.csv`` runs."""
    root = Path(history_root)
    dated_runs = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and _is_iso_date(path.name) and (path / "universe.csv").is_file()
    )
    if not dated_runs:
        raise ValueError("BUY_CONTINUITY_HISTORY_EMPTY")

    latest_date = dated_runs[-1].name
    first_seen: dict[str, str] = {}
    first_buy: dict[str, str] = {}
    streak_start: dict[str, str | None] = {}
    streak_count: dict[str, int] = {}
    total_buy: dict[str, int] = {}
    last_seen: dict[str, str] = {}
    last_change: dict[str, str] = {}
    last_signature: dict[str, tuple[Any, ...]] = {}
    latest_records: dict[str, OvtlyrRecord] = {}

    for run in dated_runs:
        run_date = run.name
        records = {record.symbol: record for record in load_ovtlyr_csv(run / "universe.csv")}
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

        # A symbol absent from a dated universe breaks an uninterrupted BUY streak.
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
            )
        )

    return tuple(states)


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
    )


def _is_iso_date(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    year, month, day = value.split("-")
    return year.isdigit() and month.isdigit() and day.isdigit()
