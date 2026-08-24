"""Research-only staging ingestion for Massive, Tiingo, and FRED."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

PROVIDERS = frozenset({"massive", "tiingo", "fred"})
SECRET_NAMES = {
    "massive": "daily-alpha/data-feeds/staging/massive",
    "tiingo": "daily-alpha/data-feeds/staging/tiingo",
    "fred": "daily-alpha/data-feeds/staging/fred",
}
SECRET_JSON_KEYS = {
    "massive": ("MASSIVE_API_KEY", "api_key", "key", "apiKey"),
    "tiingo": ("TIINGO_API_TOKEN", "token", "api_key", "key", "apiKey"),
    "fred": ("FRED_API_KEY", "api_key", "key", "apiKey"),
}
DEFAULT_TARGETS = {
    "massive": ("SPY", "DINO"),
    "tiingo": ("SPY", "DINO"),
    "fred": ("DFF", "DGS10", "VIXCLS"),
}
CAPTURE_MODE_CURRENT = "CURRENT_WINDOW"
CAPTURE_MODE_HISTORICAL = "HISTORICAL_BACKFILL"
CAPTURE_MODES = frozenset({CAPTURE_MODE_CURRENT, CAPTURE_MODE_HISTORICAL})
MAX_HISTORICAL_BACKFILL_DAYS = 31
KNOWN_AT_BASIS = "CAPTURED_AT_ONLY"
FRED_INITIAL_RELEASE_OUTPUT_TYPE = 4
_TARGET_RE = re.compile(r"^[A-Z0-9.^_-]{1,32}$")


class DataFeedIngestionError(RuntimeError):
    """Fail-closed staging ingestion error with a non-secret error code."""


def _aws_client(service: str):
    import boto3  # AWS Lambda runtime dependency; intentionally not a project dependency.

    return boto3.client(service)


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_secret_value(secret_string: str, provider: str | None = None) -> str:
    text = str(secret_string or "").strip()
    if not text:
        raise DataFeedIngestionError("SECRET_VALUE_EMPTY")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(payload, dict):
        raise DataFeedIngestionError("SECRET_JSON_OBJECT_REQUIRED")
    if provider is None:
        keys = ("api_key", "token", "key", "apiKey")
    else:
        if provider not in SECRET_JSON_KEYS:
            raise DataFeedIngestionError("SECRET_PROVIDER_UNSUPPORTED")
        keys = SECRET_JSON_KEYS[provider]
    values: list[str] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    unique = tuple(dict.fromkeys(values))
    if len(unique) != 1:
        raise DataFeedIngestionError("SECRET_JSON_KEY_AMBIGUOUS_OR_MISSING")
    return unique[0]


def _load_secret(provider: str, client=None) -> str:
    secrets = client or _aws_client("secretsmanager")
    response = secrets.get_secret_value(
        SecretId=SECRET_NAMES[provider],
        VersionStage="AWSCURRENT",
    )
    if "SecretString" not in response:
        raise DataFeedIngestionError("BINARY_SECRET_NOT_SUPPORTED")
    return _safe_secret_value(response["SecretString"], provider)


def _targets(provider: str, event: dict[str, Any]) -> tuple[str, ...]:
    raw = event.get("targets")
    if raw is None:
        values = DEFAULT_TARGETS[provider]
    elif isinstance(raw, list):
        values = tuple(str(item).strip().upper() for item in raw)
    else:
        raise DataFeedIngestionError("TARGETS_MUST_BE_ARRAY")
    if not values or len(values) > 20:
        raise DataFeedIngestionError("TARGET_COUNT_OUT_OF_RANGE")
    if len(set(values)) != len(values):
        raise DataFeedIngestionError("TARGETS_MUST_BE_UNIQUE")
    if any(not _TARGET_RE.fullmatch(value) for value in values):
        raise DataFeedIngestionError("TARGET_INVALID")
    return values


def _parse_iso_date(value: Any, code: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise DataFeedIngestionError(f"{code}_REQUIRED")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DataFeedIngestionError(f"{code}_INVALID") from exc


def _capture_window(event: dict[str, Any], as_of: datetime) -> tuple[str, date, date]:
    mode = str(event.get("capture_mode") or CAPTURE_MODE_CURRENT).strip().upper()
    if mode not in CAPTURE_MODES:
        raise DataFeedIngestionError("CAPTURE_MODE_UNSUPPORTED")

    if mode == CAPTURE_MODE_CURRENT:
        if event.get("start_date") is not None or event.get("end_date") is not None:
            raise DataFeedIngestionError("CURRENT_WINDOW_DATE_OVERRIDE_NOT_ALLOWED")
        end_date = as_of.date()
        return mode, end_date - timedelta(days=7), end_date

    start_date = _parse_iso_date(event.get("start_date"), "BACKFILL_START_DATE")
    end_date = _parse_iso_date(event.get("end_date"), "BACKFILL_END_DATE")
    if start_date > end_date:
        raise DataFeedIngestionError("BACKFILL_DATE_RANGE_INVALID")
    if end_date > as_of.date():
        raise DataFeedIngestionError("BACKFILL_END_DATE_IN_FUTURE")
    span_days = (end_date - start_date).days + 1
    if span_days > MAX_HISTORICAL_BACKFILL_DAYS:
        raise DataFeedIngestionError("BACKFILL_DATE_RANGE_TOO_LARGE")
    return mode, start_date, end_date


def _request_spec(
    provider: str,
    target: str,
    api_key: str,
    as_of: datetime,
    *,
    capture_mode: str = CAPTURE_MODE_CURRENT,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[str, dict[str, str]]:
    mode = str(capture_mode or "").strip().upper()
    if mode not in CAPTURE_MODES:
        raise DataFeedIngestionError("CAPTURE_MODE_UNSUPPORTED")
    if start_date is None and end_date is None:
        _, start_date, end_date = _capture_window({}, as_of)
    elif start_date is None or end_date is None:
        raise DataFeedIngestionError("REQUEST_DATE_RANGE_INCOMPLETE")

    headers = {
        "Accept": "application/json",
        "User-Agent": "daily-alpha-staging-ingestion/1.0",
    }
    if provider == "massive":
        path_target = quote(target, safe=".-")
        limit = 50 if mode == CAPTURE_MODE_HISTORICAL else 20
        url = (
            f"https://api.massive.com/v2/aggs/ticker/{path_target}/range/1/day/"
            f"{start_date.isoformat()}/{end_date.isoformat()}?"
            f"adjusted=true&sort=asc&limit={limit}"
        )
        headers["Authorization"] = f"Bearer {api_key}"
        return url, headers
    if provider == "tiingo":
        path_target = quote(target, safe=".-")
        query = urlencode(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "resampleFreq": "daily",
            }
        )
        headers["Authorization"] = f"Token {api_key}"
        return f"https://api.tiingo.com/tiingo/daily/{path_target}/prices?{query}", headers

    params: dict[str, str | int] = {
        "series_id": target,
        "api_key": api_key,
        "file_type": "json",
    }
    if mode == CAPTURE_MODE_HISTORICAL:
        # FRED output_type=4 is the provider-defined "initial release only" view.
        # Bound the real-time period to the requested observation window through
        # capture date. This preserves the initial-release rows that could become
        # known for those observations while avoiding FRED's finite vintage-date
        # cap on centuries-wide real-time queries.
        params.update(
            {
                "observation_start": start_date.isoformat(),
                "observation_end": end_date.isoformat(),
                "realtime_start": start_date.isoformat(),
                "realtime_end": as_of.date().isoformat(),
                "output_type": FRED_INITIAL_RELEASE_OUTPUT_TYPE,
                "sort_order": "asc",
                "limit": 1000,
            }
        )
    else:
        params.update({"sort_order": "desc", "limit": 5})
    return (
        f"https://api.stlouisfed.org/fred/series/observations?{urlencode(params)}",
        headers,
    )


def _http_get(
    url: str,
    headers: dict[str, str],
    timeout_seconds: int = 15,
) -> tuple[bytes, str]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            body = response.read()
            content_type = str(response.headers.get("Content-Type") or "application/json")
    except HTTPError as exc:
        raise DataFeedIngestionError(f"PROVIDER_HTTP_{exc.code}") from None
    except (URLError, TimeoutError):
        raise DataFeedIngestionError("PROVIDER_NETWORK_ERROR") from None
    if not 200 <= status < 300:
        raise DataFeedIngestionError(f"PROVIDER_HTTP_{status}")
    if not body:
        raise DataFeedIngestionError("PROVIDER_EMPTY_RESPONSE")
    return body, content_type


def _put_immutable(
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    metadata: dict[str, str],
    client=None,
) -> None:
    s3 = client or _aws_client("s3")
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
            Metadata=metadata,
            IfNoneMatch="*",
        )
    except Exception as exc:  # noqa: BLE001 - boto client error classes are runtime-only.
        response = getattr(exc, "response", {})
        code = None
        if isinstance(response, dict):
            code = (response.get("Error") or {}).get("Code")
        if code in {"PreconditionFailed", "412"}:
            raise DataFeedIngestionError("IMMUTABLE_OBJECT_ALREADY_EXISTS") from None
        raise DataFeedIngestionError("S3_WRITE_FAILED") from None


def _log(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "trading_authorized": False,
        "live_trading_enabled": False,
        **fields,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def _smoke_result() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "daily-alpha-staging-data-feed-ingestion",
        "historical_backfill_supported": True,
        "capture_modes": sorted(CAPTURE_MODES),
        "max_historical_backfill_days": MAX_HISTORICAL_BACKFILL_DAYS,
        "fred_historical_output_type": FRED_INITIAL_RELEASE_OUTPUT_TYPE,
        "known_at_basis": KNOWN_AT_BASIS,
        "historical_known_at_backdating_authorized": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Fetch bounded staging research data and archive raw bytes plus a receipt."""
    if event.get("smoke_test") is True:
        return _smoke_result()

    provider = str(event.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise DataFeedIngestionError("PROVIDER_UNSUPPORTED")
    bucket = os.environ.get("RAW_EVIDENCE_BUCKET", "").strip()
    if not bucket:
        raise DataFeedIngestionError("RAW_EVIDENCE_BUCKET_REQUIRED")
    targets = _targets(provider, event)
    as_of = _now()
    capture_mode, start_date, end_date = _capture_window(event, as_of)
    request_id = str(getattr(context, "aws_request_id", "") or "manual").strip()
    records: list[dict[str, Any]] = []
    try:
        secret = _load_secret(provider)
        for ordinal, target in enumerate(targets, start=1):
            body, content_type = _http_get(
                *_request_spec(
                    provider,
                    target,
                    secret,
                    as_of,
                    capture_mode=capture_mode,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            digest = hashlib.sha256(body).hexdigest()
            date_path = as_of.strftime("%Y/%m/%d")
            safe_target = target.replace(".", "_").replace("^", "_")
            stem = f"{request_id}-{ordinal:02d}-{safe_target}"
            raw_key = f"data-feeds/staging/{provider}/raw/{date_path}/{stem}.json"
            receipt_key = f"data-feeds/staging/{provider}/receipts/{date_path}/{stem}.json"
            metadata = {
                "provider": provider,
                "target": target,
                "sha256": digest,
                "capture-mode": capture_mode,
                "known-at-basis": KNOWN_AT_BASIS,
                "historical-known-at-backdating-authorized": "false",
                "trading-authorized": "false",
                "live-trading-enabled": "false",
            }
            _put_immutable(
                bucket=bucket,
                key=raw_key,
                body=body,
                content_type=content_type.split(";", 1)[0],
                metadata=metadata,
            )
            receipt = {
                "schema": "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1",
                "provider": provider.upper(),
                "target": target,
                "captured_at": as_of.isoformat(),
                "capture_mode": capture_mode,
                "requested_start_date": start_date.isoformat(),
                "requested_end_date": end_date.isoformat(),
                "known_at_basis": KNOWN_AT_BASIS,
                "historical_known_at_backdating_authorized": False,
                "raw_s3_key": raw_key,
                "raw_sha256": digest,
                "raw_bytes": len(body),
                "trading_authorized": False,
                "live_trading_enabled": False,
            }
            receipt_body = (json.dumps(receipt, sort_keys=True) + "\n").encode()
            _put_immutable(
                bucket=bucket,
                key=receipt_key,
                body=receipt_body,
                content_type="application/json",
                metadata=metadata,
            )
            records.append(receipt)
            _log(
                "DATA_FEED_INGEST_SUCCESS",
                provider=provider.upper(),
                target=target,
                capture_mode=capture_mode,
                requested_start_date=start_date.isoformat(),
                requested_end_date=end_date.isoformat(),
                raw_s3_key=raw_key,
                receipt_s3_key=receipt_key,
                raw_bytes=len(body),
            )
    except DataFeedIngestionError as exc:
        _log(
            "DATA_FEED_INGEST_FAILURE",
            provider=provider.upper(),
            capture_mode=capture_mode,
            error_code=str(exc),
            request_id=request_id,
        )
        raise

    return {
        "ok": True,
        "service": "daily-alpha-staging-data-feed-ingestion",
        "provider": provider.upper(),
        "capture_mode": capture_mode,
        "requested_start_date": start_date.isoformat(),
        "requested_end_date": end_date.isoformat(),
        "target_count": len(targets),
        "records": records,
        "known_at_basis": KNOWN_AT_BASIS,
        "historical_known_at_backdating_authorized": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }