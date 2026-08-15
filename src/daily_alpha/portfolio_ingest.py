"""Broker-neutral ingestion and reconciliation for canonical portfolio snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .portfolio import (
    AssetType,
    Greeks,
    PortfolioDataStatus,
    PortfolioSnapshot,
    Position,
)


class DuplicateSnapshotError(ValueError):
    """Raised when identical portfolio input is submitted more than once."""


@dataclass(frozen=True)
class IngestionResult:
    snapshot: PortfolioSnapshot
    content_hash: str


class PortfolioSnapshotIngestor:
    """Normalize external portfolio payloads without estimating missing risk data."""

    def __init__(self, *, max_age: timedelta = timedelta(minutes=15)) -> None:
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        self.max_age = max_age
        self._seen_hashes: set[str] = set()

    def ingest(
        self,
        payload: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> IngestionResult:
        content_hash = self._content_hash(payload)
        if content_hash in self._seen_hashes:
            raise DuplicateSnapshotError(f"duplicate portfolio snapshot: {content_hash}")

        current_time = now or datetime.now(UTC)
        if current_time.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        as_of = self._parse_timestamp(self._required_text(payload, "as_of"))
        errors: list[str] = []
        status = self._freshness_status(as_of, current_time, errors)

        raw_positions = payload.get("positions")
        if not isinstance(raw_positions, list):
            raise TypeError("positions must be a list")
        positions = tuple(self._parse_position(raw) for raw in raw_positions)
        self._reconcile(payload, positions, errors)
        if errors and status == PortfolioDataStatus.AVAILABLE:
            status = PortfolioDataStatus.PARTIAL

        snapshot = PortfolioSnapshot.create(
            snapshot_id=self._required_text(payload, "snapshot_id"),
            account_id=self._required_text(payload, "account_id"),
            source=self._required_text(payload, "source"),
            as_of=as_of.isoformat(),
            cash=self._number(payload, "cash"),
            buying_power=self._number(payload, "buying_power"),
            positions=positions,
            data_status=status,
            reconciliation_errors=errors,
        )
        self._seen_hashes.add(content_hash)
        return IngestionResult(snapshot=snapshot, content_hash=content_hash)

    @staticmethod
    def _content_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return parsed

    def _freshness_status(
        self,
        as_of: datetime,
        now: datetime,
        errors: list[str],
    ) -> PortfolioDataStatus:
        age = now - as_of
        if age < -timedelta(minutes=1):
            errors.append("as_of timestamp is in the future")
            return PortfolioDataStatus.PARTIAL
        if age > self.max_age:
            errors.append(f"portfolio snapshot is stale by {age}")
            return PortfolioDataStatus.STALE
        return PortfolioDataStatus.AVAILABLE

    @classmethod
    def _parse_position(cls, raw: Any) -> Position:
        if not isinstance(raw, dict):
            raise TypeError("each position must be an object")
        try:
            asset_type = AssetType(cls._required_text(raw, "asset_type"))
        except ValueError as exc:
            raise ValueError(f"unsupported asset_type: {raw.get('asset_type')}") from exc

        greeks_payload = raw.get("greeks")
        greeks = None
        if greeks_payload is not None:
            if not isinstance(greeks_payload, dict):
                raise ValueError("greeks must be an object")
            greeks = Greeks(
                delta=cls._number(greeks_payload, "delta"),
                gamma=cls._number(greeks_payload, "gamma"),
                theta=cls._number(greeks_payload, "theta"),
                vega=cls._number(greeks_payload, "vega"),
            )
        return Position(
            symbol=cls._required_text(raw, "symbol"),
            asset_type=asset_type,
            quantity=cls._number(raw, "quantity"),
            mark=cls._number(raw, "mark"),
            cost_basis=cls._number(raw, "cost_basis"),
            multiplier=int(raw.get("multiplier", 1)),
            sector=str(raw.get("sector", "UNKNOWN")),
            expiration=raw.get("expiration"),
            greeks=greeks,
        )

    @staticmethod
    def _reconcile(
        payload: dict[str, Any],
        positions: tuple[Position, ...],
        errors: list[str],
    ) -> None:
        symbols = [position.symbol for position in positions]
        if len(symbols) != len(set(symbols)):
            errors.append("duplicate position symbols")

        reported_count = payload.get("reported_position_count")
        if reported_count is not None and int(reported_count) != len(positions):
            errors.append(
                f"position count mismatch: reported={int(reported_count)} parsed={len(positions)}"
            )

        reported_nlv = payload.get("reported_net_liquidating_value")
        if reported_nlv is not None:
            calculated = float(payload["cash"]) + sum(p.market_value for p in positions)
            tolerance = float(payload.get("reconciliation_tolerance", 0.01))
            if abs(float(reported_nlv) - calculated) > tolerance:
                errors.append(
                    f"NAV mismatch: reported={float(reported_nlv):.2f} calculated={calculated:.2f}"
                )

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
        return value.strip()

    @staticmethod
    def _number(payload: dict[str, Any], key: str) -> float:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"{key} must be numeric")
        return float(value)
