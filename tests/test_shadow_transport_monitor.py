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


def _probe() -> dict[str, object]:
    return {
        "statusCode": 401,
        "body": (
            '{"ok":false,"status":"UNAUTHORIZED","paper_only":true,'
            '"trading_authorized":false,"live_trading_enabled":false}'
        ),
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
    status = summarize(_runtime(), _probe(), _mappings())

    assert status["ok"] is True
    assert status["matching_enabled_processor_mappings"] == 1
    assert status["trading_authorized"] is False
    assert status["live_trading_enabled"] is False
    assert status["tradingview_private_alert_observable"] is False


def test_ingress_runtime_drift_fails_closed() -> None:
    runtime = _runtime()
    runtime["state"] = "Pending"
    runtime["last_update_status"] = "Failed"
    runtime["secret_configured"] = False

    status = summarize(runtime, _probe(), _mappings())

    assert status["ok"] is False
    assert "INGRESS_FUNCTION_NOT_ACTIVE" in status["violations"]
    assert "INGRESS_LAST_UPDATE_NOT_SUCCESSFUL" in status["violations"]
    assert "INGRESS_SECRET_NOT_CONFIGURED" in status["violations"]


def test_auth_probe_must_reach_expected_fail_closed_boundary() -> None:
    probe = _probe()
    probe["statusCode"] = 503
    probe["body"] = (
        '{"ok":false,"status":"INGRESS_SECRET_ERROR","paper_only":true,'
        '"trading_authorized":false,"live_trading_enabled":false}'
    )

    status = summarize(_runtime(), probe, _mappings())

    assert status["ok"] is False
    assert "INGRESS_AUTH_PROBE_UNEXPECTED_STATUS" in status["violations"]
    assert "INGRESS_AUTH_PROBE_DID_NOT_REACH_AUTH_GATE" in status["violations"]


def test_queue_to_processor_mapping_mismatch_fails_closed() -> None:
    mappings = _mappings()
    mappings["mappings"][0]["event_source_name"] = "another-queue"

    status = summarize(_runtime(), _probe(), mappings)

    assert status["ok"] is False
    assert "INGRESS_QUEUE_NOT_MAPPED_TO_PROCESSOR" in status["violations"]


def test_live_safety_drift_in_probe_fails_closed() -> None:
    probe = _probe()
    probe["body"] = (
        '{"ok":false,"status":"UNAUTHORIZED","paper_only":true,'
        '"trading_authorized":false,"live_trading_enabled":true}'
    )

    status = summarize(_runtime(), probe, _mappings())

    assert status["ok"] is False
    assert "INGRESS_PROBE_LIVE_TRADING_NOT_FALSE" in status["violations"]
