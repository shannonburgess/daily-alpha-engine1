"""Congressional and institutional accumulation research signals.

This module is research-only. It ranks disclosed accumulation and produces
newsletter-ready factors; it never authorizes paper or live execution.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CongressionalTrade:
    politician: str
    chamber: str
    symbol: str
    issuer: str
    transaction_date: date
    disclosure_date: date
    transaction_type: str
    amount_low: float
    amount_high: float | None
    source_url: str = ""

    @property
    def estimated_value(self) -> float:
        if self.amount_high is None:
            return self.amount_low
        return (self.amount_low + self.amount_high) / 2.0

    @property
    def disclosure_lag_days(self) -> int:
        return max(0, (self.disclosure_date - self.transaction_date).days)


@dataclass(frozen=True)
class InstitutionalHolding:
    manager_cik: str
    manager_name: str
    cusip: str
    issuer: str
    symbol: str
    period_of_report: date
    shares: float
    value: float


@dataclass(frozen=True)
class CongressionalAccumulation:
    rank: int
    symbol: str
    issuer: str
    score: float
    unique_politicians: int
    purchase_count: int
    estimated_purchase_value: float
    latest_transaction_date: str
    latest_disclosure_date: str
    average_disclosure_lag_days: float
    politicians: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["politicians"] = list(self.politicians)
        return payload


@dataclass(frozen=True)
class InstitutionalAccumulation:
    rank: int
    symbol: str
    cusip: str
    issuer: str
    score: float
    managers_increasing: int
    new_manager_positions: int
    shares_added: float
    estimated_value_added: float
    period_of_report: str
    top_managers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_managers"] = list(self.top_managers)
        return payload


@dataclass(frozen=True)
class SmartMoneySnapshot:
    generated_at: str
    congressional: tuple[CongressionalAccumulation, ...]
    institutional: tuple[InstitutionalAccumulation, ...]
    coverage: Mapping[str, Any]
    disclosures: tuple[str, ...]
    trading_authorized: bool = False
    paper_execution_triggered: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "congressional": [item.to_dict() for item in self.congressional],
            "institutional": [item.to_dict() for item in self.institutional],
            "coverage": dict(self.coverage),
            "disclosures": list(self.disclosures),
            "trading_authorized": self.trading_authorized,
            "paper_execution_triggered": self.paper_execution_triggered,
            "live_trading_enabled": self.live_trading_enabled,
        }


def rank_congressional_acquisitions(
    trades: Iterable[CongressionalTrade],
    *,
    as_of: date,
    lookback_days: int = 90,
    limit: int = 5,
) -> tuple[CongressionalAccumulation, ...]:
    """Rank disclosed PURCHASE activity by breadth, value, repeats, and recency."""
    if lookback_days <= 0 or limit <= 0:
        raise ValueError("lookback_days and limit must be positive")

    grouped: dict[str, list[CongressionalTrade]] = {}
    for trade in trades:
        if trade.transaction_type.upper() not in {"PURCHASE", "BUY", "BOUGHT"}:
            continue
        if trade.disclosure_date > as_of:
            continue
        age = (as_of - trade.transaction_date).days
        if age < 0 or age > lookback_days:
            continue
        symbol = trade.symbol.strip().upper()
        if not symbol or symbol in {"--", "N/A", "NA"}:
            continue
        grouped.setdefault(symbol, []).append(trade)

    rows: list[CongressionalAccumulation] = []
    for symbol, items in grouped.items():
        politicians = tuple(sorted({item.politician.strip() for item in items if item.politician.strip()}))
        unique_count = len(politicians)
        estimated_value = sum(item.estimated_value for item in items)
        latest_tx = max(item.transaction_date for item in items)
        latest_disclosure = max(item.disclosure_date for item in items)
        recency = max(0.0, 10.0 * (1.0 - (as_of - latest_tx).days / lookback_days))
        value_points = min(20.0, max(0.0, math.log10(max(estimated_value, 1.0)) * 3.0))
        breadth_points = min(45.0, unique_count * 15.0)
        repeat_points = min(20.0, len(items) * 2.0)
        score = round(breadth_points + repeat_points + value_points + recency, 2)
        issuer = _mode(item.issuer for item in items)
        average_lag = sum(item.disclosure_lag_days for item in items) / len(items)
        rows.append(
            CongressionalAccumulation(
                rank=0,
                symbol=symbol,
                issuer=issuer,
                score=score,
                unique_politicians=unique_count,
                purchase_count=len(items),
                estimated_purchase_value=round(estimated_value, 2),
                latest_transaction_date=latest_tx.isoformat(),
                latest_disclosure_date=latest_disclosure.isoformat(),
                average_disclosure_lag_days=round(average_lag, 1),
                politicians=politicians,
            )
        )

    ordered = sorted(
        rows,
        key=lambda item: (
            -item.score,
            -item.unique_politicians,
            -item.estimated_purchase_value,
            item.symbol,
        ),
    )[:limit]
    return tuple(replace(item, rank=index) for index, item in enumerate(ordered, start=1))


def rank_institutional_acquisitions(
    current: Iterable[InstitutionalHolding],
    previous: Iterable[InstitutionalHolding],
    *,
    limit: int = 5,
    symbol_map: Mapping[str, str] | None = None,
) -> tuple[InstitutionalAccumulation, ...]:
    """Rank securities by quarter-over-quarter positive share accumulation.

    Share changes are primary so market-price appreciation alone does not look
    like an institutional purchase. Reported current value is used only to
    estimate the value of newly added shares.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    mapping = {key.upper(): value.upper() for key, value in (symbol_map or {}).items()}
    before = _collapse_holdings(previous)
    now = _collapse_holdings(current)

    aggregate: dict[str, dict[str, Any]] = {}
    for key, holding in now.items():
        prior = before.get(key)
        prior_shares = prior.shares if prior else 0.0
        delta_shares = holding.shares - prior_shares
        if delta_shares <= 0:
            continue
        avg_price = holding.value / holding.shares if holding.shares > 0 else 0.0
        estimated_added = max(0.0, delta_shares * avg_price)
        bucket = aggregate.setdefault(
            holding.cusip,
            {
                "issuer": holding.issuer,
                "period": holding.period_of_report,
                "managers": [],
                "new_positions": 0,
                "shares_added": 0.0,
                "estimated_value_added": 0.0,
                "symbol": holding.symbol,
            },
        )
        bucket["managers"].append((holding.manager_name, estimated_added))
        bucket["new_positions"] += 1 if prior is None or prior.shares <= 0 else 0
        bucket["shares_added"] += delta_shares
        bucket["estimated_value_added"] += estimated_added
        bucket["period"] = max(bucket["period"], holding.period_of_report)
        if holding.symbol:
            bucket["symbol"] = holding.symbol

    rows: list[InstitutionalAccumulation] = []
    for cusip, bucket in aggregate.items():
        managers = bucket["managers"]
        manager_count = len(managers)
        new_count = int(bucket["new_positions"])
        value_added = float(bucket["estimated_value_added"])
        breadth_points = min(50.0, manager_count * 5.0)
        new_points = min(20.0, new_count * 3.0)
        value_points = min(30.0, max(0.0, math.log10(max(value_added, 1.0)) * 4.0))
        score = round(breadth_points + new_points + value_points, 2)
        top_managers = tuple(
            name for name, _ in sorted(managers, key=lambda pair: (-pair[1], pair[0]))[:5]
        )
        symbol = mapping.get(cusip.upper()) or str(bucket["symbol"] or "").upper()
        rows.append(
            InstitutionalAccumulation(
                rank=0,
                symbol=symbol,
                cusip=cusip,
                issuer=str(bucket["issuer"]),
                score=score,
                managers_increasing=manager_count,
                new_manager_positions=new_count,
                shares_added=round(float(bucket["shares_added"]), 4),
                estimated_value_added=round(value_added, 2),
                period_of_report=bucket["period"].isoformat(),
                top_managers=top_managers,
            )
        )

    ordered = sorted(
        rows,
        key=lambda item: (
            -item.score,
            -item.managers_increasing,
            -item.estimated_value_added,
            item.cusip,
        ),
    )[:limit]
    return tuple(replace(item, rank=index) for index, item in enumerate(ordered, start=1))


