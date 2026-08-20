"""Validate the latest canonical Daily Alpha shortlist for paper-shadow operations."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_UNIVERSE_AGE_HOURS = 18.0


def _parse_aware(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _load_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _load_list(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise TypeError(f"{path} must contain a JSON object list")
    return value


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "rank": row.get("rank"),
            "symbol": row.get("symbol"),
            "ovtlyr_status": row.get("ovtlyr_status"),
            "score": row.get("score"),
        }
        for row in rows
    ]
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def summarize(
    summary: dict[str, Any],
    shortlist: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_hours: float = MAX_UNIVERSE_AGE_HOURS,
) -> dict[str, Any]:
    """Return fail-closed health evidence for the canonical actionable universe."""
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")

    violations: list[str] = []
    generated_at: datetime | None = None
    try:
        generated_at = _parse_aware(summary.get("generated_at"), "generated_at")
    except (TypeError, ValueError):
        violations.append("UNIVERSE_GENERATED_AT_INVALID")

    age_hours: float | None = None
    if generated_at is not None:
        age_hours = (timestamp - generated_at).total_seconds() / 3600.0
        if age_hours < 0:
            violations.append("UNIVERSE_GENERATED_AT_IN_FUTURE")
        elif age_hours > max_age_hours:
            violations.append("UNIVERSE_STALE")

    if summary.get("trading_authorized") is not False:
        violations.append("UNIVERSE_TRADING_AUTHORIZED_NOT_FALSE")
    if summary.get("live_trading_enabled") is not False:
        violations.append("UNIVERSE_LIVE_TRADING_NOT_FALSE")

    expected_count = summary.get("actionable_ranked_count")
    if not isinstance(expected_count, int) or expected_count < 0:
        violations.append("UNIVERSE_ACTIONABLE_COUNT_INVALID")
    elif expected_count != len(shortlist):
        violations.append("UNIVERSE_SHORTLIST_COUNT_MISMATCH")

    symbols: list[str] = []
    seen: set[str] = set()
    for position, row in enumerate(shortlist, start=1):
        symbol = str(row.get("symbol") or "").strip().upper()
        rank = row.get("rank")
        if not symbol:
            violations.append(f"UNIVERSE_SYMBOL_MISSING:{position}")
            continue
        if symbol in seen:
            violations.append(f"UNIVERSE_DUPLICATE_SYMBOL:{symbol}")
        seen.add(symbol)
        symbols.append(symbol)
        if rank != position:
            violations.append(f"UNIVERSE_RANK_SEQUENCE_INVALID:{symbol}")

    current_file = str(summary.get("current_file") or "").strip()
    if not current_file:
        violations.append("UNIVERSE_CURRENT_SOURCE_MISSING")

    return {
        "ok": not violations,
        "snapshot_at": timestamp.isoformat(),
        "generated_at": generated_at.isoformat() if generated_at else None,
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "max_age_hours": max_age_hours,
        "current_source": current_file or None,
        "actionable_count": len(shortlist),
        "symbols": symbols,
        "universe_fingerprint_sha256": _fingerprint(shortlist),
        "violations": sorted(set(violations)),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "tradingview_private_alert_universe_observable": False,
        "tradingview_platform_limitation": (
            "The connected control loop has no supported TradingView API for reading "
            "the private per-alert symbol/watchlist configuration. Canonical universe "
            "freshness and identity are monitored automatically; TradingView remains "
            "frozen unless a verified defect requires manual intervention."
        ),
    }


def render_markdown(status: dict[str, Any]) -> str:
    state = "PASS" if status["ok"] else "FAIL-CLOSED"
    lines = [
        "",
        "### Canonical actionable-universe health",
        f"Status: **{state}**  ",
        f"Current source: `{status['current_source'] or 'missing'}`  ",
        f"Generated at: `{status['generated_at'] or 'invalid'}`  ",
        f"Age: **{status['age_hours']}h** (max {status['max_age_hours']}h)  ",
        f"Actionable symbols: **{status['actionable_count']}**  ",
        f"Universe SHA-256: `{status['universe_fingerprint_sha256']}`  ",
        "Safety: `trading_authorized=false`, `live_trading_enabled=false`",
    ]
    if status["violations"]:
        lines.extend(
            ["Universe violations:", *[f"- `{item}`" for item in status["violations"]]]
        )
    lines.extend(
        [
            "",
            "TradingView private alert/watchlist membership is not readable through a "
            "supported API. The canonical universe is monitored automatically and the "
            "validated SH24/SH25 TradingView configuration remains frozen.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True)
    parser.add_argument("--shortlist", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--max-age-hours", type=float, default=MAX_UNIVERSE_AGE_HOURS)
    args = parser.parse_args()

    status = summarize(
        _load_object(args.summary),
        _load_list(args.shortlist),
        max_age_hours=args.max_age_hours,
    )
    Path(args.output_json).write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(status))
    return 0 if status["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
