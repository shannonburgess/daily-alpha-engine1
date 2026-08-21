"""Read-only staging health checks for the canonical company liquidity gate."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COMPANY_MIN_AVERAGE_VOLUME = 1_500_000.0
LIQUIDITY_EVIDENCE_FILE = "company_liquidity_eligibility.json"
LIQUIDITY_GATE_ROLLOUT_AT = datetime.fromisoformat("2026-08-20T03:54:57+00:00")


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


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize(
    summary: dict[str, Any],
    shortlist: list[dict[str, Any]],
    *,
    evidence: dict[str, Any] | None,
    evidence_found: bool,
    rollout_at: datetime = LIQUIDITY_GATE_ROLLOUT_AT,
) -> dict[str, Any]:
    """Validate the staged issue #218 artifact without forcing pre-rollout failures."""
    violations: list[str] = []
    try:
        generated_at = _parse_aware(summary.get("generated_at"), "generated_at")
    except (TypeError, ValueError):
        generated_at = None
        violations.append("LIQUIDITY_MONITOR_SUMMARY_GENERATED_AT_INVALID")

    rollout = rollout_at.astimezone(UTC)
    post_rollout_publication = generated_at is not None and generated_at >= rollout

    if not post_rollout_publication and not evidence_found:
        return {
            "ok": not violations,
            "state": "PENDING_FIRST_POST_MERGE_PUBLICATION",
            "summary_generated_at": generated_at.isoformat() if generated_at else None,
            "rollout_at": rollout.isoformat(),
            "evidence_found": False,
            "current_source": summary.get("current_file"),
            "actionable_count": len(shortlist),
            "eligible_company_count": None,
            "filtered_company_count": None,
            "missing_volume_company_count": None,
            "etf_count": None,
            "violations": sorted(set(violations)),
            "trading_authorized": False,
            "live_trading_enabled": False,
        }

    if not evidence_found or not isinstance(evidence, dict):
        violations.append("LIQUIDITY_EVIDENCE_MISSING_AFTER_ROLLOUT")
        evidence = {}

    if summary.get("company_average_volume_gate_enabled") is not True:
        violations.append("LIQUIDITY_SUMMARY_GATE_NOT_ENABLED")
    summary_threshold = _float(summary.get("company_min_average_volume"))
    if summary_threshold != COMPANY_MIN_AVERAGE_VOLUME:
        violations.append("LIQUIDITY_SUMMARY_THRESHOLD_MISMATCH")
    if summary.get("liquidity_evidence_file") != LIQUIDITY_EVIDENCE_FILE:
        violations.append("LIQUIDITY_SUMMARY_EVIDENCE_FILE_MISMATCH")

    if evidence.get("trading_authorized") is not False:
        violations.append("LIQUIDITY_EVIDENCE_TRADING_AUTHORIZED_NOT_FALSE")
    if evidence.get("live_trading_enabled") is not False:
        violations.append("LIQUIDITY_EVIDENCE_LIVE_TRADING_NOT_FALSE")
    if evidence.get("company_threshold_semantics") != "STRICTLY_GREATER_THAN":
        violations.append("LIQUIDITY_THRESHOLD_SEMANTICS_INVALID")
    evidence_threshold = _float(evidence.get("company_min_average_volume"))
    if evidence_threshold != COMPANY_MIN_AVERAGE_VOLUME:
        violations.append("LIQUIDITY_EVIDENCE_THRESHOLD_MISMATCH")

    current_source = str(summary.get("current_file") or "").strip()
    if not current_source:
        violations.append("LIQUIDITY_CURRENT_SOURCE_MISSING")
    if str(evidence.get("source_file") or "").strip() != current_source:
        violations.append("LIQUIDITY_SHORTLIST_SOURCE_MISMATCH")

    rows = evidence.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        violations.append("LIQUIDITY_ROWS_INVALID")
        rows = []

    row_by_symbol: dict[str, dict[str, Any]] = {}
    duplicate_symbols: set[str] = set()
    eligible_company_count = 0
    filtered_company_count = 0
    missing_volume_company_count = 0
    etf_count = 0
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            violations.append("LIQUIDITY_ROW_SYMBOL_MISSING")
            continue
        if symbol in row_by_symbol:
            duplicate_symbols.add(symbol)
        row_by_symbol[symbol] = row
        security_type = str(row.get("security_type") or "UNKNOWN").upper()
        status = str(row.get("status") or "")
        detail = str(row.get("detail") or "")
        volume = _float(row.get("average_daily_share_volume_30d"))
        if security_type == "ETF":
            etf_count += 1
            if status != "ETF_SEPARATE_RULES":
                violations.append(f"LIQUIDITY_ETF_STATUS_INVALID:{symbol}")
        elif security_type == "COMPANY_EQUITY":
            if status == "ELIGIBLE":
                eligible_company_count += 1
                if volume is None or volume <= COMPANY_MIN_AVERAGE_VOLUME:
                    violations.append(f"LIQUIDITY_ELIGIBLE_COMPANY_NOT_ABOVE_THRESHOLD:{symbol}")
            elif status == "LIQUIDITY_FILTERED":
                if detail == "MISSING_OR_NONPOSITIVE_VOLUME":
                    missing_volume_company_count += 1
                else:
                    filtered_company_count += 1
            else:
                violations.append(f"LIQUIDITY_COMPANY_STATUS_INVALID:{symbol}")
        else:
            violations.append(f"LIQUIDITY_SECURITY_TYPE_INVALID:{symbol}")

    for symbol in sorted(duplicate_symbols):
        violations.append(f"LIQUIDITY_DUPLICATE_SYMBOL:{symbol}")

    shortlist_symbols: set[str] = set()
    for item in shortlist:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            violations.append("LIQUIDITY_SHORTLIST_SYMBOL_MISSING")
            continue
        shortlist_symbols.add(symbol)
        row = row_by_symbol.get(symbol)
        if row is None:
            violations.append(f"LIQUIDITY_SHORTLIST_EVIDENCE_MISSING:{symbol}")
            continue
        security_type = str(row.get("security_type") or "UNKNOWN").upper()
        status = str(row.get("status") or "")
        volume = _float(row.get("average_daily_share_volume_30d"))
        if security_type == "COMPANY_EQUITY":
            if status != "ELIGIBLE" or volume is None or volume <= COMPANY_MIN_AVERAGE_VOLUME:
                violations.append(f"LIQUIDITY_FILTERED_COMPANY_IN_SHORTLIST:{symbol}")
        elif security_type == "ETF":
            if status != "ETF_SEPARATE_RULES":
                violations.append(f"LIQUIDITY_ETF_SHORTLIST_STATUS_INVALID:{symbol}")
        else:
            violations.append(f"LIQUIDITY_SHORTLIST_SECURITY_TYPE_INVALID:{symbol}")

    expected_filtered = summary.get("excluded_liquidity_filtered")
    if isinstance(expected_filtered, int) and expected_filtered != filtered_company_count:
        violations.append("LIQUIDITY_FILTERED_COUNT_MISMATCH")
    expected_missing = summary.get("excluded_liquidity_missing")
    if isinstance(expected_missing, int) and expected_missing != missing_volume_company_count:
        violations.append("LIQUIDITY_MISSING_VOLUME_COUNT_MISMATCH")
    expected_etf = summary.get("etf_separate_liquidity_count")
    if isinstance(expected_etf, int) and expected_etf != etf_count:
        violations.append("LIQUIDITY_ETF_COUNT_MISMATCH")

    return {
        "ok": not violations,
        "state": "ACTIVE" if not violations else "FAIL_CLOSED",
        "summary_generated_at": generated_at.isoformat() if generated_at else None,
        "rollout_at": rollout.isoformat(),
        "evidence_found": evidence_found,
        "current_source": current_source or None,
        "actionable_count": len(shortlist_symbols),
        "eligible_company_count": eligible_company_count,
        "filtered_company_count": filtered_company_count,
        "missing_volume_company_count": missing_volume_company_count,
        "etf_count": etf_count,
        "violations": sorted(set(violations)),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def render_markdown(status: dict[str, Any]) -> str:
    state = status.get("state") or "UNKNOWN"
    if state == "PENDING_FIRST_POST_MERGE_PUBLICATION":
        heading = "PENDING FIRST POST-MERGE PUBLICATION"
    else:
        heading = "PASS" if status.get("ok") is True else "FAIL-CLOSED"
    lines = [
        "",
        "### Canonical company-liquidity gate health",
        f"Status: **{heading}**  ",
        "Company rule: **30D average daily share volume strictly > 1,500,000 shares**  ",
        "ETF rule: **separate liquidity/capacity path**  ",
        f"Current source: `{status.get('current_source') or 'missing'}`  ",
        f"Evidence found: **{status.get('evidence_found')}**  ",
    ]
    if state == "PENDING_FIRST_POST_MERGE_PUBLICATION":
        lines.append(
            "The current shortlist predates the merged liquidity gate; the first scheduled post-merge shortlist publication will make the artifact mandatory.  "
        )
    else:
        lines.extend(
            [
                f"Actionable shortlist symbols checked: **{status.get('actionable_count')}**  ",
                f"Eligible companies in evidence: **{status.get('eligible_company_count')}**  ",
                f"Liquidity-filtered companies: **{status.get('filtered_company_count')}**  ",
                f"Companies missing valid volume evidence: **{status.get('missing_volume_company_count')}**  ",
                f"ETFs on separate rules: **{status.get('etf_count')}**  ",
            ]
        )
    lines.append("Safety: `trading_authorized=false`, `live_trading_enabled=false`")
    violations = list(status.get("violations") or [])
    if violations:
        lines.extend(["Liquidity-gate violations:", *[f"- `{item}`" for item in violations]])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", required=True)
    parser.add_argument("--shortlist", required=True)
    parser.add_argument("--evidence")
    parser.add_argument("--evidence-found", choices=("true", "false"), required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    evidence_found = args.evidence_found == "true"
    evidence = _load_object(args.evidence) if evidence_found and args.evidence else None
    status = summarize(
        _load_object(args.summary),
        _load_list(args.shortlist),
        evidence=evidence,
        evidence_found=evidence_found,
    )
    Path(args.output_json).write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(status))
    return 0 if status["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
