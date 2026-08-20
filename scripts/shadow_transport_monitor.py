"""Validate the read-only backend ingress runtime for PAPER shadow events."""

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


def summarize(ingress_runtime: dict[str, Any]) -> dict[str, Any]:
    """Return fail-closed health evidence for the staging Pine ingress runtime."""
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

    return {
        "ok": not violations,
        "ingress_function": ingress_runtime.get("function_name"),
        "ingress_state": ingress_runtime.get("state"),
        "ingress_last_update_status": ingress_runtime.get("last_update_status"),
        "ingress_queue_name": queue_name or None,
        "secret_reference_configured": ingress_runtime.get("secret_configured") is True,
        "queue_configured": ingress_runtime.get("queue_configured") is True,
        "violations": sorted(set(violations)),
        "trading_authorized": False,
        "live_trading_enabled": False,
        "ingress_invoke_probe_performed": False,
        "event_source_mapping_inspected": False,
        "least_privilege_boundary": (
            "The staging monitor role can read Lambda configuration and invoke only the read-only "
            "processor monitor operation. It cannot invoke the public ingress or list Lambda event "
            "source mappings. Those denied permissions are preserved rather than widened for "
            "monitoring convenience."
        ),
        "tradingview_private_alert_observable": False,
        "transport_scope": (
            "Backend transport monitoring verifies the ingress Lambda runtime plus configured "
            "secret and queue references. Processor runtime/state is monitored separately by the "
            "canonical shadow contract monitor. The original TradingView→AWS transport proof "
            "remains historical evidence; private TradingView alert state is not readable through "
            "a supported API."
        ),
    }


def render_markdown(status: dict[str, Any]) -> str:
    state = "PASS" if status["ok"] else "FAIL-CLOSED"
    lines = [
        "",
        "### Shadow backend ingress health",
        f"Status: **{state}**  ",
        f"Ingress: `{status['ingress_function'] or 'missing'}` — "
        f"`{status['ingress_state'] or 'unknown'}` / "
        f"`{status['ingress_last_update_status'] or 'unknown'}`  ",
        f"Ingress queue: `{status['ingress_queue_name'] or 'missing'}`  ",
        f"Secret reference configured: **{status['secret_reference_configured']}**  ",
        f"Queue configured: **{status['queue_configured']}**  ",
        "Safety: `trading_authorized=false`, `live_trading_enabled=false`",
    ]
    if status["violations"]:
        lines.extend(
            ["Ingress violations:", *[f"- `{item}`" for item in status["violations"]]]
        )
    lines.extend(
        [
            "",
            (
                "Least-privilege note: this monitor does not invoke the public ingress and does "
                "not list event-source mappings because the staging monitor role intentionally "
                "lacks those permissions. No manual action is required; validated SH24/SH25 "
                "TradingView configuration stays frozen."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingress-runtime", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    status = summarize(_load_object(args.ingress_runtime))
    Path(args.output_json).write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(status))
    return 0 if status["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
