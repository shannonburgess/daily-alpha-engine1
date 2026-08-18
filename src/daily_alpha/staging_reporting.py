"""Publish readable Daily Alpha staging outputs from current research and paper data."""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import InstrumentSelected
from .newsletter import NewsletterRenderer
from .research_report import DailyResearchPacket, ResearchCandidate, ResearchDisposition


class StagingReportError(RuntimeError):
    """Raised when a staging report cannot be built or published safely."""


class AwsStagingReportPublisher:
    """Read the latest staging research + paper ledger and publish daily outputs."""

    DEFAULT_BUCKET = "daily-alpha-staging-490809405132-us-east-2"
    DEFAULT_TABLE = "daily-alpha-paper-ledger-staging"
    DEFAULT_ACCOUNT = "paper-staging"
    SHORTLIST_PREFIX = "ovtlyr/shortlist/latest"
    OUTPUT_PREFIX = "daily-alpha/outputs"

    def __init__(
        self,
        *,
        s3_client: Any | None = None,
        dynamodb_client: Any | None = None,
        bucket: str | None = None,
        table_name: str | None = None,
        account_id: str | None = None,
    ) -> None:
        self.bucket = (
            bucket or os.getenv("DAILY_ALPHA_STAGING_BUCKET") or self.DEFAULT_BUCKET
        ).strip()
        self.table_name = (
            table_name
            or os.getenv("DAILY_ALPHA_PAPER_LEDGER_TABLE")
            or self.DEFAULT_TABLE
        ).strip()
        self.account_id = (
            account_id
            or os.getenv("DAILY_ALPHA_PAPER_ACCOUNT_ID")
            or self.DEFAULT_ACCOUNT
        ).strip()
        if not self.bucket or not self.table_name or not self.account_id:
            raise StagingReportError("STAGING_REPORT_CONFIGURATION_INVALID")

        if s3_client is None or dynamodb_client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - Lambda includes boto3
                raise StagingReportError("BOTO3_UNAVAILABLE") from exc
            if s3_client is None:
                s3_client = boto3.client("s3")
            if dynamodb_client is None:
                dynamodb_client = boto3.client("dynamodb")
        self.s3 = s3_client
        self.dynamodb = dynamodb_client

    def publish(
        self,
        *,
        session: str = "MANUAL",
        now: datetime | None = None,
        run_id: str = "lambda",
    ) -> dict[str, Any]:
        timestamp = _aware(now or datetime.now(UTC))
        local = timestamp.astimezone(ZoneInfo("America/Los_Angeles"))
        normalized_session = _session(session)

        shortlist = self._json_object(f"{self.SHORTLIST_PREFIX}/shortlist.json")
        if not isinstance(shortlist, list):
            raise StagingReportError("SHORTLIST_JSON_MUST_BE_ARRAY")
        summary = self._json_object(f"{self.SHORTLIST_PREFIX}/summary.json")
        if not isinstance(summary, Mapping):
            raise StagingReportError("SHORTLIST_SUMMARY_MUST_BE_OBJECT")
        sector_rotation = self._json_object(
            f"{self.SHORTLIST_PREFIX}/sector_rotation.json"
        )
        if not isinstance(sector_rotation, list):
            raise StagingReportError("SECTOR_ROTATION_JSON_MUST_BE_ARRAY")
        shortlist_csv = self._bytes(f"{self.SHORTLIST_PREFIX}/shortlist.csv")

        ledger_rows = self._paper_ledger_rows()
        ledger_csv = _rows_to_csv(
            ledger_rows,
            preferred=(
                "pk",
                "sk",
                "event",
                "action",
                "signal_id",
                "symbol",
                "instrument",
                "state",
                "trade_id",
                "disposition",
                "reason",
                "runner_stage",
                "position_fraction",
                "trade_json",
                "result_json",
            ),
        ).encode("utf-8")
        sector_csv = _rows_to_csv(sector_rotation).encode("utf-8")

        packet = _packet_from_shortlist(
            shortlist,
            report_date=local.date().isoformat(),
            run_id=run_id,
            generated_at=timestamp.isoformat(),
        )
        rendered = NewsletterRenderer().render(packet)
        if not rendered.quality_passed:
            raise StagingReportError(
                "NEWSLETTER_QUALITY_FAILED:" + ",".join(rendered.quality_warnings)
            )

        date_key = local.date().isoformat()
        stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
        history_prefix = (
            f"{self.OUTPUT_PREFIX}/history/{date_key}/{normalized_session.lower()}-{stamp}"
        )
        latest_prefix = f"{self.OUTPUT_PREFIX}/latest"

        outputs: dict[str, tuple[bytes, str]] = {
            "newsletter.html": (rendered.html.encode("utf-8"), "text/html; charset=utf-8"),
            "research_shortlist.csv": (shortlist_csv, "text/csv; charset=utf-8"),
            "paper_ledger.csv": (ledger_csv, "text/csv; charset=utf-8"),
            "sector_rotation.csv": (sector_csv, "text/csv; charset=utf-8"),
        }

        manifest = {
            "report_date": date_key,
            "session": normalized_session,
            "generated_at": timestamp.isoformat(),
            "run_id": run_id,
            "research_candidate_count": len(shortlist),
            "qualified_option_count": int(summary.get("qualified_option_count", 0) or 0),
            "paper_ledger_row_count": len(ledger_rows),
            "open_paper_position_count": sum(
                "#POSITION#" in str(row.get("pk", "")) and row.get("sk") == "OPEN"
                for row in ledger_rows
            ),
            "newsletter_quality_passed": rendered.quality_passed,
            "newsletter_sections": list(rendered.sections),
            "live_trading_enabled": False,
            "publication": "STAGING_RESEARCH_AND_PAPER_ONLY",
        }
        outputs["report_manifest.json"] = (
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "application/json",
        )

        published: dict[str, str] = {}
        for name, (body, content_type) in outputs.items():
            history_key = f"{history_prefix}/{name}"
            latest_key = f"{latest_prefix}/{name}"
            self._put(history_key, body, content_type)
            self._put(latest_key, body, content_type)
            published[name] = latest_key

        return {
            "ok": True,
            "status": "PUBLISHED",
            "bucket": self.bucket,
            "session": normalized_session,
            "report_date": date_key,
            "history_prefix": history_prefix,
            "outputs": published,
            "manifest": manifest,
            "live_trading_enabled": False,
        }

    def _bytes(self, key: str) -> bytes:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"].read()
        except Exception as exc:
            raise StagingReportError(f"S3_READ_FAILED:{key}") from exc
        if not isinstance(body, (bytes, bytearray)):
            raise StagingReportError(f"S3_BODY_INVALID:{key}")
        return bytes(body)

    def _json_object(self, key: str) -> Any:
        try:
            return json.loads(self._bytes(key).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StagingReportError(f"S3_JSON_INVALID:{key}") from exc

    def _paper_ledger_rows(self) -> list[dict[str, Any]]:
        prefix = f"ACCOUNT#{self.account_id}#"
        kwargs: dict[str, Any] = {
            "TableName": self.table_name,
            "FilterExpression": "begins_with(pk, :prefix)",
            "ExpressionAttributeValues": {":prefix": {"S": prefix}},
        }
        rows: list[dict[str, Any]] = []
        while True:
            try:
                response = self.dynamodb.scan(**kwargs)
            except Exception as exc:
                raise StagingReportError("DYNAMODB_SCAN_FAILED") from exc
            for item in response.get("Items", []):
                if isinstance(item, Mapping):
                    rows.append({str(key): _ddb_value(value) for key, value in item.items()})
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        rows.sort(key=lambda row: (str(row.get("pk", "")), str(row.get("sk", ""))))
        return rows

    def _put(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except Exception as exc:
            raise StagingReportError(f"S3_WRITE_FAILED:{key}") from exc


def _packet_from_shortlist(
    rows: list[Any],
    *,
    report_date: str,
    run_id: str,
    generated_at: str,
) -> DailyResearchPacket:
    candidates: list[ResearchCandidate] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        orats_status = str(raw.get("orats_status", "")).upper()
        orats_reason = str(raw.get("orats_reason", "") or "RESEARCH_ONLY")
        has_option = bool(str(raw.get("selected_expiration", "")).strip())
        if orats_status == "DATA_ERROR":
            disposition = ResearchDisposition.DATA_ERROR
            instrument = InstrumentSelected.NONE
            risk_status = "NOT_EVALUATED"
            data_status = "DATA_ERROR"
        else:
            disposition = ResearchDisposition.WATCHLIST
            instrument = InstrumentSelected.OPTION if has_option else InstrumentSelected.NONE
            risk_status = "NOT_EVALUATED"
            data_status = "PASS"

        reasons = [
            f"OVTLYR={raw.get('ovtlyr_status', 'UNKNOWN')!s}",
            f"ORATS={orats_reason}",
            f"RANK_SCORE={raw.get('score', 0)}",
        ]
        smart_bonus = float(raw.get("smart_money_bonus", 0) or 0)
        policy_bonus = float(raw.get("trump_policy_bonus", 0) or 0)
        if smart_bonus > 0:
            reasons.append(f"SMART_MONEY_BONUS=+{smart_bonus:.1f}")
        if policy_bonus > 0:
            reasons.append(f"POLICY_WATCH_BONUS=+{policy_bonus:.1f}")

        contract = None
        if has_option:
            contract = (
                f"{raw.get('selected_expiration')} "
                f"{raw.get('selected_option_type')} "
                f"{raw.get('selected_strike')}"
            )
        candidates.append(
            ResearchCandidate(
                symbol=symbol,
                disposition=disposition,
                instrument=instrument,
                signal_label=str(
                    raw.get("display_label") or raw.get("ovtlyr_status") or "WATCH"
                ),
                thesis=str(
                    raw.get("classification_reason")
                    or "Ranked Daily Alpha research candidate."
                ),
                reasons=tuple(reasons),
                risk_status=risk_status,
                data_status=data_status,
                sector=str(raw.get("sector") or "UNKNOWN"),
                option_contract=contract,
                flow_classification=(
                    "UNUSUAL_CONFIRMATION"
                    if raw.get("unusual_options_activity") is True
                    else ("NORMAL" if orats_status == "ENRICHED" else None)
                ),
                option_volume=int(raw.get("selected_volume", 0) or 0),
                option_open_interest=int(raw.get("selected_open_interest", 0) or 0),
                option_volume_oi_ratio=(
                    round(
                        float(raw.get("selected_volume", 0) or 0)
                        / float(raw.get("selected_open_interest", 0) or 1),
                        4,
                    )
                    if int(raw.get("selected_open_interest", 0) or 0) > 0
                    else None
                ),
                option_bid=(
                    float(raw.get("selected_bid", 0) or 0) if has_option else None
                ),
                option_ask=(
                    float(raw.get("selected_ask", 0) or 0) if has_option else None
                ),
            )
        )

    return DailyResearchPacket(
        report_date=report_date,
        run_id=run_id,
        methodology_version="DAILY_ALPHA_V1_9_STAGING",
        generated_at=generated_at,
        market_regime="RESEARCH_ONLY",
        candidates=tuple(candidates),
    )


def _rows_to_csv(
    rows: list[Any],
    *,
    preferred: tuple[str, ...] = (),
) -> str:
    normalized = [dict(row) for row in rows if isinstance(row, Mapping)]
    fields: list[str] = list(preferred)
    extras = sorted({str(key) for row in normalized for key in row if str(key) not in fields})
    fields.extend(extras)
    if not fields:
        fields = ["status"]
        normalized = [{"status": "NO_ROWS"}]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in normalized:
        writer.writerow({key: _csv_value(row.get(key)) for key in fields})
    return output.getvalue()


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "" if value is None else value


def _ddb_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    if "S" in value:
        return value["S"]
    if "N" in value:
        text = str(value["N"])
        try:
            is_integer = text.isdigit() or (text.startswith("-") and text[1:].isdigit())
            return int(text) if is_integer else float(text)
        except ValueError:
            return text
    if "BOOL" in value:
        return bool(value["BOOL"])
    if value.get("NULL") is True:
        return None
    if "L" in value:
        return [_ddb_value(item) for item in value["L"]]
    if "M" in value:
        return {str(key): _ddb_value(item) for key, item in value["M"].items()}
    return json.dumps(dict(value), sort_keys=True)


def _session(value: str) -> str:
    normalized = str(value or "MANUAL").strip().upper().replace("-", "_")
    if normalized not in {"MORNING", "POST_MARKET", "MANUAL"}:
        raise StagingReportError("INVALID_REPORT_SESSION")
    return normalized


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