def smart_money_bonus(
    symbol: str,
    congressional: Iterable[CongressionalAccumulation],
    institutional: Iterable[InstitutionalAccumulation],
) -> float:
    """Return the bounded research-ranking bonus: Congress 0-5, institutions 0-10."""
    target = symbol.strip().upper()
    congress_points = {1: 5.0, 2: 4.0, 3: 3.0, 4: 2.0, 5: 1.0}
    institution_points = {1: 10.0, 2: 8.0, 3: 6.0, 4: 4.0, 5: 2.0}
    bonus = 0.0
    for item in congressional:
        if item.symbol.upper() == target:
            bonus += congress_points.get(item.rank, 0.0)
            break
    for item in institutional:
        if item.symbol and item.symbol.upper() == target:
            bonus += institution_points.get(item.rank, 0.0)
            break
    return min(15.0, bonus)


def build_smart_money_snapshot(
    *,
    generated_at: datetime,
    congressional: Iterable[CongressionalAccumulation],
    institutional: Iterable[InstitutionalAccumulation],
    coverage: Mapping[str, Any],
) -> SmartMoneySnapshot:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    disclosures = (
        "Congressional transactions are disclosure data, not real-time trades; reporting may lag the transaction date.",
        "Form 13F reports quarter-end holdings and cannot identify the exact purchase date within the quarter.",
        "Smart-money factors are confirmation inputs only and never override Pine, ORATS freshness, or portfolio risk gates.",
    )
    return SmartMoneySnapshot(
        generated_at=generated_at.isoformat(),
        congressional=tuple(congressional),
        institutional=tuple(institutional),
        coverage=dict(coverage),
        disclosures=disclosures,
    )


