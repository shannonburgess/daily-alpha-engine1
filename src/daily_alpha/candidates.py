"""Rank OVTLYR research candidates after Pine, risk, and ORATS gates."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .fallback import InstrumentFallbackEngine
from .models import DecisionStatus, InstrumentSelected, OptionCandidate, StockCandidate
from .ovtlyr import ClassifiedRecord, OvtlyrRecord, OvtlyrStatus

ACTIONABLE_STATUSES = {
    OvtlyrStatus.NEW_BUY,
    OvtlyrStatus.EMERGING,
    OvtlyrStatus.LEADER,
    OvtlyrStatus.ENTRY_WATCH,
    OvtlyrStatus.RE_ENTRY,
}


class CandidateBucket(StrEnum):
    OPTION_SETUP = "OPTION_SETUP"
    STOCK_FALLBACK = "STOCK_FALLBACK"
    ENTRY_WATCH = "ENTRY_WATCH"
    NO_TRADE = "NO_TRADE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class CandidateAssessment:
    symbol: str
    ovtlyr_status: str
    bucket: CandidateBucket
    score: float
    instrument_selected: str
    fallback_reason: str
    sector: str
    sector_net_score: int
    pine_entry: bool
    risk_gate_passed: bool
    optionable: bool | None
    selected_expiration: str = ""
    selected_strike: float = 0.0
    selected_delta: float | None = None
    selected_spread_pct: float | None = None
    unusual_options_activity: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["bucket"] = self.bucket.value
        return payload


def assess_candidate(
    *,
    classified: ClassifiedRecord,
    source: OvtlyrRecord,
    options: Iterable[OptionCandidate],
    option_data_available: bool,
    option_data_fresh: bool,
    pine_entry: bool,
    risk_gate_passed: bool,
    sector_net_score: int = 0,
    engine: InstrumentFallbackEngine | None = None,
) -> CandidateAssessment:
    """Apply the approved hierarchy and return one newsletter-ready assessment."""
    fallback = engine or InstrumentFallbackEngine()
    actionable = classified.status in ACTIONABLE_STATUSES and source.signal == "BUY"
    stock = _stock_candidate(source) if actionable else None
    decision = fallback.select(
        symbol=source.symbol,
        signal_active=actionable and pine_entry,
        risk_gate_passed=risk_gate_passed,
        option_data_fresh=option_data_fresh,
        option_data_available=option_data_available,
        options=options,
        stock=stock,
    )

    if decision.status == DecisionStatus.DATA_ERROR:
        bucket = CandidateBucket.DATA_ERROR
    elif decision.instrument_selected == InstrumentSelected.OPTION:
        bucket = CandidateBucket.OPTION_SETUP
    elif decision.instrument_selected == InstrumentSelected.STOCK:
        bucket = CandidateBucket.STOCK_FALLBACK
    elif actionable and not pine_entry:
        bucket = CandidateBucket.ENTRY_WATCH
    else:
        bucket = CandidateBucket.NO_TRADE

    contract = decision.selected_contract
    score = _score(
        classified=classified,
        source=source,
        bucket=bucket,
        sector_net_score=sector_net_score,
        contract=contract,
    )
    return CandidateAssessment(
        symbol=source.symbol,
        ovtlyr_status=classified.status.value,
        bucket=bucket,
        score=score,
        instrument_selected=decision.instrument_selected.value,
        fallback_reason=decision.fallback_reason,
        sector=source.sector,
        sector_net_score=sector_net_score,
        pine_entry=pine_entry,
        risk_gate_passed=risk_gate_passed,
        optionable=source.optionable,
        selected_expiration=contract.expiration if contract else "",
        selected_strike=contract.strike if contract else 0.0,
        selected_delta=contract.delta if contract else None,
        selected_spread_pct=round(contract.spread_pct, 6) if contract else None,
        unusual_options_activity=(
            contract is not None and contract.volume_to_open_interest >= 1.0
        ),
    )


def rank_candidates(items: Iterable[CandidateAssessment]) -> list[CandidateAssessment]:
    bucket_order = {
        CandidateBucket.OPTION_SETUP: 0,
        CandidateBucket.STOCK_FALLBACK: 1,
        CandidateBucket.ENTRY_WATCH: 2,
        CandidateBucket.DATA_ERROR: 3,
        CandidateBucket.NO_TRADE: 4,
    }
    return sorted(items, key=lambda item: (bucket_order[item.bucket], -item.score, item.symbol))


def write_candidate_outputs(
    output_dir: str | Path,
    items: Iterable[CandidateAssessment],
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    ranked = rank_candidates(items)
    json_path = destination / "candidates.json"
    csv_path = destination / "candidates.csv"
    summary_path = destination / "candidate_summary.json"
    rows = [item.to_dict() for item in ranked]
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    counts = {bucket.value: 0 for bucket in CandidateBucket}
    for item in ranked:
        counts[item.bucket.value] += 1
    summary_path.write_text(
        json.dumps({"counts": counts, "total": len(ranked)}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "summary": summary_path}


def _stock_candidate(source: OvtlyrRecord) -> StockCandidate | None:
    if source.price <= 0 or source.average_volume <= 0:
        return None
    return StockCandidate(
        symbol=source.symbol,
        price=source.price,
        average_daily_dollar_volume=source.price * source.average_volume,
        eligible=not source.partial_data,
    )


def _score(
    *,
    classified: ClassifiedRecord,
    source: OvtlyrRecord,
    bucket: CandidateBucket,
    sector_net_score: int,
    contract: OptionCandidate | None,
) -> float:
    status_points = {
        OvtlyrStatus.EMERGING: 40,
        OvtlyrStatus.NEW_BUY: 36,
        OvtlyrStatus.RE_ENTRY: 34,
        OvtlyrStatus.ENTRY_WATCH: 30,
        OvtlyrStatus.LEADER: 26,
    }.get(classified.status, 0)
    points = float(status_points)
    if source.trend in {"UP", "UPTREND", "BULLISH", "RISING"}:
        points += 10
    if source.momentum in {"ACCELERATING", "STRONG", "RISING", "POSITIVE", "MOVING UP"}:
        points += 10
    points += max(-10, min(15, sector_net_score / 10))
    if bucket == CandidateBucket.OPTION_SETUP:
        points += 20
    elif bucket == CandidateBucket.STOCK_FALLBACK:
        points += 8
    elif bucket == CandidateBucket.DATA_ERROR:
        points -= 25
    if contract is not None:
        points += max(0.0, 10.0 - 50.0 * contract.spread_pct)
        points += min(5.0, contract.volume_to_open_interest * 5.0)
    return round(points, 2)
