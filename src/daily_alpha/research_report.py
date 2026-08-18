"""Deterministic, newsletter-ready Daily Alpha research records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .models import InstrumentSelected
from .smart_money import SmartMoneySnapshot


class ResearchDisposition(StrEnum):
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    WATCHLIST = "WATCHLIST"
    NO_TRADE = "NO_TRADE"
    DATA_ERROR = "DATA_ERROR"


@dataclass(frozen=True)
class OptionFlowEvidence:
    """One quality-filtered unusual option-flow observation for newsletter use."""

    option_type: str
    contract: str
    volume: int
    open_interest: int
    volume_oi_ratio: float
    bid: float
    ask: float
    classification: str = "UNUSUAL_CONFIRMATION"

    def __post_init__(self) -> None:
        if self.option_type not in {"CALL", "PUT"}:
            raise ValueError("option flow evidence must be CALL or PUT")
        if not self.contract:
            raise ValueError("option flow evidence requires contract identity")
        if self.volume < 0 or self.open_interest < 0:
            raise ValueError("option flow counts cannot be negative")
        if self.volume_oi_ratio < 0:
            raise ValueError("option flow ratio cannot be negative")
        if self.bid < 0 or self.ask < self.bid:
            raise ValueError("option flow quote is invalid")
        if self.classification != "UNUSUAL_CONFIRMATION":
            raise ValueError("side-specific flow evidence must be unusual confirmation")


@dataclass(frozen=True)
class ResearchCandidate:
    symbol: str
    disposition: ResearchDisposition
    instrument: InstrumentSelected
    signal_label: str
    thesis: str
    reasons: tuple[str, ...]
    risk_status: str
    data_status: str
    sector: str = "UNKNOWN"
    option_contract: str | None = None
    planned_loss_nav: float | None = None
    expected_move_pct: float | None = None
    flow_classification: str | None = None
    option_volume: int = 0
    option_open_interest: int = 0
    option_volume_oi_ratio: float | None = None
    option_bid: float | None = None
    option_ask: float | None = None
    option_flow_evidence: tuple[OptionFlowEvidence, ...] = ()
    standalone_flow_signal: bool = False

    def __post_init__(self) -> None:
        if not self.symbol or not self.signal_label or not self.thesis:
            raise ValueError("symbol, signal label, and thesis are required")
        if not self.reasons:
            raise ValueError("at least one explainable reason is required")
        if self.standalone_flow_signal:
            raise ValueError("options flow cannot be a standalone signal")
        if self.option_volume < 0 or self.option_open_interest < 0:
            raise ValueError("option flow counts cannot be negative")
        if self.option_volume_oi_ratio is not None and self.option_volume_oi_ratio < 0:
            raise ValueError("option_volume_oi_ratio cannot be negative")
        flow_sides = [item.option_type for item in self.option_flow_evidence]
        if len(flow_sides) != len(set(flow_sides)):
            raise ValueError("only one unusual flow observation per option side is allowed")
        if self.disposition == ResearchDisposition.DATA_ERROR:
            if self.instrument != InstrumentSelected.NONE:
                raise ValueError("DATA_ERROR cannot select an instrument")
        elif self.disposition == ResearchDisposition.PAPER_CANDIDATE:
            if self.instrument == InstrumentSelected.NONE:
                raise ValueError("paper candidate requires a selected instrument")
            if self.risk_status != "APPROVED" or self.data_status != "PASS":
                raise ValueError("paper candidate requires approved risk and passing data")
        if self.instrument == InstrumentSelected.OPTION and not self.option_contract:
            raise ValueError("selected option requires contract identity")
        if self.planned_loss_nav is not None and self.planned_loss_nav < 0:
            raise ValueError("planned_loss_nav cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["disposition"] = self.disposition.value
        payload["instrument"] = self.instrument.value
        return payload


@dataclass(frozen=True)
class DailyResearchPacket:
    report_date: str
    run_id: str
    methodology_version: str
    generated_at: str
    market_regime: str
    candidates: tuple[ResearchCandidate, ...]
    disclosures: tuple[str, ...] = (
        "Research and paper-trading output only; not investment advice.",
        "No live order execution is authorized.",
    )
    smart_money: SmartMoneySnapshot | None = None

    def __post_init__(self) -> None:
        if not all((self.report_date, self.run_id, self.methodology_version, self.generated_at)):
            raise ValueError("packet identity and version fields are required")
        if len({candidate.symbol for candidate in self.candidates}) != len(self.candidates):
            raise ValueError("candidate symbols must be unique within a daily packet")
        if self.smart_money is not None and self.smart_money.trading_authorized:
            raise ValueError("smart-money snapshot cannot authorize trading")

    @property
    def counts(self) -> dict[str, int]:
        return {
            disposition.value: sum(
                candidate.disposition == disposition for candidate in self.candidates
            )
            for disposition in ResearchDisposition
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "run_id": self.run_id,
            "methodology_version": self.methodology_version,
            "generated_at": self.generated_at,
            "market_regime": self.market_regime,
            "counts": self.counts,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "disclosures": list(self.disclosures),
            "smart_money": self.smart_money.to_dict() if self.smart_money else None,
        }


def data_error_candidate(symbol: str, *, reason: str, signal_label: str) -> ResearchCandidate:
    """Fail closed: missing/stale ORATS data never creates a stock substitute."""
    return ResearchCandidate(
        symbol=symbol,
        disposition=ResearchDisposition.DATA_ERROR,
        instrument=InstrumentSelected.NONE,
        signal_label=signal_label,
        thesis="Candidate withheld because required market data failed validation.",
        reasons=(reason,),
        risk_status="NOT_EVALUATED",
        data_status="DATA_ERROR",
    )
