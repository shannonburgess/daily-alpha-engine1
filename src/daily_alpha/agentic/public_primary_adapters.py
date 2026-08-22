"""Deterministic adapters for public primary/reference data sources.

Transport is deliberately separated from normalization. These adapters build safe request
specifications and normalize captured JSON payloads from OpenFIGI, SEC EDGAR, and
FRED/ALFRED into point-in-time records that can be replayed without network access.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from .contracts import EvidenceStatus
from .data_providers import DataDomain, ProviderObservation


class PublicPrimaryAdapterError(ValueError):
    """Public-source request or payload violates the adapter contract."""


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"


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
        raise PublicPrimaryAdapterError("PUBLIC_SOURCE_VALUE_NOT_CANONICAL_JSON") from exc


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicPrimaryAdapterError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _required_text(value: Any, reason: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise PublicPrimaryAdapterError(reason)
    return text


def _parse_date(value: Any, reason: str) -> date:
    text = _required_text(value, reason)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise PublicPrimaryAdapterError(reason) from exc


def _parse_sec_acceptance(value: Any) -> datetime:
    text = _required_text(value, "SEC_ACCEPTANCE_DATETIME_REQUIRED")
    if re.fullmatch(r"\d{14}", text):
        # EDGAR header convention is Eastern Time. For deterministic ordering inside the
        # public-source layer, retain the clock value as UTC only when fixtures explicitly
        # use this legacy compact representation; live transport must preserve source zone.
        parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
        return parsed.replace(tzinfo=UTC)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PublicPrimaryAdapterError("SEC_ACCEPTANCE_DATETIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PublicPrimaryAdapterError("SEC_ACCEPTANCE_DATETIME_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class HttpRequestSpec:
    method: HttpMethod
    url: str
    query: tuple[tuple[str, str], ...] = ()
    json_body: Any | None = None
    requires_secret: bool = False
    secret_name: str | None = None

    def __post_init__(self) -> None:
        url = self.url.strip()
        if not url.startswith("https://"):
            raise PublicPrimaryAdapterError("PUBLIC_SOURCE_HTTPS_REQUIRED")
        query = tuple(sorted((str(k).strip(), str(v).strip()) for k, v in self.query))
        if any(not key for key, _ in query):
            raise PublicPrimaryAdapterError("PUBLIC_SOURCE_QUERY_KEY_REQUIRED")
        if len({key for key, _ in query}) != len(query):
            raise PublicPrimaryAdapterError("PUBLIC_SOURCE_QUERY_KEYS_MUST_BE_UNIQUE")
        if self.json_body is not None:
            _canonical_json(self.json_body)
        secret = self.secret_name.strip() if self.secret_name else None
        if self.requires_secret and not secret:
            raise PublicPrimaryAdapterError("PUBLIC_SOURCE_SECRET_NAME_REQUIRED")
        if not self.requires_secret and secret is not None:
            raise PublicPrimaryAdapterError("PUBLIC_SOURCE_SECRET_NAME_WITHOUT_REQUIREMENT")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "secret_name", secret)

    @property
    def request_id(self) -> str:
        payload = {
            "method": self.method.value,
            "url": self.url,
            "query": list(self.query),
            "json_body": self.json_body,
            "requires_secret": self.requires_secret,
            "secret_name": self.secret_name,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OpenFigiMapping:
    figi: str
    composite_figi: str | None
    share_class_figi: str | None
    ticker: str | None
    name: str | None
    security_type: str | None
    market_sector: str | None
    exchange_code: str | None

    def __post_init__(self) -> None:
        figi = self.figi.strip().upper()
        if not figi:
            raise PublicPrimaryAdapterError("OPENFIGI_FIGI_REQUIRED")
        object.__setattr__(self, "figi", figi)
        for field_name in (
            "composite_figi",
            "share_class_figi",
            "ticker",
            "name",
            "security_type",
            "market_sector",
            "exchange_code",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, str(value).strip() or None)

    @property
    def mapping_id(self) -> str:
        return hashlib.sha256(_canonical_json(self.__dict__).encode("utf-8")).hexdigest()


class OpenFigiAdapter:
    BASE_URL = "https://api.openfigi.com/v3/mapping"

    @staticmethod
    def mapping_request(*, id_type: str, id_value: str) -> HttpRequestSpec:
        id_type = _required_text(id_type, "OPENFIGI_ID_TYPE_REQUIRED")
        id_value = _required_text(id_value, "OPENFIGI_ID_VALUE_REQUIRED")
        return HttpRequestSpec(
            method=HttpMethod.POST,
            url=OpenFigiAdapter.BASE_URL,
            json_body=[{"idType": id_type, "idValue": id_value}],
            requires_secret=False,
        )

    @staticmethod
    def parse_mapping_response(payload: Any) -> tuple[OpenFigiMapping, ...]:
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise PublicPrimaryAdapterError("OPENFIGI_RESPONSE_SHAPE_INVALID")
        item = payload[0]
        if item.get("error"):
            raise PublicPrimaryAdapterError(f"OPENFIGI_MAPPING_ERROR:{str(item['error']).strip()}")
        data = item.get("data")
        if not isinstance(data, list):
            raise PublicPrimaryAdapterError("OPENFIGI_DATA_REQUIRED")
        mappings: list[OpenFigiMapping] = []
        for raw in data:
            if not isinstance(raw, dict):
                raise PublicPrimaryAdapterError("OPENFIGI_DATA_ITEM_INVALID")
            mappings.append(
                OpenFigiMapping(
                    figi=_required_text(raw.get("figi"), "OPENFIGI_FIGI_REQUIRED"),
                    composite_figi=raw.get("compositeFIGI"),
                    share_class_figi=raw.get("shareClassFIGI"),
                    ticker=raw.get("ticker"),
                    name=raw.get("name"),
                    security_type=raw.get("securityType"),
                    market_sector=raw.get("marketSector"),
                    exchange_code=raw.get("exchCode"),
                )
            )
        return tuple(sorted(mappings, key=lambda mapping: mapping.mapping_id))


@dataclass(frozen=True)
class SecFilingRecord:
    cik: str
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    acceptance_datetime: datetime
    primary_document: str | None
    primary_doc_description: str | None

    def __post_init__(self) -> None:
        cik = self.cik.strip()
        accession = self.accession_number.strip()
        form = self.form.strip().upper()
        acceptance = _aware_utc(self.acceptance_datetime, "SEC_FILING_ACCEPTANCE")
        if not re.fullmatch(r"\d{10}", cik):
            raise PublicPrimaryAdapterError("SEC_CIK_MUST_BE_10_DIGITS")
        if not accession or not form:
            raise PublicPrimaryAdapterError("SEC_FILING_IDENTITY_REQUIRED")
        object.__setattr__(self, "cik", cik)
        object.__setattr__(self, "accession_number", accession)
        object.__setattr__(self, "form", form)
        object.__setattr__(self, "acceptance_datetime", acceptance)
        if self.primary_document is not None:
            object.__setattr__(self, "primary_document", self.primary_document.strip() or None)
        if self.primary_doc_description is not None:
            object.__setattr__(
                self,
                "primary_doc_description",
                self.primary_doc_description.strip() or None,
            )

    @property
    def filing_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "cik": self.cik,
                    "accession_number": self.accession_number,
                    "form": self.form,
                    "filing_date": self.filing_date.isoformat(),
                    "report_date": self.report_date.isoformat() if self.report_date else None,
                    "acceptance_datetime": self.acceptance_datetime.isoformat(),
                    "primary_document": self.primary_document,
                    "primary_doc_description": self.primary_doc_description,
                }
            ).encode("utf-8")
        ).hexdigest()

    def to_provider_observation(
        self,
        *,
        security_id: str,
        received_at: datetime,
        source_version: str = "SEC_SUBMISSIONS_V1",
    ) -> ProviderObservation:
        received = _aware_utc(received_at, "SEC_RECEIVED_AT")
        if received < self.acceptance_datetime:
            raise PublicPrimaryAdapterError("SEC_RECEIVED_BEFORE_ACCEPTANCE")
        return ProviderObservation(
            provider_id="SEC_EDGAR",
            independence_group="SEC_EDGAR_PRIMARY",
            domain=DataDomain.SEC_FILINGS,
            metric="FILING",
            subject_key=f"SECURITY:{security_id.strip().upper()}",
            value={
                "cik": self.cik,
                "accession_number": self.accession_number,
                "form": self.form,
                "filing_date": self.filing_date.isoformat(),
                "report_date": self.report_date.isoformat() if self.report_date else None,
                "acceptance_datetime": self.acceptance_datetime.isoformat(),
                "primary_document": self.primary_document,
                "primary_doc_description": self.primary_doc_description,
            },
            observed_at=self.acceptance_datetime,
            received_at=received,
            source_version=source_version,
            status=EvidenceStatus.COMPLETE,
            confidence=1.0,
            provenance={"filing_id": self.filing_id, "source_authority": "REGULATOR_PRIMARY"},
        )


class SecEdgarAdapter:
    BASE_URL = "https://data.sec.gov/submissions"

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        text = str(cik).strip()
        if text.upper().startswith("CIK"):
            text = text[3:]
        if not text.isdigit() or len(text) > 10:
            raise PublicPrimaryAdapterError("SEC_CIK_INVALID")
        return text.zfill(10)

    @classmethod
    def submissions_request(cls, cik: str | int) -> HttpRequestSpec:
        normalized = cls.normalize_cik(cik)
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=f"{cls.BASE_URL}/CIK{normalized}.json",
            requires_secret=False,
        )

    @classmethod
    def parse_recent_filings(cls, payload: Any) -> tuple[SecFilingRecord, ...]:
        if not isinstance(payload, dict):
            raise PublicPrimaryAdapterError("SEC_SUBMISSIONS_PAYLOAD_INVALID")
        cik = cls.normalize_cik(payload.get("cik"))
        recent = payload.get("filings", {}).get("recent") if isinstance(payload.get("filings"), dict) else None
        if not isinstance(recent, dict):
            raise PublicPrimaryAdapterError("SEC_RECENT_FILINGS_REQUIRED")
        required_columns = ("accessionNumber", "filingDate", "form", "acceptanceDateTime")
        if any(not isinstance(recent.get(column), list) for column in required_columns):
            raise PublicPrimaryAdapterError("SEC_RECENT_FILINGS_COLUMNS_REQUIRED")
        count = len(recent["accessionNumber"])
        if any(len(recent[column]) != count for column in required_columns):
            raise PublicPrimaryAdapterError("SEC_RECENT_FILINGS_COLUMN_LENGTH_MISMATCH")

        records: list[SecFilingRecord] = []
        report_dates = recent.get("reportDate", [""] * count)
        primary_docs = recent.get("primaryDocument", [""] * count)
        descriptions = recent.get("primaryDocDescription", [""] * count)
        for optional in (report_dates, primary_docs, descriptions):
            if not isinstance(optional, list) or len(optional) != count:
                raise PublicPrimaryAdapterError("SEC_RECENT_OPTIONAL_COLUMN_LENGTH_MISMATCH")
        for index in range(count):
            report_text = str(report_dates[index]).strip()
            report = _parse_date(report_text, "SEC_REPORT_DATE_INVALID") if report_text else None
            records.append(
                SecFilingRecord(
                    cik=cik,
                    accession_number=_required_text(
                        recent["accessionNumber"][index],
                        "SEC_ACCESSION_REQUIRED",
                    ),
                    form=_required_text(recent["form"][index], "SEC_FORM_REQUIRED"),
                    filing_date=_parse_date(recent["filingDate"][index], "SEC_FILING_DATE_INVALID"),
                    report_date=report,
                    acceptance_datetime=_parse_sec_acceptance(recent["acceptanceDateTime"][index]),
                    primary_document=str(primary_docs[index]).strip() or None,
                    primary_doc_description=str(descriptions[index]).strip() or None,
                )
            )
        return tuple(sorted(records, key=lambda record: (record.acceptance_datetime, record.accession_number)))


@dataclass(frozen=True)
class FredVintageObservation:
    series_id: str
    observation_date: date
    realtime_start: date
    realtime_end: date
    value: float | None

    def __post_init__(self) -> None:
        series_id = self.series_id.strip().upper()
        if not series_id:
            raise PublicPrimaryAdapterError("FRED_SERIES_ID_REQUIRED")
        if self.realtime_end < self.realtime_start:
            raise PublicPrimaryAdapterError("FRED_REALTIME_PERIOD_INVALID")
        if self.value is not None and not math.isfinite(self.value):
            raise PublicPrimaryAdapterError("FRED_VALUE_MUST_BE_FINITE")
        object.__setattr__(self, "series_id", series_id)

    @property
    def vintage_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "series_id": self.series_id,
                    "observation_date": self.observation_date.isoformat(),
                    "realtime_start": self.realtime_start.isoformat(),
                    "realtime_end": self.realtime_end.isoformat(),
                    "value": self.value,
                }
            ).encode("utf-8")
        ).hexdigest()

    def to_provider_observation(
        self,
        *,
        as_of: datetime,
        source_version: str = "FRED_ALFRED_V1",
    ) -> ProviderObservation:
        boundary = _aware_utc(as_of, "FRED_AS_OF")
        vintage_start = datetime.combine(self.realtime_start, datetime.min.time(), tzinfo=UTC)
        if vintage_start > boundary:
            raise PublicPrimaryAdapterError("FUTURE_FRED_VINTAGE_NOT_ALLOWED")
        return ProviderObservation(
            provider_id="FRED_ALFRED",
            independence_group="STLOUISFED_PRIMARY",
            domain=DataDomain.MACRO,
            metric=self.series_id,
            subject_key=f"GLOBAL:{self.series_id}",
            value={
                "observation_date": self.observation_date.isoformat(),
                "realtime_start": self.realtime_start.isoformat(),
                "realtime_end": self.realtime_end.isoformat(),
                "value": self.value,
            },
            observed_at=vintage_start,
            received_at=boundary,
            source_version=source_version,
            status=EvidenceStatus.COMPLETE if self.value is not None else EvidenceStatus.DATA_ERROR,
            confidence=1.0 if self.value is not None else 0.0,
            reason_code=None if self.value is not None else "FRED_MISSING_VALUE",
            provenance={"vintage_id": self.vintage_id, "source_authority": "REGULATOR_PRIMARY"},
        )


class FredAlfredAdapter:
    OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
    VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"

    @staticmethod
    def observations_request(*, series_id: str, as_of_date: date) -> HttpRequestSpec:
        series = _required_text(series_id, "FRED_SERIES_ID_REQUIRED").upper()
        boundary = as_of_date.isoformat()
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=FredAlfredAdapter.OBSERVATIONS_URL,
            query=(
                ("file_type", "json"),
                ("output_type", "1"),
                ("realtime_end", boundary),
                ("realtime_start", boundary),
                ("series_id", series),
            ),
            requires_secret=True,
            secret_name="FRED_API_KEY",
        )

    @staticmethod
    def vintage_dates_request(*, series_id: str) -> HttpRequestSpec:
        series = _required_text(series_id, "FRED_SERIES_ID_REQUIRED").upper()
        return HttpRequestSpec(
            method=HttpMethod.GET,
            url=FredAlfredAdapter.VINTAGE_DATES_URL,
            query=(("file_type", "json"), ("series_id", series)),
            requires_secret=True,
            secret_name="FRED_API_KEY",
        )

    @staticmethod
    def parse_observations(payload: Any, *, series_id: str) -> tuple[FredVintageObservation, ...]:
        if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
            raise PublicPrimaryAdapterError("FRED_OBSERVATIONS_PAYLOAD_INVALID")
        series = _required_text(series_id, "FRED_SERIES_ID_REQUIRED").upper()
        observations: list[FredVintageObservation] = []
        for raw in payload["observations"]:
            if not isinstance(raw, dict):
                raise PublicPrimaryAdapterError("FRED_OBSERVATION_ITEM_INVALID")
            raw_value = _required_text(raw.get("value"), "FRED_VALUE_REQUIRED")
            value = None if raw_value == "." else float(raw_value)
            observations.append(
                FredVintageObservation(
                    series_id=series,
                    observation_date=_parse_date(raw.get("date"), "FRED_OBSERVATION_DATE_INVALID"),
                    realtime_start=_parse_date(raw.get("realtime_start"), "FRED_REALTIME_START_INVALID"),
                    realtime_end=_parse_date(raw.get("realtime_end"), "FRED_REALTIME_END_INVALID"),
                    value=value,
                )
            )
        return tuple(
            sorted(
                observations,
                key=lambda item: (item.observation_date, item.realtime_start, item.realtime_end),
            )
        )