def write_smart_money_outputs(
    output_dir: str | Path,
    snapshot: SmartMoneySnapshot,
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "smart_money.json"
    congress_csv = destination / "congressional_top5.csv"
    institution_csv = destination / "institutional_top5.csv"
    summary_path = destination / "summary.json"

    payload = snapshot.to_dict()
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_rows(congress_csv, [item.to_dict() for item in snapshot.congressional])
    _write_rows(institution_csv, [item.to_dict() for item in snapshot.institutional])
    summary_path.write_text(
        json.dumps(
            {
                "generated_at": snapshot.generated_at,
                "congressional_count": len(snapshot.congressional),
                "institutional_count": len(snapshot.institutional),
                "coverage": dict(snapshot.coverage),
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
    return {
        "json": json_path,
        "congressional_csv": congress_csv,
        "institutional_csv": institution_csv,
        "summary": summary_path,
    }


def _collapse_holdings(
    holdings: Iterable[InstitutionalHolding],
) -> dict[tuple[str, str], InstitutionalHolding]:
    collapsed: dict[tuple[str, str], InstitutionalHolding] = {}
    for item in holdings:
        key = (item.manager_cik, item.cusip.upper())
        existing = collapsed.get(key)
        if existing is None:
            collapsed[key] = item
            continue
        collapsed[key] = replace(
            existing,
            shares=existing.shares + item.shares,
            value=existing.value + item.value,
            symbol=existing.symbol or item.symbol,
            issuer=existing.issuer or item.issuer,
        )
    return collapsed


def _mode(values: Iterable[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        cleaned = value.strip()
        if cleaned:
            counts[cleaned] = counts.get(cleaned, 0) + 1
    if not counts:
        return ""
    return min(counts, key=lambda value: (-counts[value], value))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not rows:
            return
        normalized = []
        for row in rows:
            normalized.append(
                {
                    key: "; ".join(value) if isinstance(value, list) else value
                    for key, value in row.items()
                }
            )
        writer = csv.DictWriter(handle, fieldnames=list(normalized[0]))
        writer.writeheader()
        writer.writerows(normalized)
