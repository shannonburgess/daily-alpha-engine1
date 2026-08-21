"""Build one concise operator-facing summary from canonical PAPER-shadow monitor evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTROL_KEYS = (
    "contract",
    "replay_scheduler",
    "transport",
    "universe",
    "liquidity",
    "source_diagnostic",
)

# These controls protect the active PAPER path directly. Their failure or
# indeterminate state must keep the GitHub monitor red. Source diagnostics are
# evidence-quality diagnostics only, while replay is conditional on whether a
# genuinely pre-existing ARMED record actually exists.
CI_CRITICAL_CONTROLS = frozenset({"contract", "transport", "universe", "liquidity"})


def _load(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _control_state(payload: Mapping[str, Any]) -> tuple[str, str]:
    status = str(payload.get("status") or "").strip().upper()
    diagnosis = str(payload.get("diagnosis") or payload.get("reason") or "").strip()
    ok = payload.get("ok")

    if ok is False or status in {"FAIL", "FAILED", "ERROR", "DATA_ERROR"}:
        return "FAIL_CLOSED", diagnosis or status or "CONTROL_FAILED"
    if status == "PENDING" or "PENDING" in diagnosis.upper() or "NOT_DUE" in diagnosis.upper():
        return "PENDING", diagnosis or status
    if ok is True or status in {"PASS", "HEALTHY", "OK", "SUCCESS"}:
        return "PASS", diagnosis or status or "PASS"
    if status:
        return status, diagnosis or status
    return "UNKNOWN", diagnosis or "STATUS_UNAVAILABLE"


def build_operator_summary(evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    core = evidence["core"]
    safety = core.get("safety") if isinstance(core.get("safety"), Mapping) else {}
    trading_authorized = safety.get("trading_authorized")
    live_trading_enabled = safety.get("live_trading_enabled")
    safety_violations = safety.get("violations")
    if not isinstance(safety_violations, list):
        safety_violations = ["SAFETY_EVIDENCE_INVALID"]

    controls: dict[str, dict[str, str]] = {}
    hard_failures: list[str] = []
    pending: list[str] = []
    unknown: list[str] = []
    for key in CONTROL_KEYS:
        state, detail = _control_state(evidence[key])
        controls[key] = {"state": state, "detail": detail}
        if state == "FAIL_CLOSED":
            hard_failures.append(key)
        elif state == "PENDING":
            pending.append(key)
        elif state == "UNKNOWN":
            unknown.append(key)

    if core.get("ok") is not True:
        hard_failures.append("core")
    if trading_authorized is not False or live_trading_enabled is not False:
        hard_failures.append("safety_flags")
    if safety_violations:
        hard_failures.append("safety_evidence")

    hard_failures = sorted(set(hard_failures))
    if hard_failures:
        overall = "FAIL_CLOSED"
        operator_action = "NONE — automated diagnosis remains authoritative; do not edit TradingView or run CloudShell as a routine workaround."
    elif pending:
        overall = "AUTOMATION_PENDING"
        operator_action = "NONE — bounded automation is waiting for its next technically eligible evidence window."
    elif unknown:
        overall = "EVIDENCE_INCOMPLETE"
        operator_action = "NONE — fail closed and let the canonical monitor resolve missing evidence automatically."
    else:
        overall = "HEALTHY"
        operator_action = "NONE — normal PAPER-shadow operation requires no manual TradingView or CloudShell step."

    accounts = core.get("accounts") if isinstance(core.get("accounts"), Mapping) else {}
    open_positions = 0
    for account in ("PAPER_SHADOW_V24", "PAPER_SHADOW_V25"):
        book = accounts.get(account)
        if isinstance(book, Mapping):
            value = book.get("open_count", 0)
            if isinstance(value, int) and not isinstance(value, bool):
                open_positions += value

    armed = core.get("total_armed")
    armed_count = armed if isinstance(armed, int) and not isinstance(armed, bool) else None

    # GitHub Actions notification severity is intentionally narrower than the
    # fail-closed operator state. Evidence-only diagnostic gaps still appear as
    # FAIL_CLOSED in #213, but they must not generate hourly failure noise when
    # the active PAPER path is safe and requires no human action.
    ci_blocking_failures: list[str] = []
    ci_nonblocking_findings: list[str] = []
    for failure in hard_failures:
        active_path_failure = failure in {
            "core",
            "safety_flags",
            "safety_evidence",
        } or failure in CI_CRITICAL_CONTROLS
        armed_replay_failure = failure == "replay_scheduler" and (
            armed_count is None or armed_count > 0
        )
        if active_path_failure or armed_replay_failure:
            ci_blocking_failures.append(failure)
        else:
            ci_nonblocking_findings.append(failure)

    for control in unknown:
        if control in CI_CRITICAL_CONTROLS:
            ci_blocking_failures.append(f"{control}:UNKNOWN")
        elif control == "replay_scheduler" and (armed_count is None or armed_count > 0):
            ci_blocking_failures.append("replay_scheduler:UNKNOWN")
        else:
            ci_nonblocking_findings.append(f"{control}:UNKNOWN")

    ci_blocking_failures = sorted(set(ci_blocking_failures))
    ci_nonblocking_findings = sorted(set(ci_nonblocking_findings))
    if ci_blocking_failures:
        ci_gate_status = "FAIL"
    elif ci_nonblocking_findings or pending or overall != "HEALTHY":
        ci_gate_status = "PASS_WITH_EVIDENCE_WARNINGS"
    else:
        ci_gate_status = "PASS"

    return {
        "overall_status": overall,
        "operator_action": operator_action,
        "session_date_et": core.get("session_date_et"),
        "session_phase": core.get("session_phase"),
        "diagnosis": core.get("diagnosis"),
        "zero_trade_status": core.get("zero_trade_status"),
        "paper_fills": core.get("total_session_fills"),
        "armed": armed,
        "open_positions": open_positions,
        "controls": controls,
        "pending_controls": pending,
        "hard_failures": hard_failures,
        "unknown_controls": unknown,
        "ci_gate_status": ci_gate_status,
        "ci_blocking_failures": ci_blocking_failures,
        "ci_nonblocking_findings": ci_nonblocking_findings,
        "tradingview_configuration": "FROZEN",
        "trading_authorized": trading_authorized,
        "live_trading_enabled": live_trading_enabled,
    }


def render_markdown(summary: Mapping[str, Any]) -> str:
    controls = summary["controls"]
    control_text = " · ".join(
        f"{key.replace('_', ' ')}=`{controls[key]['state']}`" for key in CONTROL_KEYS
    )
    return "\n".join(
        [
            "### Operator Summary",
            f"**Status:** `{summary['overall_status']}`  ",
            f"**Operator action:** {summary['operator_action']}  ",
            (
                "**Session:** "
                f"`{summary.get('session_date_et') or 'unknown'}` / "
                f"`{summary.get('session_phase') or 'unknown'}`  "
            ),
            (
                "**Trading:** "
                f"fills={summary.get('paper_fills')}, "
                f"open positions={summary.get('open_positions')}, "
                f"ARMED={summary.get('armed')}, "
                f"diagnosis=`{summary.get('diagnosis') or 'unknown'}`  "
            ),
            f"**Controls:** {control_text}  ",
            f"**Automation notification gate:** `{summary.get('ci_gate_status')}`  ",
            "**TradingView:** frozen; private alert/watchlist membership is not inferred  ",
            "**Safety:** `trading_authorized=false`, `live_trading_enabled=false`",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--replay-scheduler", required=True)
    parser.add_argument("--transport", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--liquidity", required=True)
    parser.add_argument("--source-diagnostic", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    evidence = {
        "core": _load(args.core),
        "contract": _load(args.contract),
        "replay_scheduler": _load(args.replay_scheduler),
        "transport": _load(args.transport),
        "universe": _load(args.universe),
        "liquidity": _load(args.liquidity),
        "source_diagnostic": _load(args.source_diagnostic),
    }
    summary = build_operator_summary(evidence)
    Path(args.output_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())