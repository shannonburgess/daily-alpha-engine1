"""Trump administration company and policy-watch research factors.

This layer is intentionally research-only. It converts official White House
company/investment mentions into a bounded confirmation score and never
represents an administration mention as a stock recommendation or trade signal.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrumpPolicyCompany:
    rank: int
    symbol: str
    company: str
    score: float
    investment_usd: float
    sector: str
    investment_focus: str
    source_type: str
    source_url: str
    direct_trump_mention: bool = False
    administration_beneficiary: bool = True
    trump_affiliated: bool = False

    @property
    def research_bonus(self) -> float:
        """Bounded 0-5 confirmation bonus; affiliation alone earns no points."""
        if self.trump_affiliated and not self.administration_beneficiary:
            return 0.0
        points = 1.0 if self.administration_beneficiary else 0.0
        if self.investment_usd >= 200_000_000_000:
            points += 2.0
        elif self.investment_usd >= 50_000_000_000:
            points += 1.5
        elif self.investment_usd >= 10_000_000_000:
            points += 1.0
        elif self.investment_usd >= 1_000_000_000:
            points += 0.5
        if self.direct_trump_mention:
            points += 2.0
        return min(5.0, round(points, 2))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["research_bonus"] = self.research_bonus
        return payload


@dataclass(frozen=True)
class TrumpPolicySnapshot:
    generated_at: str
    companies: tuple[TrumpPolicyCompany, ...]
    source_url: str
    disclosures: tuple[str, ...]
    trading_authorized: bool = False
    paper_execution_triggered: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "companies": [item.to_dict() for item in self.companies],
            "source_url": self.source_url,
            "disclosures": list(self.disclosures),
            "trading_authorized": self.trading_authorized,
            "paper_execution_triggered": self.paper_execution_triggered,
            "live_trading_enabled": self.live_trading_enabled,
        }


def rank_trump_policy_companies(
    companies: Iterable[TrumpPolicyCompany], *, limit: int = 10
) -> tuple[TrumpPolicyCompany, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    unique: dict[str, TrumpPolicyCompany] = {}
    for item in companies:
        symbol = item.symbol.strip().upper()
        if not symbol:
            continue
        existing = unique.get(symbol)
        if existing is None or _ranking_key(item) < _ranking_key(existing):
            unique[symbol] = replace(item, symbol=symbol)
    ordered = sorted(unique.values(), key=_ranking_key)[:limit]
    return tuple(replace(item, rank=index) for index, item in enumerate(ordered, start=1))


def trump_policy_bonus(symbol: str, companies: Iterable[TrumpPolicyCompany]) -> float:
    """Return the strongest official-policy confirmation bonus for one symbol."""
    target = symbol.strip().upper()
    matches = [item.research_bonus for item in companies if item.symbol.upper() == target]
    return min(5.0, max(matches, default=0.0))


def build_trump_policy_snapshot(
    *,
    generated_at: datetime,
    companies: Iterable[TrumpPolicyCompany],
    source_url: str,
) -> TrumpPolicySnapshot:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    disclosures = (
        "This is a Trump Administration company and policy watch, not a list of stock recommendations by President Trump.",
        "An official White House investment or company mention is a catalyst/confirmation input only and does not establish investment merit.",
        "Trump-affiliated companies receive no bonus solely because of affiliation.",
        "This factor never overrides OVTLYR, ORATS freshness, Pine entry/exit signals, or portfolio risk controls.",
    )
    return TrumpPolicySnapshot(
        generated_at=generated_at.isoformat(),
        companies=tuple(companies),
        source_url=source_url,
        disclosures=disclosures,
    )


def write_trump_policy_outputs(
    output_dir: str | Path, snapshot: TrumpPolicySnapshot
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "trump_policy_watch.json"
    csv_path = destination / "trump_policy_top.csv"
    summary_path = destination / "summary.json"

    payload = snapshot.to_dict()
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = [item.to_dict() for item in snapshot.companies]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary_path.write_text(
        json.dumps(
            {
                "generated_at": snapshot.generated_at,
                "company_count": len(snapshot.companies),
                "source_url": snapshot.source_url,
                "trading_authorized": False,
                "paper_execution_triggered": False,
                "live_trading_enabled": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "summary": summary_path}


def _ranking_key(item: TrumpPolicyCompany) -> tuple[float, float, str]:
    return (-item.score, -item.investment_usd, item.symbol)
