"""Canonical company-equity liquidity evidence and PAPER execution gate.

Issue #218 requires individual companies to have current 30-day average daily
share volume strictly greater than 1.5M shares before they can be actionable.
ETFs remain on their separate liquidity/capacity path.  This module is fail-closed
and never authorizes live trading.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

CANONICAL_COMPANY_MIN_AVERAGE_VOLUME = 1_500_000.0
CANONICAL_LIQUIDITY_MAX_SOURCE_AGE_DAYS = 4
DEFAULT_STAGING_BUCKET = "daily-alpha-staging-490809405132-us-east-2"
DEFAULT_LIQUIDITY_PREFIX = "ovtlyr/shortlist/latest"
_DATE_PATTERN = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class LiquidityDecision:
    symbol: str
    allowed: bool
    security_type: str
    reason: str
    detail: str
    average_daily_share_volume_30d: float | None
    source_date: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreparedLiquidityUniverse:
    previous_path: Path
    current_path: Path
    snapshot_path: Path
    company_eligible_count: int
    company_filtered_count: int
    company_missing_volume_count: int
    etf_count: int


class LiquidityEvidenceStore(Protocol):
    def evaluate(self, symbol: str, *, as_of: datetime) -> LiquidityDecision: ...


def prepare_actionable_liquidity_inputs(
    previous_path: str | Path,
    current_path: str | Path,
    *,
    output_dir: str | Path,
    as_of: datetime,
    threshold: float = CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
) -> PreparedLiquidityUniverse:
    """Filter company rows while preserving ETF rows for their separate rules.

    Both input CSVs keep their original headers and filenames in a staging-only
    working directory.  Company rows pass only when their own day's 30-day average
    share volume is strictly greater than ``threshold``.  ETF rows are retained
    without applying the company-share-volume threshold.
    """
    _require_aware(as_of, "as_of")
    if threshold <= 0:
        raise ValueError("threshold must be positive")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    previous = Path(previous_path)
    current = Path(current_path)
    previous_filtered = destination / previous.name
    current_filtered = destination / current.name

    _filter_csv(previous, previous_filtered, threshold=threshold)
    current_rows, current_headers = _read_csv(current)
    current_classified = [_classify_row(row, current_headers, threshold) for row in current_rows]
    _write_filtered_rows(
        current_filtered,
        current_headers,
        [row for row, evidence in zip(current_rows, current_classified, strict=True) if evidence["actionable_liquidity"]],
    )

    source_date = _source_date(current.name)
    snapshot = {
        "schema_version": "2026-08-19-v1",
        "source": "OVTLYR_30_DAY_AVG_VOLUME",
        "source_file": current.name,
        "source_date": source_date.isoformat(),
        "generated_at": as_of.astimezone(UTC).isoformat(),
        "company_min_average_volume": threshold,
        "company_threshold_semantics": "STRICTLY_GREATER_THAN",
        "rows": sorted(current_classified, key=lambda item: item["symbol"]),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    snapshot_path = destination / "company_liquidity_eligibility.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return PreparedLiquidityUniverse(
        previous_path=previous_filtered,
        current_path=current_filtered,
        snapshot_path=snapshot_path,
        company_eligible_count=sum(
            row["security_type"] == "COMPANY_EQUITY" and row["status"] == "ELIGIBLE"
            for row in current_classified
        ),
        company_filtered_count=sum(
            row["security_type"] == "COMPANY_EQUITY"
            and row["status"] == "LIQUIDITY_FILTERED"
            and row["detail"] == "AT_OR_BELOW_THRESHOLD"
            for row in current_classified
        ),
        company_missing_volume_count=sum(
            row["security_type"] == "COMPANY_EQUITY"
            and row["status"] == "LIQUIDITY_FILTERED"
            and row["detail"] == "MISSING_OR_NONPOSITIVE_VOLUME"
            for row in current_classified
        ),
        etf_count=sum(row["security_type"] == "ETF" for row in current_classified),
    )


def evaluate_persisted_liquidity(
    symbol: str,
    *,
    snapshot: Mapping[str, Any],
    shortlist: list[Mapping[str, Any]],
    summary: Mapping[str, Any],
    as_of: datetime,
    max_source_age_days: int = CANONICAL_LIQUIDITY_MAX_SOURCE_AGE_DAYS,
) -> LiquidityDecision:
    """Evaluate immutable S3-published liquidity + actionable-universe evidence."""
    _require_aware(as_of, "as_of")
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise ValueError("symbol is required")
    if max_source_age_days < 0:
        raise ValueError("max_source_age_days must be non-negative")

    if snapshot.get("trading_authorized") is not False or snapshot.get("live_trading_enabled") is not False:
        return _filtered(ticker, "UNKNOWN", "LIQUIDITY_EVIDENCE_SAFETY_FLAGS_INVALID")
    threshold = _positive_float(snapshot.get("company_min_average_volume"))
    if threshold != CANONICAL_COMPANY_MIN_AVERAGE_VOLUME:
        return _filtered(ticker, "UNKNOWN", "LIQUIDITY_THRESHOLD_CONTRACT_MISMATCH")
    if snapshot.get("company_threshold_semantics") != "STRICTLY_GREATER_THAN":
        return _filtered(ticker, "UNKNOWN", "LIQUIDITY_THRESHOLD_SEMANTICS_INVALID")

    source_file = str(snapshot.get("source_file") or "")
    if source_file != str(summary.get("current_file") or ""):
        return _filtered(ticker, "UNKNOWN", "LIQUIDITY_SHORTLIST_SOURCE_MISMATCH")
    try:
        source_date = date.fromisoformat(str(snapshot.get("source_date") or ""))
    except ValueError:
        return _filtered(ticker, "UNKNOWN", "LIQUIDITY_SOURCE_DATE_INVALID")
    local_date = as_of.astimezone(_NEW_YORK).date()
    age_days = (local_date - source_date).days
    if age_days < 0 or age_days > max_source_age_days:
        return _filtered(
            ticker,
            "UNKNOWN",
            "LIQUIDITY_EVIDENCE_STALE",
            source_date=source_date.isoformat(),
        )

    generated_at = _parse_aware(snapshot.get("generated_at"))
    if generated_at is None or generated_at > as_of.astimezone(UTC):
        return _filtered(
            ticker,
            "UNKNOWN",
            "LIQUIDITY_GENERATED_AT_INVALID",
            source_date=source_date.isoformat(),
        )

    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        return _filtered(ticker, "UNKNOWN", "LIQUIDITY_ROWS_MISSING", source_date=source_date.isoformat())
    matches = [row for row in rows if isinstance(row, Mapping) and str(row.get("symbol", "")).upper() == ticker]
    if len(matches) != 1:
        return _filtered(
            ticker,
            "UNKNOWN",
            "LIQUIDITY_SYMBOL_EVIDENCE_MISSING_OR_DUPLICATE",
            source_date=source_date.isoformat(),
        )
    row = matches[0]
    security_type = str(row.get("security_type") or "UNKNOWN").upper()
    volume = _nonnegative_float_or_none(row.get("average_daily_share_volume_30d"))

    if security_type == "COMPANY_EQUITY":
        if row.get("status") != "ELIGIBLE" or volume is None or volume <= threshold:
            return _filtered(
                ticker,
                security_type,
                str(row.get("detail") or "AT_OR_BELOW_OR_MISSING_VOLUME"),
                volume=volume,
                source_date=source_date.isoformat(),
            )
    elif security_type == "ETF":
        # Explicitly do not apply the company share-volume threshold to ETFs.
        pass
    else:
        return _filtered(
            ticker,
            security_type,
            "SECURITY_TYPE_UNRESOLVED",
            volume=volume,
            source_date=source_date.isoformat(),
        )

    shortlist_symbols = {
        str(item.get("symbol", "")).strip().upper()
        for item in shortlist
        if isinstance(item, Mapping)
    }
    if ticker not in shortlist_symbols:
        return LiquidityDecision(
            symbol=ticker,
            allowed=False,
            security_type=security_type,
            reason="ACTIONABLE_UNIVERSE_FILTERED",
            detail="SYMBOL_NOT_IN_CURRENT_RANKED_SHORTLIST",
            average_daily_share_volume_30d=volume,
            source_date=source_date.isoformat(),
        )

    return LiquidityDecision(
        symbol=ticker,
        allowed=True,
        security_type=security_type,
        reason="ELIGIBLE" if security_type == "COMPANY_EQUITY" else "ETF_SEPARATE_RULES",
        detail=(
            "COMPANY_VOLUME_STRICTLY_ABOVE_1_5M"
            if security_type == "COMPANY_EQUITY"
            else "COMPANY_SHARE_VOLUME_GATE_NOT_APPLIED"
        ),
        average_daily_share_volume_30d=volume,
        source_date=source_date.isoformat(),
    )


class S3ActionableLiquidityStore:
    """Read the latest canonical liquidity evidence and shortlist from staging S3."""

    def __init__(
        self,
        *,
        s3_client: Any | None = None,
        bucket: str | None = None,
        prefix: str | None = None,
        max_source_age_days: int = CANONICAL_LIQUIDITY_MAX_SOURCE_AGE_DAYS,
    ) -> None:
        if s3_client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - Lambda includes boto3
                raise RuntimeError("BOTO3_UNAVAILABLE") from exc
            s3_client = boto3.client("s3")
        self.s3_client = s3_client
        self.bucket = (bucket or os.getenv("DAILY_ALPHA_STAGING_BUCKET") or DEFAULT_STAGING_BUCKET).strip()
        self.prefix = (prefix or os.getenv("DAILY_ALPHA_LIQUIDITY_PREFIX") or DEFAULT_LIQUIDITY_PREFIX).strip("/")
        self.max_source_age_days = max_source_age_days

    def evaluate(self, symbol: str, *, as_of: datetime) -> LiquidityDecision:
        snapshot = self._json("company_liquidity_eligibility.json")
        shortlist = self._json("shortlist.json")
        summary = self._json("summary.json")
        if not isinstance(snapshot, Mapping) or not isinstance(summary, Mapping) or not isinstance(shortlist, list):
            raise TypeError("LIQUIDITY_EVIDENCE_PAYLOAD_INVALID")
        return evaluate_persisted_liquidity(
            symbol,
            snapshot=snapshot,
            shortlist=[item for item in shortlist if isinstance(item, Mapping)],
            summary=summary,
            as_of=as_of,
            max_source_age_days=self.max_source_age_days,
        )

    def _json(self, name: str) -> Any:
        key = f"{self.prefix}/{name}"
        response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
        body = response.get("Body") if isinstance(response, Mapping) else None
        raw = body.read() if hasattr(body, "read") else body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"LIQUIDITY_EVIDENCE_EMPTY:{name}")
        return json.loads(raw)


class LiquidityGatedPaperExecutor:
    """Gate new PAPER entries with persisted liquidity/universe evidence.

    PARTIAL/EXIT management is never blocked by a later liquidity deterioration.
    Existing ETF behavior delegates to the downstream separate liquidity/capacity
    rules after the snapshot confirms that the symbol is an ETF.
    """

    def __init__(self, delegate: Any, store: LiquidityEvidenceStore) -> None:
        self.delegate = delegate
        self.store = store

    @property
    def ledger(self) -> Any:
        return self.delegate.ledger

    def execute(self, ingress: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        if str(ingress.get("action", "")).upper() != "ENTRY_LONG":
            return self.delegate.execute(ingress, now=timestamp)
        decision = self._decision(ingress, timestamp)
        if not decision.allowed:
            return _blocked_result(ingress, decision)
        return self.delegate.execute(ingress, now=timestamp)

    def replay_armed(self, ingress: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        if str(ingress.get("action", "")).upper() != "ENTRY_LONG":
            return self.delegate.replay_armed(ingress, now=timestamp)
        decision = self._decision(ingress, timestamp)
        if not decision.allowed:
            return _blocked_result(ingress, decision)
        return self.delegate.replay_armed(ingress, now=timestamp)

    def _decision(self, ingress: Mapping[str, Any], as_of: datetime) -> LiquidityDecision:
        symbol = str(ingress.get("symbol", "")).strip().upper()
        try:
            return self.store.evaluate(symbol, as_of=as_of)
        except Exception as exc:  # noqa: BLE001 - execution boundary fails closed
            return LiquidityDecision(
                symbol=symbol,
                allowed=False,
                security_type="UNKNOWN",
                reason="LIQUIDITY_FILTERED",
                detail=f"LIQUIDITY_EVIDENCE_DATA_ERROR:{type(exc).__name__}",
                average_daily_share_volume_30d=None,
                source_date=None,
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


def _blocked_result(ingress: Mapping[str, Any], decision: LiquidityDecision) -> dict[str, Any]:
    reason = decision.reason
    if reason not in {"LIQUIDITY_FILTERED", "ACTIONABLE_UNIVERSE_FILTERED"}:
        reason = "LIQUIDITY_FILTERED"
    return {
        "disposition": "NO_TRADE",
        "reason": reason,
        "action": str(ingress.get("action", "")).upper(),
        "symbol": str(ingress.get("symbol", "")).upper(),
        "paper_execution_triggered": False,
        "paper_ledger_updated": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
        "paper": {},
        "context": {"liquidity_gate": decision.to_dict()},
    }


def _filter_csv(source: Path, destination: Path, *, threshold: float) -> None:
    rows, headers = _read_csv(source)
    evidence = [_classify_row(row, headers, threshold) for row in rows]
    _write_filtered_rows(
        destination,
        headers,
        [row for row, item in zip(rows, evidence, strict=True) if item["actionable_liquidity"]],
    )


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        return [dict(row) for row in reader], list(reader.fieldnames)


def _write_filtered_rows(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _classify_row(row: Mapping[str, str], headers: list[str], threshold: float) -> dict[str, Any]:
    symbol = _row_value(row, headers, "ticker", "symbol").strip().upper()
    security_type = _security_type(row, headers)
    volume = _parse_volume(_row_value(row, headers, "30_day_avg_volume", "average_volume", "30_day_avg_vol"))
    if security_type == "ETF":
        status = "ETF_SEPARATE_RULES"
        detail = "COMPANY_SHARE_VOLUME_GATE_NOT_APPLIED"
        actionable = True
    elif volume is None or volume <= 0:
        status = "LIQUIDITY_FILTERED"
        detail = "MISSING_OR_NONPOSITIVE_VOLUME"
        actionable = False
    elif volume <= threshold:
        status = "LIQUIDITY_FILTERED"
        detail = "AT_OR_BELOW_THRESHOLD"
        actionable = False
    else:
        status = "ELIGIBLE"
        detail = "STRICTLY_ABOVE_THRESHOLD"
        actionable = True
    return {
        "symbol": symbol,
        "security_type": security_type,
        "average_daily_share_volume_30d": volume,
        "status": status,
        "detail": detail,
        "actionable_liquidity": actionable,
    }


def _security_type(row: Mapping[str, str], headers: list[str]) -> str:
    explicit = _row_value(
        row,
        headers,
        "security_type",
        "asset_type",
        "instrument_type",
        "security",
        "type",
    ).upper()
    industry = _row_value(row, headers, "industry").upper()
    values = {explicit, industry}
    values.update(str(value or "").strip().upper() for value in row.values())
    if any(value in {"ETF", "EXCHANGE TRADED FUND", "EXCHANGE-TRADED FUND"} for value in values):
        return "ETF"
    return "COMPANY_EQUITY"


def _row_value(row: Mapping[str, str], headers: list[str], *names: str) -> str:
    normalized = {_normalize(header): header for header in headers}
    for name in names:
        header = normalized.get(_normalize(name))
        if header is not None:
            return str(row.get(header) or "")
    return ""


def _normalize(value: str) -> str:
    return "_".join("".join(char.lower() if char.isalnum() else " " for char in str(value)).split())


def _parse_volume(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _source_date(filename: str) -> date:
    match = _DATE_PATTERN.search(filename)
    if not match:
        raise ValueError("Current OVTLYR filename has no YYYY-MM-DD source date")
    return date.fromisoformat(match.group(1))


def _filtered(
    symbol: str,
    security_type: str,
    detail: str,
    *,
    volume: float | None = None,
    source_date: str | None = None,
) -> LiquidityDecision:
    return LiquidityDecision(
        symbol=symbol,
        allowed=False,
        security_type=security_type,
        reason="LIQUIDITY_FILTERED",
        detail=detail,
        average_daily_share_volume_30d=volume,
        source_date=source_date,
    )


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _nonnegative_float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _parse_aware(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> datetime:
    _require_aware(value, "datetime")
    return value.astimezone(UTC)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
