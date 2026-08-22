"""Fixture/shadow-only institutional vendor adapters for Daily Alpha.

These adapters normalize captured Massive, Databento, Financial Modeling Prep (FMP),
and Benzinga payloads into the provider-agnostic Stage 4B contracts. Network transport,
credential resolution, retry, rate limiting, raw archival, and queue semantics remain in
Stage 9B ``aws_transport``. This module performs no HTTP calls and contains no secrets.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any

from .aws_transport import RetryDisposition, TransportResponseReceipt
from .contracts import EvidenceStatus
from .data_providers import (
    DataDomain,
    ProviderCapability,
    ProviderDefinition,
    ProviderObservation,
    ProviderRegistry,
    ProviderRole,
)
from .event_reconciliation import SourceAuthority
from .public_primary_adapters import HttpMethod, HttpRequestSpec


class VendorAdapterError(ValueError):
    """A vendor request or captured payload violates the institutional adapter contract."""


class VendorAdapterRoute(StrEnum):
    MASSIVE_STOCK_BARS = "MASSIVE_STOCK_BARS"
    DATABENTO_OHLCV = "DATABENTO_OHLCV"
    FMP_INCOME_STATEMENT = "FMP_INCOME_STATEMENT"
    FMP_ANALYST_ESTIMATES = "FMP_ANALYST_ESTIMATES"
    BENZINGA_NEWS = "BENZINGA_NEWS"


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
        raise VendorAdapterError("VENDOR_VALUE_NOT_CANONICAL_JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise VendorAdapterError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _required_text(value: Any, reason: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise VendorAdapterError(reason)
    return text


def _finite_positive(value: Any, reason: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise VendorAdapterError(reason) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise VendorAdapterError(reason)
    return parsed


def _finite_nonnegative(value: Any, reason: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise VendorAdapterError(reason) from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise VendorAdapterError(reason)
    return parsed


def _security_subject(security_id: str) -> str:
    security = security_id.strip().upper()
    if not security:
        raise VendorAdapterError("VENDOR_SECURITY_ID_REQUIRED")
    return f"SECURITY:{security}"


def _date_midnight_utc(value: Any, reason: str) -> datetime:
    text = _required_text(value, reason)
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise VendorAdapterError(reason) from exc
    return datetime.combine(parsed, time.min, tzinfo=UTC)


def _parse_iso_timestamp(value: Any, reason: str) -> datetime:
    text = _required_text(value, reason)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise VendorAdapterError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VendorAdapterError(f"{reason}_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def _parse_benzinga_timestamp(value: Any, reason: str) -> datetime:
    text = _required_text(value, reason)
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return _parse_iso_timestamp(text, reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VendorAdapterError(f"{reason}_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def _duration_for_timespan(multiplier: int, timespan: str) -> tuple[str, timedelta]:
    if multiplier <= 0:
        raise VendorAdapterError("MARKET_BAR_MULTIPLIER_MUST_BE_POSITIVE")
    unit = timespan.strip().lower()
    factors = {
        "second": ("S", timedelta(seconds=1)),
        "minute": ("M", timedelta(minutes=1)),
        "hour": ("H", timedelta(hours=1)),
        "day": ("D", timedelta(days=1)),
    }
    try:
        suffix, base = factors[unit]
    except KeyError as exc:
        raise VendorAdapterError("MARKET_BAR_TIMESPAN_UNSUPPORTED") from exc
    return f"{multiplier}{suffix}", base * multiplier


def _duration_for_databento_schema(schema: str) -> tuple[str, timedelta]:
    normalized = schema.strip().lower()
    mapping = {
        "ohlcv-1s": ("1S", timedelta(seconds=1)),
        "ohlcv-1m": ("1M", timedelta(minutes=1)),
        "ohlcv-1h": ("1H", timedelta(hours=1)),
        "ohlcv-1d": ("1D", timedelta(days=1)),
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise VendorAdapterError("DATABENTO_OHLCV_SCHEMA_UNSUPPORTED") from exc


def _parse_epoch(value: Any, *, unit: str, reason: str) -> datetime:
    try:
        raw = int(value)
    except (TypeError, ValueError) as exc:
        raise VendorAdapterError(reason) from exc
    divisor = {"ms": 1_000, "ns": 1_000_000_000}[unit]
    try:
        return datetime.fromtimestamp(raw / divisor, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise VendorAdapterError(reason) from exc


def _ensure_completed_bar(bar_end: datetime, received_at: datetime, provider: str) -> None:
    if bar_end > received_at:
        raise VendorAdapterError(f"{provider}_FUTURE_OR_INCOMPLETE_BAR_NOT_ALLOWED")


@dataclass(frozen=True)
class MassiveStocksAdapter:
    """Massive Stocks aggregate-bar adapter; formerly Polygon-compatible schema."""

    BASE_URL = "https://api.massive.com"
    SECRET_NAME = "MASSIVE_API_KEY"
    SOURCE_VERSION = "MASSIVE_STOCKS_AGGS_V1"

    @staticmethod
    def definition() -> ProviderDefinition:
        return ProviderDefinition(
            provider_id="MASSIVE",
            display_name="Massive Stocks",
            independence_group="MASSIVE_MARKET_DATA",
            source_version=MassiveStocksAdapter.SOURCE_VERSION,
            capabilities=(
                ProviderCapability(
                    domain=DataDomain.MARKET_BARS,
                    role=ProviderRole.PRIMARY,
                    cadence_seconds=60,
                    max_freshness_seconds=120,
                    supports_point_in_time_history=True,
                ),
            ),
        )

    @classmethod
    def aggregate_request(
        cls,
        *,
        ticker: str,
        multiplier: int,
        timespan: str,
        start: str,
        end: str,
        limit: int = 50_000,
    ) -> HttpRequestSpec:
        symbol = _required_text(ticker, "MASSIVE_TICKER_REQUIRED").upper()
        _duration_for_timespan(multiplier, timespan)
        if limit <= 0:
            raise VendorAdapterError("MASSIVE_LIMIT_MUST_BE_POSITIVE")
        start_text = _required_text(start, "MASSIVE_START_REQUIRED")
        end_text = _required_text(end, "MASSIVE_END_REQUIRED")
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=(
                f"{cls.BASE_URL}/v2/aggs/ticker/{symbol}/range/"
                f"{multiplier}/{timespan.strip().lower()}/{start_text}/{end_text}"
            ),
            query=(
                ("adjusted", "true"),
                ("limit", str(limit)),
                ("sort", "asc"),
            ),
            requires_secret=True,
            secret_name=cls.SECRET_NAME,
        )

    @classmethod
    def parse_aggregate_response(
        cls,
        payload: Any,
        *,
        security_id: str,
        ticker: str,
        multiplier: int,
        timespan: str,
        received_at: datetime,
    ) -> tuple[ProviderObservation, ...]:
        received = _aware_utc(received_at, "MASSIVE_RECEIVED_AT")
        if not isinstance(payload, dict):
            raise VendorAdapterError("MASSIVE_RESPONSE_SHAPE_INVALID")
        if str(payload.get("status") or "").upper() not in {"OK", "DELAYED"}:
            raise VendorAdapterError("MASSIVE_RESPONSE_STATUS_NOT_SUCCESS")
        expected = _required_text(ticker, "MASSIVE_TICKER_REQUIRED").upper()
        actual = _required_text(payload.get("ticker"), "MASSIVE_RESPONSE_TICKER_REQUIRED").upper()
        if actual != expected:
            raise VendorAdapterError("MASSIVE_RESPONSE_TICKER_MISMATCH")
        results = payload.get("results")
        if not isinstance(results, list):
            raise VendorAdapterError("MASSIVE_RESULTS_REQUIRED")
        timeframe, duration = _duration_for_timespan(multiplier, timespan)
        request_id = str(payload.get("request_id") or "").strip()
        observations: list[ProviderObservation] = []
        for raw in results:
            if not isinstance(raw, dict):
                raise VendorAdapterError("MASSIVE_RESULT_ITEM_INVALID")
            bar_start = _parse_epoch(raw.get("t"), unit="ms", reason="MASSIVE_BAR_TIMESTAMP_INVALID")
            bar_end = bar_start + duration
            _ensure_completed_bar(bar_end, received, "MASSIVE")
            open_price = _finite_positive(raw.get("o"), "MASSIVE_OPEN_INVALID")
            high = _finite_positive(raw.get("h"), "MASSIVE_HIGH_INVALID")
            low = _finite_positive(raw.get("l"), "MASSIVE_LOW_INVALID")
            close = _finite_positive(raw.get("c"), "MASSIVE_CLOSE_INVALID")
            volume = _finite_nonnegative(raw.get("v"), "MASSIVE_VOLUME_INVALID")
            if high < max(open_price, low, close) or low > min(open_price, high, close):
                raise VendorAdapterError("MASSIVE_OHLC_INCONSISTENT")
            provenance = {
                "vendor_symbol": expected,
                "vendor_request_id": request_id,
            }
            if raw.get("n") is not None:
                provenance["transaction_count"] = str(raw["n"])
            if raw.get("vw") is not None:
                provenance["vwap"] = str(raw["vw"])
            observations.append(
                ProviderObservation(
                    provider_id="MASSIVE",
                    independence_group="MASSIVE_MARKET_DATA",
                    domain=DataDomain.MARKET_BARS,
                    metric="OHLCV",
                    subject_key=_security_subject(security_id),
                    value={
                        "timeframe": timeframe,
                        "bar_start": bar_start.isoformat(),
                        "bar_end": bar_end.isoformat(),
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    },
                    observed_at=bar_end,
                    received_at=received,
                    source_version=cls.SOURCE_VERSION,
                    status=EvidenceStatus.COMPLETE,
                    confidence=1.0,
                    provenance=provenance,
                )
            )
        return tuple(sorted(observations, key=lambda item: item.observed_at))


@dataclass(frozen=True)
class DatabentoHistoricalAdapter:
    """Databento historical OHLCV adapter using JSON/JSON-lines capture."""

    BASE_URL = "https://hist.databento.com/v0/timeseries.get_range"
    SECRET_NAME = "DATABENTO_API_KEY"
    SOURCE_VERSION = "DATABENTO_HIST_OHLCV_V1"

    @staticmethod
    def definition() -> ProviderDefinition:
        return ProviderDefinition(
            provider_id="DATABENTO",
            display_name="Databento Historical",
            independence_group="DATABENTO_MARKET_DATA",
            source_version=DatabentoHistoricalAdapter.SOURCE_VERSION,
            capabilities=(
                ProviderCapability(
                    domain=DataDomain.MARKET_BARS,
                    role=ProviderRole.SECONDARY,
                    cadence_seconds=60,
                    max_freshness_seconds=120,
                    supports_point_in_time_history=True,
                ),
            ),
        )

    @classmethod
    def ohlcv_request(
        cls,
        *,
        dataset: str,
        symbol: str,
        schema: str,
        start: str,
        end: str,
        limit: int | None = None,
    ) -> HttpRequestSpec:
        dataset_text = _required_text(dataset, "DATABENTO_DATASET_REQUIRED")
        symbol_text = _required_text(symbol, "DATABENTO_SYMBOL_REQUIRED").upper()
        schema_text = schema.strip().lower()
        _duration_for_databento_schema(schema_text)
        start_text = _required_text(start, "DATABENTO_START_REQUIRED")
        end_text = _required_text(end, "DATABENTO_END_REQUIRED")
        query: list[tuple[str, str]] = [
            ("dataset", dataset_text),
            ("encoding", "json"),
            ("end", end_text),
            ("map_symbols", "true"),
            ("pretty_px", "true"),
            ("pretty_ts", "true"),
            ("schema", schema_text),
            ("start", start_text),
            ("stype_in", "raw_symbol"),
            ("symbols", symbol_text),
        ]
        if limit is not None:
            if limit <= 0:
                raise VendorAdapterError("DATABENTO_LIMIT_MUST_BE_POSITIVE")
            query.append(("limit", str(limit)))
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=cls.BASE_URL,
            query=tuple(query),
            requires_secret=True,
            secret_name=cls.SECRET_NAME,
        )

    @staticmethod
    def _record_timestamp(raw: dict[str, Any]) -> datetime:
        header = raw.get("hd") if isinstance(raw.get("hd"), dict) else {}
        value = header.get("ts_event", raw.get("ts_event"))
        if isinstance(value, str) and not value.isdigit():
            return _parse_iso_timestamp(value, "DATABENTO_TS_EVENT_INVALID")
        return _parse_epoch(value, unit="ns", reason="DATABENTO_TS_EVENT_INVALID")

    @classmethod
    def parse_ohlcv_response(
        cls,
        payload: Any,
        *,
        security_id: str,
        symbol: str,
        schema: str,
        received_at: datetime,
    ) -> tuple[ProviderObservation, ...]:
        received = _aware_utc(received_at, "DATABENTO_RECEIVED_AT")
        if not isinstance(payload, list):
            raise VendorAdapterError("DATABENTO_RESPONSE_MUST_BE_RECORD_LIST")
        expected = _required_text(symbol, "DATABENTO_SYMBOL_REQUIRED").upper()
        timeframe, duration = _duration_for_databento_schema(schema)
        observations: list[ProviderObservation] = []
        for raw in payload:
            if not isinstance(raw, dict):
                raise VendorAdapterError("DATABENTO_RECORD_INVALID")
            actual_symbol = _required_text(
                raw.get("symbol"), "DATABENTO_RECORD_SYMBOL_REQUIRED"
            ).upper()
            if actual_symbol != expected:
                raise VendorAdapterError("DATABENTO_RECORD_SYMBOL_MISMATCH")
            bar_start = cls._record_timestamp(raw)
            bar_end = bar_start + duration
            _ensure_completed_bar(bar_end, received, "DATABENTO")
            open_price = _finite_positive(raw.get("open"), "DATABENTO_OPEN_INVALID")
            high = _finite_positive(raw.get("high"), "DATABENTO_HIGH_INVALID")
            low = _finite_positive(raw.get("low"), "DATABENTO_LOW_INVALID")
            close = _finite_positive(raw.get("close"), "DATABENTO_CLOSE_INVALID")
            volume = _finite_nonnegative(raw.get("volume"), "DATABENTO_VOLUME_INVALID")
            if high < max(open_price, low, close) or low > min(open_price, high, close):
                raise VendorAdapterError("DATABENTO_OHLC_INCONSISTENT")
            header = raw.get("hd") if isinstance(raw.get("hd"), dict) else raw
            provenance = {
                "vendor_symbol": expected,
                "schema": schema.strip().lower(),
                "instrument_id": str(header.get("instrument_id") or ""),
                "publisher_id": str(header.get("publisher_id") or ""),
                "rtype": str(header.get("rtype") or ""),
            }
            observations.append(
                ProviderObservation(
                    provider_id="DATABENTO",
                    independence_group="DATABENTO_MARKET_DATA",
                    domain=DataDomain.MARKET_BARS,
                    metric="OHLCV",
                    subject_key=_security_subject(security_id),
                    value={
                        "timeframe": timeframe,
                        "bar_start": bar_start.isoformat(),
                        "bar_end": bar_end.isoformat(),
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    },
                    observed_at=bar_end,
                    received_at=received,
                    source_version=cls.SOURCE_VERSION,
                    status=EvidenceStatus.COMPLETE,
                    confidence=1.0,
                    provenance=provenance,
                )
            )
        return tuple(sorted(observations, key=lambda item: item.observed_at))


@dataclass(frozen=True)
class FinancialModelingPrepAdapter:
    """FMP normalized fundamentals and analyst-estimate snapshot adapter."""

    BASE_URL = "https://financialmodelingprep.com/stable"
    SECRET_NAME = "FMP_API_KEY"
    SOURCE_VERSION = "FMP_STABLE_V1"

    @staticmethod
    def definition() -> ProviderDefinition:
        return ProviderDefinition(
            provider_id="FMP",
            display_name="Financial Modeling Prep",
            independence_group="FMP_NORMALIZED",
            source_version=FinancialModelingPrepAdapter.SOURCE_VERSION,
            capabilities=(
                ProviderCapability(
                    domain=DataDomain.FUNDAMENTALS,
                    role=ProviderRole.PRIMARY,
                    cadence_seconds=86_400,
                    max_freshness_seconds=172_800,
                    supports_point_in_time_history=False,
                ),
                ProviderCapability(
                    domain=DataDomain.ESTIMATES_REVISIONS,
                    role=ProviderRole.PRIMARY,
                    cadence_seconds=86_400,
                    max_freshness_seconds=172_800,
                    supports_point_in_time_history=False,
                ),
            ),
        )

    @classmethod
    def income_statement_request(
        cls,
        *,
        symbol: str,
        period: str = "quarter",
        limit: int = 8,
    ) -> HttpRequestSpec:
        ticker = _required_text(symbol, "FMP_SYMBOL_REQUIRED").upper()
        normalized_period = period.strip().lower()
        if normalized_period not in {"annual", "quarter"}:
            raise VendorAdapterError("FMP_PERIOD_INVALID")
        if limit <= 0:
            raise VendorAdapterError("FMP_LIMIT_MUST_BE_POSITIVE")
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=f"{cls.BASE_URL}/income-statement",
            query=(("limit", str(limit)), ("period", normalized_period), ("symbol", ticker)),
            requires_secret=True,
            secret_name=cls.SECRET_NAME,
        )

    @classmethod
    def analyst_estimates_request(
        cls,
        *,
        symbol: str,
        period: str = "quarter",
        limit: int = 8,
    ) -> HttpRequestSpec:
        ticker = _required_text(symbol, "FMP_SYMBOL_REQUIRED").upper()
        normalized_period = period.strip().lower()
        if normalized_period not in {"annual", "quarter"}:
            raise VendorAdapterError("FMP_PERIOD_INVALID")
        if limit <= 0:
            raise VendorAdapterError("FMP_LIMIT_MUST_BE_POSITIVE")
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=f"{cls.BASE_URL}/analyst-estimates",
            query=(("limit", str(limit)), ("period", normalized_period), ("symbol", ticker)),
            requires_secret=True,
            secret_name=cls.SECRET_NAME,
        )

    @staticmethod
    def _validate_records(payload: Any, symbol: str) -> tuple[dict[str, Any], ...]:
        if not isinstance(payload, list):
            raise VendorAdapterError("FMP_RESPONSE_MUST_BE_LIST")
        expected = _required_text(symbol, "FMP_SYMBOL_REQUIRED").upper()
        records: list[dict[str, Any]] = []
        for raw in payload:
            if not isinstance(raw, dict):
                raise VendorAdapterError("FMP_RECORD_INVALID")
            actual = _required_text(raw.get("symbol"), "FMP_RECORD_SYMBOL_REQUIRED").upper()
            if actual != expected:
                raise VendorAdapterError("FMP_RECORD_SYMBOL_MISMATCH")
            records.append(raw)
        return tuple(records)

    @classmethod
    def parse_income_statements(
        cls,
        payload: Any,
        *,
        security_id: str,
        symbol: str,
        received_at: datetime,
    ) -> tuple[ProviderObservation, ...]:
        received = _aware_utc(received_at, "FMP_RECEIVED_AT")
        records = cls._validate_records(payload, symbol)
        observations: list[ProviderObservation] = []
        fields = (
            "reportedCurrency",
            "revenue",
            "costOfRevenue",
            "grossProfit",
            "operatingIncome",
            "netIncome",
            "eps",
            "epsDiluted",
            "ebitda",
        )
        for raw in records:
            period_end = _date_midnight_utc(raw.get("date"), "FMP_STATEMENT_DATE_INVALID")
            period = _required_text(raw.get("period"), "FMP_STATEMENT_PERIOD_REQUIRED").upper()
            fact_value = {key: raw.get(key) for key in fields if key in raw}
            if not fact_value:
                raise VendorAdapterError("FMP_STATEMENT_FACT_FIELDS_REQUIRED")
            revision_id = _digest(raw)
            observations.append(
                ProviderObservation(
                    provider_id="FMP",
                    independence_group="FMP_NORMALIZED",
                    domain=DataDomain.FUNDAMENTALS,
                    metric="INCOME_STATEMENT",
                    subject_key=_security_subject(security_id),
                    value={
                        "authority": SourceAuthority.VENDOR_NORMALIZED.value,
                        "fact_key": f"INCOME_STATEMENT:{period_end.date().isoformat()}:{period}",
                        "fact_value": fact_value,
                        # FMP normalized statements are capture-time vendor facts. The transport
                        # receipt is the trustworthy historical known/publication boundary.
                        "published_at": received.isoformat(),
                        "period_end": period_end.isoformat(),
                        "unit": str(raw.get("reportedCurrency") or "").strip() or None,
                        "revision_id": revision_id,
                        "primary_document_id": None,
                    },
                    observed_at=received,
                    received_at=received,
                    source_version=cls.SOURCE_VERSION,
                    status=EvidenceStatus.COMPLETE,
                    confidence=0.90,
                    provenance={
                        "vendor_symbol": symbol.strip().upper(),
                        "vendor_capture_boundary": "TRANSPORT_RECEIPT",
                        "filling_date": str(raw.get("fillingDate") or ""),
                        "accepted_date": str(raw.get("acceptedDate") or ""),
                        "cik": str(raw.get("cik") or ""),
                    },
                )
            )
        return tuple(sorted(observations, key=lambda item: (item.value["period_end"], item.observation_id)))

    @classmethod
    def parse_analyst_estimates(
        cls,
        payload: Any,
        *,
        security_id: str,
        symbol: str,
        received_at: datetime,
    ) -> tuple[ProviderObservation, ...]:
        received = _aware_utc(received_at, "FMP_RECEIVED_AT")
        records = cls._validate_records(payload, symbol)
        observations: list[ProviderObservation] = []
        for raw in records:
            period_end = _date_midnight_utc(raw.get("date"), "FMP_ESTIMATE_DATE_INVALID")
            fact_value = {
                key: value
                for key, value in raw.items()
                if key not in {"symbol", "date"} and value is not None
            }
            if not fact_value:
                raise VendorAdapterError("FMP_ESTIMATE_FACT_FIELDS_REQUIRED")
            revision_id = _digest(raw)
            observations.append(
                ProviderObservation(
                    provider_id="FMP",
                    independence_group="FMP_NORMALIZED",
                    domain=DataDomain.ESTIMATES_REVISIONS,
                    metric="ANALYST_ESTIMATES",
                    subject_key=_security_subject(security_id),
                    value={
                        "authority": SourceAuthority.VENDOR_NORMALIZED.value,
                        "fact_key": f"ANALYST_ESTIMATES:{period_end.date().isoformat()}",
                        "fact_value": fact_value,
                        # Current consensus endpoints are snapshots, not a trustworthy historical
                        # revision tape. Capture time therefore defines what Daily Alpha knew.
                        "published_at": received.isoformat(),
                        "period_end": period_end.isoformat(),
                        "unit": None,
                        "revision_id": revision_id,
                        "primary_document_id": None,
                    },
                    observed_at=received,
                    received_at=received,
                    source_version=cls.SOURCE_VERSION,
                    status=EvidenceStatus.COMPLETE,
                    confidence=0.75,
                    provenance={
                        "vendor_symbol": symbol.strip().upper(),
                        "vendor_capture_boundary": "TRANSPORT_RECEIPT",
                        "historical_revision_tape_claimed": "false",
                    },
                )
            )
        return tuple(sorted(observations, key=lambda item: (item.value["period_end"], item.observation_id)))


@dataclass(frozen=True)
class BenzingaNewsAdapter:
    """Benzinga Newsfeed adapter; vendor news remains secondary research evidence."""

    BASE_URL = "https://api.benzinga.com/api/v2/news"
    SECRET_NAME = "BENZINGA_API_KEY"
    SOURCE_VERSION = "BENZINGA_NEWS_V2"

    @staticmethod
    def definition() -> ProviderDefinition:
        return ProviderDefinition(
            provider_id="BENZINGA",
            display_name="Benzinga Newsfeed",
            independence_group="BENZINGA_NEWS",
            source_version=BenzingaNewsAdapter.SOURCE_VERSION,
            capabilities=(
                ProviderCapability(
                    domain=DataDomain.NEWS_CATALYSTS,
                    role=ProviderRole.PRIMARY,
                    cadence_seconds=300,
                    max_freshness_seconds=600,
                    supports_point_in_time_history=True,
                ),
            ),
        )

    @classmethod
    def news_request(
        cls,
        *,
        ticker: str,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        display_output: str = "abstract",
    ) -> HttpRequestSpec:
        symbol = _required_text(ticker, "BENZINGA_TICKER_REQUIRED").upper()
        if not 1 <= page_size <= 100:
            raise VendorAdapterError("BENZINGA_PAGE_SIZE_OUT_OF_RANGE")
        output = display_output.strip().lower()
        if output not in {"headline", "abstract", "full"}:
            raise VendorAdapterError("BENZINGA_DISPLAY_OUTPUT_INVALID")
        query: list[tuple[str, str]] = [
            ("displayOutput", output),
            ("pageSize", str(page_size)),
            ("tickers", symbol),
        ]
        if date_from is not None:
            query.append(("dateFrom", _required_text(date_from, "BENZINGA_DATE_FROM_INVALID")))
        if date_to is not None:
            query.append(("dateTo", _required_text(date_to, "BENZINGA_DATE_TO_INVALID")))
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=cls.BASE_URL,
            query=tuple(query),
            requires_secret=True,
            secret_name=cls.SECRET_NAME,
        )

    @classmethod
    def parse_news_response(
        cls,
        payload: Any,
        *,
        security_id: str,
        ticker: str,
        received_at: datetime,
    ) -> tuple[ProviderObservation, ...]:
        received = _aware_utc(received_at, "BENZINGA_RECEIVED_AT")
        if not isinstance(payload, list):
            raise VendorAdapterError("BENZINGA_RESPONSE_MUST_BE_LIST")
        expected = _required_text(ticker, "BENZINGA_TICKER_REQUIRED").upper()
        observations: list[ProviderObservation] = []
        for raw in payload:
            if not isinstance(raw, dict):
                raise VendorAdapterError("BENZINGA_NEWS_ITEM_INVALID")
            item_id = _required_text(raw.get("id"), "BENZINGA_NEWS_ID_REQUIRED")
            created = _parse_benzinga_timestamp(raw.get("created"), "BENZINGA_CREATED_INVALID")
            updated = _parse_benzinga_timestamp(
                raw.get("updated") or raw.get("created"), "BENZINGA_UPDATED_INVALID"
            )
            if created > received or updated > received:
                raise VendorAdapterError("BENZINGA_FUTURE_NEWS_NOT_ALLOWED")
            stocks = raw.get("stocks")
            if not isinstance(stocks, list):
                raise VendorAdapterError("BENZINGA_STOCK_ASSOCIATIONS_REQUIRED")
            associated = {
                str(item.get("name") or "").strip().upper()
                for item in stocks
                if isinstance(item, dict)
            }
            if expected not in associated:
                raise VendorAdapterError("BENZINGA_NEWS_TICKER_MISMATCH")
            title = _required_text(raw.get("title"), "BENZINGA_NEWS_TITLE_REQUIRED")
            channels = sorted(
                {
                    str(item.get("name") or "").strip()
                    for item in (raw.get("channels") or [])
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                }
            )
            tags = sorted(
                {
                    str(item.get("name") or "").strip()
                    for item in (raw.get("tags") or [])
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                }
            )
            observations.append(
                ProviderObservation(
                    provider_id="BENZINGA",
                    independence_group="BENZINGA_NEWS",
                    domain=DataDomain.NEWS_CATALYSTS,
                    metric="NEWS_ITEM",
                    subject_key=_security_subject(security_id),
                    value={
                        "authority": SourceAuthority.SECONDARY.value,
                        "fact_key": f"NEWS:{item_id}",
                        "fact_value": {
                            "title": title,
                            "teaser": str(raw.get("teaser") or ""),
                            "url": str(raw.get("url") or ""),
                            "author": str(raw.get("author") or ""),
                            "channels": channels,
                            "tags": tags,
                        },
                        "published_at": created.isoformat(),
                        "period_end": None,
                        "unit": None,
                        "revision_id": f"{item_id}:{updated.isoformat()}",
                        "primary_document_id": None,
                    },
                    observed_at=created,
                    received_at=received,
                    source_version=cls.SOURCE_VERSION,
                    status=EvidenceStatus.COMPLETE,
                    confidence=0.80,
                    provenance={
                        "vendor_symbol": expected,
                        "news_id": item_id,
                        "updated_at": updated.isoformat(),
                        "source_authority": "SECONDARY_VENDOR_NEWS",
                    },
                )
            )
        return tuple(sorted(observations, key=lambda item: (item.observed_at, item.observation_id)))


def institutional_vendor_definitions() -> tuple[ProviderDefinition, ...]:
    """Provider metadata used by reconciliation without exposing vendor schemas downstream."""
    return (
        MassiveStocksAdapter.definition(),
        DatabentoHistoricalAdapter.definition(),
        FinancialModelingPrepAdapter.definition(),
        BenzingaNewsAdapter.definition(),
    )


def institutional_vendor_registry() -> ProviderRegistry:
    return ProviderRegistry(institutional_vendor_definitions())


def _decode_json_body(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VendorAdapterError("VENDOR_RESPONSE_JSON_INVALID") from exc


def _decode_json_lines(body: bytes) -> list[Any]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VendorAdapterError("VENDOR_RESPONSE_JSON_INVALID") from exc
    records: list[Any] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise VendorAdapterError("VENDOR_RESPONSE_JSON_LINES_INVALID") from exc
    return records


def parse_vendor_transport_receipt(
    *,
    route: VendorAdapterRoute,
    receipt: TransportResponseReceipt,
    body: bytes,
    security_id: str,
    symbol: str,
    multiplier: int = 1,
    timespan: str = "day",
    schema: str = "ohlcv-1d",
) -> tuple[ProviderObservation, ...]:
    """Checksum-verify a Stage 9B receipt and hand captured bytes to one vendor adapter."""
    if receipt.disposition is not RetryDisposition.SUCCESS:
        raise VendorAdapterError("VENDOR_TRANSPORT_RECEIPT_NOT_SUCCESS")
    try:
        receipt.validate_body(body)
    except ValueError as exc:
        raise VendorAdapterError("VENDOR_TRANSPORT_BODY_INVALID") from exc

    expected_provider = {
        VendorAdapterRoute.MASSIVE_STOCK_BARS: "MASSIVE",
        VendorAdapterRoute.DATABENTO_OHLCV: "DATABENTO",
        VendorAdapterRoute.FMP_INCOME_STATEMENT: "FMP",
        VendorAdapterRoute.FMP_ANALYST_ESTIMATES: "FMP",
        VendorAdapterRoute.BENZINGA_NEWS: "BENZINGA",
    }[route]
    if receipt.provider_id != expected_provider:
        raise VendorAdapterError("VENDOR_TRANSPORT_PROVIDER_ROUTE_MISMATCH")

    if route is VendorAdapterRoute.DATABENTO_OHLCV:
        payload = _decode_json_lines(body)
        return DatabentoHistoricalAdapter.parse_ohlcv_response(
            payload,
            security_id=security_id,
            symbol=symbol,
            schema=schema,
            received_at=receipt.received_at,
        )

    payload = _decode_json_body(body)
    if route is VendorAdapterRoute.MASSIVE_STOCK_BARS:
        return MassiveStocksAdapter.parse_aggregate_response(
            payload,
            security_id=security_id,
            ticker=symbol,
            multiplier=multiplier,
            timespan=timespan,
            received_at=receipt.received_at,
        )
    if route is VendorAdapterRoute.FMP_INCOME_STATEMENT:
        return FinancialModelingPrepAdapter.parse_income_statements(
            payload,
            security_id=security_id,
            symbol=symbol,
            received_at=receipt.received_at,
        )
    if route is VendorAdapterRoute.FMP_ANALYST_ESTIMATES:
        return FinancialModelingPrepAdapter.parse_analyst_estimates(
            payload,
            security_id=security_id,
            symbol=symbol,
            received_at=receipt.received_at,
        )
    if route is VendorAdapterRoute.BENZINGA_NEWS:
        return BenzingaNewsAdapter.parse_news_response(
            payload,
            security_id=security_id,
            ticker=symbol,
            received_at=receipt.received_at,
        )
    raise VendorAdapterError("VENDOR_ADAPTER_ROUTE_UNSUPPORTED")
