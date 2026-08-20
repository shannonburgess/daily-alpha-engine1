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


def _mappings() -> dict[str, object]:
    return {
        "mappings": [
            {
                "state": "Enabled",
                "event_source_name": "daily-alpha-pine-events-staging",
                "last_processing_result": "OK",
            }
        ]
    }


def test_healthy_backend_transport_is_read_only() -> None:
    status = summarize(_runtime(), _mappings())

    assert status["ok"] is True
    assert status["matching_enabled_processor_mappings"] == 1
    assert status["secret_reference_configured"] is True
    assert status["ingress_invoke_probe_performed"] is False
    assert status["trading_authorized"] is False
    assert status["live_trading_enabled"] is False
    assert status["tradingview_private_alert_observable"] is False


def test_ingress_runtime_drift_fails_closed() -> None:
    runtime = _runtime()
    runtime["state"] = "Pending"
    runtime["last_update_status"] = "Failed"
    runtime["secret_configured"] = False

    status = summarize(runtime, _mappings())

    assert status["ok"] is False
    assert "INGRESS_FUNCTION_NOT_ACTIVE" in status["violations"]
    assert "INGRESS_LAST_UPDATE_NOT_SUCCESSFUL" in status["violations"]
    assert "INGRESS_SECRET_REFERENCE_NOT_CONFIGURED" in status["violations"]


def test_queue_to_processor_mapping_mismatch_fails_closed() -> None:
    mappings = _mappings()
    mappings["mappings"][0]["event_source_name"] = "another-queue"

    status = summarize(_runtime(), mappings)

    assert status["ok"] is False
    assert "INGRESS_QUEUE_NOT_MAPPED_TO_PROCESSOR" in status["violations"]


def test_disabled_matching_mapping_fails_closed() -> None:
    mappings = _mappings()
    mappings["mappings"][0]["state"] = "Disabled"

    status = summarize(_runtime(), mappings)

    assert status["ok"] is False
    assert "INGRESS_QUEUE_NOT_MAPPED_TO_PROCESSOR" in status["violations"]


def test_missing_queue_configuration_fails_closed() -> None:
    runtime = _runtime()
    runtime["queue_configured"] = False
    runtime["queue_name"] = None

    status = summarize(runtime, _mappings())

    assert status["ok"] is False
    assert "INGRESS_QUEUE_NOT_CONFIGURED" in status["violations"]
    assert "INGRESS_QUEUE_NAME_MISSING" in status["violations"]
