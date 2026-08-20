"""Validate the read-only backend transport wiring for PAPER shadow events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def summarize(
    ingress_runtime: dict[str, Any],
    event_source_mappings: dict[str, Any],
) -> dict[str, Any]:
    """Return fail-closed health evidence for staging ingress/processor wiring."""
    violations: list[str] = []

    if ingress_runtime.get("state") != "Active":
        violations.append("INGRESS_FUNCTION_NOT_ACTIVE")
    if ingress_runtime.get("last_update_status") != "Successful":
        violations.append("INGRESS_LAST_UPDATE_NOT_SUCCESSFUL")
    if ingress_runtime.get("secret_configured") is not True:
        violations.append("INGRESS_SECRET_REFERENCE_NOT_CONFIGURED")
    if ingress_runtime.get("queue_configured") is not True:
        violations.append("INGRESS_QUEUE_NOT_CONFIGURED")

    queue_name = str(ingress_runtime.get("queue_name") or "").strip()
    if not queue_name:
        violations.append("INGRESS_QUEUE_NAME_MISSING")

    mappings = event_source_mappings.get("mappings")
    if not isinstance(mappings, list):
        violations.append("PROCESSOR_EVENT_SOURCE_MAPPINGS_INVALID")
        mappings = []

    matching_enabled = [
        row
        for row in mappings
        if isinstance(row, dict)
        and row.get("state") == "Enabled"
        and str(row.get("event_source_name") or "").strip() == queue_name
    ]
    if queue_name and not matching_enabled:
        violations.append("INGRESS_QUEUE_NOT_MAPPED_TO_PROCESSOR")

    return {
        "ok": not violations,
        "ingress_function": ingress_runtime.get("function_name"),
        "ingress_state": ingress_runtime.get("state"),
        "ingress_last_update_status": ingress_runtime.get("last_update_status"),
        "ingress_queue_name": queue_name or None,
        "secret_reference_configured": ingress_runtime.get("secret_configured") is True,
        "queue_configured": ingress_runtime.get("queue_configured") is True,
        "matching_enabled_processor_mappings": len(matching_enabled),
        "violations": sorted(set(violations)),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "ingress_invoke_probe_performed": False,
        "ingress_invoke_probe_reason": (
            "LEAST_PRIVILEGE_MONITOR_ROLE_CANNOT_INVOKE_PUBLIC_INGRESS"
        ),
        "tradingview_private_alert_observable": False,
        "transport_scope": (
            "Backend transport monitoring verifies the ingress Lambda runtime, configured secret "
            "reference, configured ingress queue, and enabled queue-to-processor mapping. The "
            "least-privilege monitor role does not invoke the public ingress and cannot inspect "
            "private TradingView alert state through a supported API."
        ),
    }


def render_markdown(status: dict[str, Any]) -> str:
    state = "PASS" if status["ok"] else "FAIL-CLOSED"
    lines = [
        "",
        "### Shadow backend transport wiring",
        f"Status: **{state}**  ",
        f"Ingress: `{status['ingress_function'] or 'missing'}` — "
        f"`{status['ingress_state'] or 'unknown'}` / "
        f"`{status['ingress_last_update_status'] or 'unknown'}`  ",
        f"Ingress queue: `{status['ingress_queue_name'] or 'missing'}`  ",
        f"Secret reference configured: **{status['secret_reference_configured']}**  ",
        f"Queue configured: **{status['queue_configured']}**  ",
        "Matching enabled queue→processor mappings: "
        f"**{status['matching_enabled_processor_mappings']}**  ",
        "Safety: `trading_authorized=false`, `live_trading_enabled=false`",
    ]
    if status["violations"]:
        lines.extend(
            ["Transport violations:", *[f"- `{item}`" for item in status["violations"]]]
        )
    lines.extend(
        [
            "",
            (
                "The monitor intentionally does not invoke the public ingress: its staging role "
                "is least-privilege and lacks `lambda:InvokeFunction` on that function. This is "
                "not a TradingView action item. Runtime and queue→processor wiring are checked "
                "read-only; validated SH24/SH25 TradingView configuration stays frozen."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingress-runtime", required=True)
    parser.add_argument("--event-source-mappings", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    status = summarize(
        _load_object(args.ingress_runtime),
        _load_object(args.event_source_mappings),
    )
    Path(args.output_json).write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(status))
    return 0 if status["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
