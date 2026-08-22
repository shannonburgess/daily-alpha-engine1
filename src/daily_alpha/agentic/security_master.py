"""Canonical point-in-time Security Master for Daily Alpha.

The Security Master is research/investment infrastructure, not an execution path.
It gives every instrument a stable Daily Alpha identity that survives ticker changes,
corporate actions, and source-vendor changes. Symbol resolution is always point-in-time
and ambiguous identities fail closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SecurityMasterError(ValueError):
    """Security Master data violates identity or point-in-time invariants."""


class AssetType(StrEnum):
    COMPANY_EQUITY = "COMPANY_EQUITY"
    ETF = "ETF"
    ADR = "ADR"
    REIT = "REIT"
    CLOSED_END_FUND = "CLOSED_END_FUND"
    PREFERRED = "PREFERRED"
    OTHER = "OTHER"


class ListingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    DELISTED = "DELISTED"
    PENDING = "PENDING"


class IdentifierNamespace(StrEnum):
    FIGI = "FIGI"
    CUSIP = "CUSIP"
    ISIN = "ISIN"
    CIK = "CIK"
    INTERNAL = "INTERNAL"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SecurityMasterError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SecurityMasterError("SECURITY_MASTER_VALUE_NOT_CANONICAL_JSON") from exc


def _normalize_pairs(
    pairs: tuple[tuple[str, str], ...] | dict[str, str],
) -> tuple[tuple[str, str], ...]:
    items = pairs.items() if isinstance(pairs, dict) else pairs
    normalized = tuple(sorted((str(key).strip(), str(value).strip()) for key, value in items))
    if any(not key for key, _ in normalized):
        raise SecurityMasterError("PROVENANCE_KEY_REQUIRED")
    if len({key for key, _ in normalized}) != len(normalized):
        raise SecurityMasterError("PROVENANCE_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True, order=True)
class SecurityIdentifier:
    namespace: IdentifierNamespace
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip().upper()
        if not value:
            raise SecurityMasterError("SECURITY_IDENTIFIER_VALUE_REQUIRED")
        object.__setattr__(self, "value", value)

    @property
    def key(self) -> tuple[str, str]:
        return self.namespace.value, self.value


@dataclass(frozen=True)
class TickerAlias:
    symbol: str
    exchange_mic: str
    effective_from: datetime
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        exchange = self.exchange_mic.strip().upper()
        if not symbol:
            raise SecurityMasterError("TICKER_ALIAS_SYMBOL_REQUIRED")
        if not exchange:
            raise SecurityMasterError("TICKER_ALIAS_EXCHANGE_REQUIRED")
        start = _aware_utc(self.effective_from, "ALIAS_EFFECTIVE_FROM")
        end = None
        if self.effective_to is not None:
            end = _aware_utc(self.effective_to, "ALIAS_EFFECTIVE_TO")
            if end <= start:
                raise SecurityMasterError("ALIAS_EFFECTIVE_TO_MUST_FOLLOW_EFFECTIVE_FROM")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "exchange_mic", exchange)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_to", end)

    def active_at(self, as_of: datetime) -> bool:
        boundary = _aware_utc(as_of, "AS_OF")
        return self.effective_from <= boundary and (
            self.effective_to is None or boundary < self.effective_to
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "exchange_mic": self.exchange_mic,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
        }


@dataclass(frozen=True)
class SecurityMasterRecord:
    """One immutable point-in-time version of a security definition."""

    security_id: str
    issuer_id: str
    issuer_name: str
    asset_type: AssetType
    primary_ticker: str
    exchange_mic: str
    currency: str
    country: str
    sector: str
    industry: str
    listing_status: ListingStatus
    optionable: bool | None
    effective_from: datetime
    source_version: str
    identifiers: tuple[SecurityIdentifier, ...]
    aliases: tuple[TickerAlias, ...]
    effective_to: datetime | None = None
    share_class: str | None = None
    provenance: tuple[tuple[str, str], ...] | dict[str, str] = field(default_factory=tuple)
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        issuer_id = self.issuer_id.strip().upper()
        issuer_name = self.issuer_name.strip()
        ticker = self.primary_ticker.strip().upper()
        exchange = self.exchange_mic.strip().upper()
        currency = self.currency.strip().upper()
        country = self.country.strip().upper()
        sector = self.sector.strip()
        industry = self.industry.strip()
        source_version = self.source_version.strip()
        share_class = self.share_class.strip() if self.share_class else None

        required = {
            "SECURITY_ID_REQUIRED": security_id,
            "ISSUER_ID_REQUIRED": issuer_id,
            "ISSUER_NAME_REQUIRED": issuer_name,
            "PRIMARY_TICKER_REQUIRED": ticker,
            "EXCHANGE_MIC_REQUIRED": exchange,
            "CURRENCY_REQUIRED": currency,
            "COUNTRY_REQUIRED": country,
            "SOURCE_VERSION_REQUIRED": source_version,
        }
        for error_code, value in required.items():
            if not value:
                raise SecurityMasterError(error_code)
        if not self.identifiers:
            raise SecurityMasterError("AT_LEAST_ONE_DURABLE_IDENTIFIER_REQUIRED")
        if not self.aliases:
            raise SecurityMasterError("AT_LEAST_ONE_TICKER_ALIAS_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise SecurityMasterError("SECURITY_MASTER_MUST_REMAIN_RESEARCH_ONLY")

        start = _aware_utc(self.effective_from, "SECURITY_EFFECTIVE_FROM")
        end = None
        if self.effective_to is not None:
            end = _aware_utc(self.effective_to, "SECURITY_EFFECTIVE_TO")
            if end <= start:
                raise SecurityMasterError("SECURITY_EFFECTIVE_TO_MUST_FOLLOW_EFFECTIVE_FROM")

        identifiers = tuple(sorted(set(self.identifiers), key=lambda item: item.key))
        aliases = tuple(
            sorted(
                set(self.aliases),
                key=lambda item: (
                    item.symbol,
                    item.exchange_mic,
                    item.effective_from,
                    item.effective_to or datetime.max.replace(tzinfo=UTC),
                ),
            )
        )
        if not any(
            alias.symbol == ticker
            and alias.exchange_mic == exchange
            and alias.active_at(start)
            for alias in aliases
        ):
            raise SecurityMasterError("PRIMARY_TICKER_MUST_HAVE_ACTIVE_ALIAS_AT_VERSION_START")

        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "issuer_id", issuer_id)
        object.__setattr__(self, "issuer_name", issuer_name)
        object.__setattr__(self, "primary_ticker", ticker)
        object.__setattr__(self, "exchange_mic", exchange)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "country", country)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(self, "industry", industry)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "share_class", share_class)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_to", end)
        object.__setattr__(self, "identifiers", identifiers)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "provenance", _normalize_pairs(self.provenance))

    def active_at(self, as_of: datetime) -> bool:
        boundary = _aware_utc(as_of, "AS_OF")
        return self.effective_from <= boundary and (
            self.effective_to is None or boundary < self.effective_to
        )

    @property
    def record_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "issuer_id": self.issuer_id,
            "issuer_name": self.issuer_name,
            "asset_type": self.asset_type.value,
            "primary_ticker": self.primary_ticker,
            "exchange_mic": self.exchange_mic,
            "currency": self.currency,
            "country": self.country,
            "sector": self.sector,
            "industry": self.industry,
            "listing_status": self.listing_status.value,
            "optionable": self.optionable,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source_version": self.source_version,
            "share_class": self.share_class,
            "identifiers": [item.key for item in self.identifiers],
            "aliases": [item.to_payload() for item in self.aliases],
            "provenance": list(self.provenance),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SecurityMasterSnapshot:
    as_of: datetime
    security_ids: tuple[str, ...]
    record_ids: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        boundary = _aware_utc(self.as_of, "AS_OF")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise SecurityMasterError("SECURITY_MASTER_SNAPSHOT_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "security_ids", tuple(sorted(self.security_ids)))
        object.__setattr__(self, "record_ids", tuple(sorted(self.record_ids)))

    @property
    def snapshot_id(self) -> str:
        payload = {
            "as_of": self.as_of.isoformat(),
            "security_ids": list(self.security_ids),
            "record_ids": list(self.record_ids),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class InMemorySecurityMaster:
    """Reference Security Master with strict identity and version invariants."""

    def __init__(self) -> None:
        self._records_by_id: dict[str, SecurityMasterRecord] = {}
        self._versions: dict[str, list[SecurityMasterRecord]] = {}
        self._identifier_owner: dict[tuple[str, str], str] = {}

    def add(self, record: SecurityMasterRecord) -> str:
        existing = self._records_by_id.get(record.record_id)
        if existing is not None:
            return record.record_id

        for identifier in record.identifiers:
            owner = self._identifier_owner.get(identifier.key)
            if owner is not None and owner != record.security_id:
                raise SecurityMasterError(
                    "DURABLE_IDENTIFIER_REASSIGNMENT_BLOCKED:"
                    f"{identifier.namespace.value}:{identifier.value}:{owner}:{record.security_id}"
                )

        versions = self._versions.setdefault(record.security_id, [])
        for current in versions:
            if _intervals_overlap(
                current.effective_from,
                current.effective_to,
                record.effective_from,
                record.effective_to,
            ):
                raise SecurityMasterError(
                    f"SECURITY_MASTER_VERSION_OVERLAP:{record.security_id}"
                )

        self._records_by_id[record.record_id] = record
        versions.append(record)
        versions.sort(key=lambda item: (item.effective_from, item.record_id))
        for identifier in record.identifiers:
            self._identifier_owner.setdefault(identifier.key, record.security_id)
        return record.record_id

    def get(self, security_id: str, as_of: datetime) -> SecurityMasterRecord:
        boundary = _aware_utc(as_of, "AS_OF")
        key = security_id.strip().upper()
        matches = [record for record in self._versions.get(key, []) if record.active_at(boundary)]
        if not matches:
            raise SecurityMasterError(f"SECURITY_ID_NOT_ACTIVE:{key}")
        if len(matches) != 1:
            raise SecurityMasterError(f"SECURITY_ID_AMBIGUOUS:{key}")
        return matches[0]

    def resolve_symbol(
        self,
        symbol: str,
        *,
        as_of: datetime,
        exchange_mic: str | None = None,
    ) -> SecurityMasterRecord:
        boundary = _aware_utc(as_of, "AS_OF")
        ticker = symbol.strip().upper()
        exchange = exchange_mic.strip().upper() if exchange_mic else None
        if not ticker:
            raise SecurityMasterError("SYMBOL_REQUIRED")

        matches: list[SecurityMasterRecord] = []
        for record in self.active_records(boundary):
            if any(
                alias.symbol == ticker
                and (exchange is None or alias.exchange_mic == exchange)
                and alias.active_at(boundary)
                for alias in record.aliases
            ):
                matches.append(record)
        if not matches:
            suffix = f":{exchange}" if exchange else ""
            raise SecurityMasterError(f"SYMBOL_NOT_RESOLVED:{ticker}{suffix}")
        if len(matches) != 1:
            ids = ",".join(sorted(record.security_id for record in matches))
            raise SecurityMasterError(f"SYMBOL_AMBIGUOUS:{ticker}:{ids}")
        return matches[0]

    def resolve_identifier(
        self,
        identifier: SecurityIdentifier,
        *,
        as_of: datetime,
    ) -> SecurityMasterRecord:
        owner = self._identifier_owner.get(identifier.key)
        if owner is None:
            raise SecurityMasterError(
                f"IDENTIFIER_NOT_RESOLVED:{identifier.namespace.value}:{identifier.value}"
            )
        return self.get(owner, as_of)

    def active_records(self, as_of: datetime) -> tuple[SecurityMasterRecord, ...]:
        boundary = _aware_utc(as_of, "AS_OF")
        records = [
            record
            for versions in self._versions.values()
            for record in versions
            if record.active_at(boundary)
        ]
        return tuple(sorted(records, key=lambda item: item.security_id))

    def snapshot(self, as_of: datetime) -> SecurityMasterSnapshot:
        boundary = _aware_utc(as_of, "AS_OF")
        records = self.active_records(boundary)
        return SecurityMasterSnapshot(
            as_of=boundary,
            security_ids=tuple(record.security_id for record in records),
            record_ids=tuple(record.record_id for record in records),
        )


def _intervals_overlap(
    left_start: datetime,
    left_end: datetime | None,
    right_start: datetime,
    right_end: datetime | None,
) -> bool:
    infinity = datetime.max.replace(tzinfo=UTC)
    return left_start < (right_end or infinity) and right_start < (left_end or infinity)
