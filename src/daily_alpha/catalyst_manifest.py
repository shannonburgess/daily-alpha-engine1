"""Point-in-time manifest contract for public catalyst research events.

The manifest exists to make historical pre-catalyst research reconstructable without
lookahead. It is deliberately research-only and does not authorize a paper/live
signal or infer that a public event is investable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from .pre_catalyst import CatalystType, PublicCatalyst

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CatalystManifestRecord:
    ticker: str
    event_type: CatalystType
    event_date: date
    event_known_at: datetime
    source_url: str
    source_first_seen_at: datetime
    source_sha256: str
    source_title: str = ""

    @property
    def event_known_date(self) -> date:
        return self.event_known_at.date()

    @property
    def event_id(self) -> str:
        payload = "|".join(
            (
                self.ticker.upper().strip(),
                self.event_type.value,
                self.event_date.isoformat(),
                self.event_known_at.astimezone(timezone.utc).isoformat(),
                self.source_url.strip(),
                self.source_sha256,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_public_catalyst(self) -> PublicCatalyst:
        validate_manifest_record(self)
        return PublicCatalyst(
            ticker=self.ticker.upper().strip(),
            event_type=self.event_type,
            event_date=self.event_date,
            event_known_date=self.event_known_date,
            source_id=self.event_id,
        )


def validate_manifest_record(record: CatalystManifestRecord) -> None:
    ticker = record.ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker is required")
    if record.event_known_at.tzinfo is None or record.source_first_seen_at.tzinfo is None:
        raise ValueError("event/source timestamps must be timezone-aware")
    if record.event_known_at.date() > record.event_date:
        raise ValueError("event_known_at cannot be after event_date")
    if record.source_first_seen_at < record.event_known_at:
        raise ValueError("source_first_seen_at cannot precede the asserted public-known timestamp")
    parsed = urlparse(record.source_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("source_url must be an absolute HTTPS public source")
    if not _SHA256_RE.fullmatch(record.source_sha256.lower()):
        raise ValueError("source_sha256 must be a 64-character SHA-256 hex digest")


def record_from_dict(payload: dict[str, str]) -> CatalystManifestRecord:
    required = {
        "ticker",
        "event_type",
        "event_date",
        "event_known_at",
        "source_url",
        "source_first_seen_at",
        "source_sha256",
    }
    missing = sorted(key for key in required if not str(payload.get(key, "")).strip())
    if missing:
        raise ValueError(f"missing catalyst manifest fields: {missing}")

    record = CatalystManifestRecord(
        ticker=str(payload["ticker"]).upper().strip(),
        event_type=CatalystType(str(payload["event_type"]).strip()),
        event_date=date.fromisoformat(str(payload["event_date"])[:10]),
        event_known_at=_parse_timestamp(str(payload["event_known_at"])),
        source_url=str(payload["source_url"]).strip(),
        source_first_seen_at=_parse_timestamp(str(payload["source_first_seen_at"])),
        source_sha256=str(payload["source_sha256"]).lower().strip(),
        source_title=str(payload.get("source_title", "")).strip(),
    )
    validate_manifest_record(record)
    return record


def _parse_timestamp(raw: str) -> datetime:
    normalized = raw.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone/offset")
    return parsed
