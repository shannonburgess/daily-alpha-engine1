from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ProspectV1StagingProofError(ValueError):
    """The real staging prospect rollout did not satisfy the V1 launch contract."""


def _require_mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProspectV1StagingProofError(code)
    return value


def _require_false(value: Any, code: str) -> None:
    if value is not False:
        raise ProspectV1StagingProofError(code)


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("prospect_v1_runtime_enabled") is not True:
        raise ProspectV1StagingProofError("PROSPECT_V1_RUNTIME_NOT_ENABLED")
    _require_false(result.get("live_trading_enabled"), "LIVE_TRADING_AUTHORITY_INVALID")

    rollout = _require_mapping(
        result.get("prospect_initial_rollout"),
        "PROSPECT_INITIAL_ROLLOUT_RESULT_REQUIRED",
    )
    if rollout.get("ready") is not True:
        reasons = rollout.get("reasons")
        raise ProspectV1StagingProofError(f"PROSPECT_INITIAL_ROLLOUT_NOT_READY:{reasons}")
    if rollout.get("delivery_contract_validated") is not True:
        raise ProspectV1StagingProofError("NEWSLETTER_DELIVERY_NOT_VALIDATED")
    reasons = rollout.get("reasons")
    if reasons not in ([], (), None):
        raise ProspectV1StagingProofError("READY_ROLLOUT_CANNOT_HAVE_REASONS")
    _require_false(rollout.get("trading_authorized"), "PROSPECT_TRADING_AUTHORITY_INVALID")
    _require_false(rollout.get("live_trading_enabled"), "PROSPECT_LIVE_AUTHORITY_INVALID")

    board_id = str(rollout.get("board_id") or "").strip()
    if not board_id:
        raise ProspectV1StagingProofError("PROSPECT_BOARD_ID_REQUIRED")
    total_qualifying = rollout.get("total_qualifying")
    if not isinstance(total_qualifying, int) or isinstance(total_qualifying, bool) or total_qualifying < 0:
        raise ProspectV1StagingProofError("TOTAL_QUALIFYING_INVALID")
    top_pick_symbols = rollout.get("top_pick_symbols")
    if not isinstance(top_pick_symbols, list):
        raise ProspectV1StagingProofError("TOP_PICK_SYMBOLS_REQUIRED")
    normalized_top = tuple(str(item or "").strip().upper() for item in top_pick_symbols)
    if any(not item for item in normalized_top):
        raise ProspectV1StagingProofError("TOP_PICK_SYMBOL_INVALID")
    if len(set(normalized_top)) != len(normalized_top):
        raise ProspectV1StagingProofError("TOP_PICK_SYMBOLS_MUST_BE_UNIQUE")
    if len(normalized_top) > min(3, total_qualifying):
        raise ProspectV1StagingProofError("TOP_PICK_COUNT_INVALID")

    additional = rollout.get("additional_qualifying_count")
    if additional != total_qualifying - len(normalized_top):
        raise ProspectV1StagingProofError("ADDITIONAL_QUALIFYING_COUNT_MISMATCH")
    filtered_count = rollout.get("filtered_count")
    if not isinstance(filtered_count, int) or isinstance(filtered_count, bool) or filtered_count < 0:
        raise ProspectV1StagingProofError("FILTERED_COUNT_INVALID")

    channels = rollout.get("verified_channels")
    if not isinstance(channels, list):
        raise ProspectV1StagingProofError("VERIFIED_CHANNELS_REQUIRED")
    normalized_channels = tuple(sorted(str(item or "").strip().upper() for item in channels))
    expected_channels = ("API", "DASHBOARD", "NEWSLETTER")
    if normalized_channels != expected_channels:
        raise ProspectV1StagingProofError("REQUIRED_PROSPECT_CHANNELS_NOT_VERIFIED")

    email_delivery = _require_mapping(result.get("email_delivery"), "EMAIL_DELIVERY_RESULT_REQUIRED")
    if str(email_delivery.get("status") or "").strip().upper() != "SENT":
        raise ProspectV1StagingProofError("NEWSLETTER_EMAIL_NOT_SENT")

    return {
        "board_id": board_id,
        "total_qualifying": total_qualifying,
        "top_pick_symbols": list(normalized_top),
        "additional_qualifying_count": additional,
        "filtered_count": filtered_count,
        "verified_channels": list(expected_channels),
        "newsletter_delivery_status": "SENT",
        "prospect_v1_runtime_enabled_during_proof": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def render_receipt(
    *,
    result_path: Path,
    output_json: Path,
    output_markdown: Path,
    commit: str,
    run_id: str,
    environment_restored: bool,
) -> dict[str, Any]:
    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectV1StagingProofError("PROSPECT_STAGING_RESULT_INVALID_JSON") from exc
    result = _require_mapping(raw, "PROSPECT_STAGING_RESULT_MUST_BE_OBJECT")
    proof = validate_result(result)
    if environment_restored is not True:
        raise ProspectV1StagingProofError("REPORT_LAMBDA_ENVIRONMENT_NOT_RESTORED")

    receipt = {
        "schema": "DAILY_ALPHA_PROSPECT_V1_STAGING_PROOF_V1",
        "commit": str(commit or "").strip(),
        "workflow_run_id": str(run_id or "").strip(),
        **proof,
        "report_lambda_environment_restored": True,
    }
    if not receipt["commit"]:
        raise ProspectV1StagingProofError("PROOF_COMMIT_REQUIRED")
    if not receipt["workflow_run_id"]:
        raise ProspectV1StagingProofError("PROOF_WORKFLOW_RUN_ID_REQUIRED")

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    top = ", ".join(receipt["top_pick_symbols"]) or "NONE"
    markdown = "\n".join(
        [
            "## V1 prospect staging proof",
            "",
            f"- Commit: `{receipt['commit']}`",
            f"- Workflow run: `{receipt['workflow_run_id']}`",
            f"- Board: `{receipt['board_id']}`",
            f"- Total qualifying opportunities: **{receipt['total_qualifying']}**",
            f"- Top ConvexRidge picks: **{top}**",
            f"- Additional qualifying opportunities retained: **{receipt['additional_qualifying_count']}**",
            f"- Verified channels: **{', '.join(receipt['verified_channels'])}**",
            "- Newsletter delivery contract: **SENT / validated**",
            "- Report Lambda environment restored exactly after proof: **yes**",
            "- `trading_authorized=false`",
            "- `live_trading_enabled=false`",
            "",
            "This receipt proves the staging initial-rollout contract for the captured canonical board; it does not authorize personalized advice, PAPER mutation, or live execution.",
            "",
        ]
    )
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.write_text(markdown, encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and sanitize V1 prospect staging proof.")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--environment-restored", action="store_true")
    args = parser.parse_args()
    render_receipt(
        result_path=args.result,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
        commit=args.commit,
        run_id=args.run_id,
        environment_restored=args.environment_restored,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
