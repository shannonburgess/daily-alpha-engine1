from __future__ import annotations

from scripts.shadow_transport_monitor import summarize


def _runtime() -> dict[str, object]:
    return {
        "function_name": "daily-alpha-pine-ingress",
        "state": "Active",
        "last_update_status": "Successful",
        "secret_configured": True,
        "queue_configured": True,
        "queue_name": "daily-alpha-pine-events-staging",
    }


def test_healthy_backend_ingress_is_read_only() -> None:
    status = summarize(_runtime())

    assert status["ok"] is True
    assert status["secret_reference_configured"] is True
    assert status["queue_configured"] is True
    assert status["ingress_invoke_probe_performed"] is False
    assert status["event_source_mapping_inspected"] is False
    assert status["trading_authorized"] is False
    assert status["live_trading_enabled"] is False
    assert status["tradingview_private_alert_observable"] is False


def test_ingress_runtime_drift_fails_closed() -> None:
    runtime = _runtime()
    runtime["state"] = "Pending"
    runtime["last_update_status"] = "Failed"
    runtime["secret_configured"] = False

    status = summarize(runtime)

    assert status["ok"] is False
    assert "INGRESS_FUNCTION_NOT_ACTIVE" in status["violations"]
    assert "INGRESS_LAST_UPDATE_NOT_SUCCESSFUL" in status["violations"]
    assert "INGRESS_SECRET_REFERENCE_NOT_CONFIGURED" in status["violations"]


def test_missing_queue_configuration_fails_closed() -> None:
    runtime = _runtime()
    runtime["queue_configured"] = False
    runtime["queue_name"] = None

    status = summarize(runtime)

    assert status["ok"] is False
    assert "INGRESS_QUEUE_NOT_CONFIGURED" in status["violations"]
    assert "INGRESS_QUEUE_NAME_MISSING" in status["violations"]


def test_missing_secret_reference_fails_closed() -> None:
    runtime = _runtime()
    runtime["secret_configured"] = False

    status = summarize(runtime)

    assert status["ok"] is False
    assert "INGRESS_SECRET_REFERENCE_NOT_CONFIGURED" in status["violations"]
