"""Deterministic day-over-day classification for OVTLYR universe exports."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class OvtlyrStatus(StrEnum):
    NEW_BUY = "NEW_BUY"
    EMERGING = "EMERGING"
    LEADER = "LEADER"
    ENTRY_WATCH = "ENTRY_WATCH"
    RE_ENTRY = "RE_ENTRY"
    DETERIORATING = "DETERIORATING"
    REMOVED = "REMOVED"
    ACTIVE_BUY = "ACTIVE_BUY"
    UNCHANGED = "UNCHANGED"


DISPLAY_LABELS = {
    OvtlyrStatus.NEW_BUY: "NEW BUY",
    OvtlyrStatus.EMERGING: "🔥 EMERGING",
    OvtlyrStatus.LEADER: "🚀 LEADER",
    OvtlyrStatus.ENTRY_WATCH: "🎯 ENTRY WATCH",
    OvtlyrStatus.RE_ENTRY: "♻️ RE-ENTRY",
    OvtlyrStatus.DETERIORATING: "⚠️ DETERIORATING",
    OvtlyrStatus.REMOVED: "❌ REMOVED",
    OvtlyrStatus.ACTIVE_BUY: "ACTIVE BUY",
    OvtlyrStatus.UNCHANGED: "UNCHANGED",
}


@dataclass(frozen=True)
class OvtlyrRecord:
    symbol: str
    signal: str
    signal_date: str = ""
    sector: str = "Unknown"
    industry: str = ""
    trend: str = ""
    momentum: str = ""
    setup: str = ""
    entry_watch: bool = False
    optionable: bool | None = None


@dataclass(frozen=True)
class ClassifiedRecord:
    symbol: str
    status: OvtlyrStatus
    display_label: str
    signal: str
    previous_signal: str
    signal_date: str
    sector: str
    industry: str
    trend: str
    momentum: str
    optionable: bool | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class SectorRotation:
    sector: str
    current_buys: int
    advancing: int
    leaders: int
    deteriorating: int
    removed: int
    net_score: int


def load_ovtlyr_csv(path: str | Path) -> list[OvtlyrRecord]:
    """Load a flexible OVTLYR CSV while retaining explicit classification inputs."""
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        columns = {_normalize(name): name for name in reader.fieldnames}

        records = []
        for row in reader:
            symbol = _value(row, columns, "symbol", "ticker").upper()
            if not symbol:
                continue
            records.append(
                OvtlyrRecord(
                    symbol=symbol,
                    signal=_value(
                        row,
                        columns,
                        "signal",
                        "status",
                        "rating",
                        "current_signal_status",
                    ).upper(),
                    signal_date=_value(
                        row,
                        columns,
                        "signal_date",
                        "date",
                        "signal_start_date",
                        "overlay_start_date",
                    ),
                    sector=_value(row, columns, "sector", "sector_index")
                    or "Unknown",
                    industry=_value(row, columns, "industry"),
                    trend=_value(
                        row,
                        columns,
                        "trend",
                        "trend_direction",
                        "overlay",
                    ).upper(),
                    momentum=_value(
                        row,
                        columns,
                        "momentum",
                        "momentum_direction",
                        "fear_and_greed_heatmap_direction",
                        "fear_greed_heatmap_direction",
                    ).upper(),
                    setup=_value(row, columns, "setup", "setup_type").upper(),
                    entry_watch=_boolean(
                        _value(
                            row,
                            columns,
                            "entry_watch",
                            "near_10_20",
                            "near_pine_entry",
                        )
                    )
                    is True,
                    optionable=_boolean(
                        _value(
                            row,
                            columns,
                            "optionable",
                            "options_available",
                            "has_options",
                        )
                    ),
                )
            )
    if not records:
        raise ValueError("CSV contains no usable symbol rows")
    return records


def compare_universes(
    previous: list[OvtlyrRecord],
    current: list[OvtlyrRecord],
) -> list[ClassifiedRecord]:
    """Assign one primary status to every current or previously active symbol."""
    before = {record.symbol: record for record in previous}
    now = {record.symbol: record for record in current}
    results = []

    for symbol in sorted(before.keys() | now.keys()):
        old = before.get(symbol)
        new = now.get(symbol)
        status, reason = _classify(old, new)
        source = new or old
        assert source is not None
        results.append(
            ClassifiedRecord(
                symbol=symbol,
                status=status,
                display_label=DISPLAY_LABELS[status],
                signal=new.signal if new else "",
                previous_signal=old.signal if old else "",
                signal_date=new.signal_date if new else old.signal_date,
                sector=source.sector,
                industry=source.industry,
                trend=new.trend if new else "",
                momentum=new.momentum if new else "",
                optionable=new.optionable if new else old.optionable,
                reason=reason,
            )
        )
    return results


def summarize_sector_rotation(
    classified: list[ClassifiedRecord],
) -> list[SectorRotation]:
    buckets: dict[str, dict[str, int]] = {}
    advancing_statuses = {
        OvtlyrStatus.NEW_BUY,
        OvtlyrStatus.EMERGING,
        OvtlyrStatus.RE_ENTRY,
        OvtlyrStatus.ENTRY_WATCH,
    }
    for item in classified:
        bucket = buckets.setdefault(
            item.sector or "Unknown",
            {
                "current_buys": 0,
                "advancing": 0,
                "leaders": 0,
                "deteriorating": 0,
                "removed": 0,
            },
        )
        if item.signal == "BUY":
            bucket["current_buys"] += 1
        if item.status in advancing_statuses:
            bucket["advancing"] += 1
        if item.status == OvtlyrStatus.LEADER:
            bucket["leaders"] += 1
        if item.status == OvtlyrStatus.DETERIORATING:
            bucket["deteriorating"] += 1
        if item.status == OvtlyrStatus.REMOVED:
            bucket["removed"] += 1

    summary = []
    for sector, counts in buckets.items():
        net_score = (
            2 * counts["advancing"]
            + counts["leaders"]
            - 2 * counts["deteriorating"]
            - 2 * counts["removed"]
        )
        summary.append(SectorRotation(sector=sector, net_score=net_score, **counts))
    return sorted(summary, key=lambda item: (-item.net_score, item.sector))


def _classify(
    old: OvtlyrRecord | None,
    new: OvtlyrRecord | None,
) -> tuple[OvtlyrStatus, str]:
    was_buy = old is not None and old.signal == "BUY"
    is_buy = new is not None and new.signal == "BUY"

    if was_buy and not is_buy:
        return OvtlyrStatus.REMOVED, "Prior BUY is missing or no longer rated BUY"
    if new is None:
        return OvtlyrStatus.UNCHANGED, "Previously inactive symbol is absent"

    momentum = new.momentum
    trend_up = new.trend in {"UP", "UPTREND", "BULLISH", "RISING"}
    accelerating = momentum in {
        "ACCELERATING",
        "STRONG",
        "RISING",
        "POSITIVE",
        "MOVING UP",
    }
    deteriorating = momentum in {
        "DETERIORATING",
        "WEAKENING",
        "DECLINING",
        "NEGATIVE",
        "MOVING DOWN",
    }

    if was_buy and is_buy and deteriorating:
        return OvtlyrStatus.DETERIORATING, "Existing BUY momentum is weakening"
    if is_buy and new.setup in {"REENTRY", "RE_ENTRY", "RE-ENTRY"}:
        return OvtlyrStatus.RE_ENTRY, "Established BUY has a new re-entry setup"
    if is_buy and new.entry_watch:
        return OvtlyrStatus.ENTRY_WATCH, "BUY is approaching the approved 10/20/Pine entry"
    if is_buy and not was_buy and trend_up and accelerating:
        return OvtlyrStatus.EMERGING, "New BUY with rising trend and accelerating momentum"
    if is_buy and not was_buy:
        return OvtlyrStatus.NEW_BUY, "BUY triggered since the previous file"
    if is_buy and was_buy and trend_up and accelerating:
        return OvtlyrStatus.LEADER, "Sustained BUY with confirmed trend and momentum"
    if is_buy:
        return OvtlyrStatus.ACTIVE_BUY, "BUY remains active without a higher-priority setup"
    return OvtlyrStatus.UNCHANGED, "No active BUY transition"


def _normalize(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("&", "and")
        .replace("/", "_")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _value(
    row: dict[str, str],
    columns: dict[str, str],
    *aliases: str,
) -> str:
    for alias in aliases:
        original = columns.get(alias)
        if original:
            return (row.get(original) or "").strip()
    return ""


def _boolean(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "1", "y", "optionable"}:
        return True
    if normalized in {"no", "false", "0", "n", "not_optionable"}:
        return False
    return None
