from __future__ import annotations

from scripts.shadow_contract_monitor import inspect_contract, render_markdown


def runtime(**overrides):
    value = {
        "function_name": "daily-alpha-pine-processor",
        "state": "Active",
        "last_update_status": "Successful",
        "last_modified": "2026-08-19T18:00:00+0000",
        "forward_test_start": "2026-08-19",
        "expected_forward_test_start": "2026-08-19",
    }
    value.update(overrides)
    return value


def strategy_event(account: str, **overrides):
    value = {
        "signal_id": f"strategy-{account}",
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "model_id": account,
        "forward_test_start": "2026-08-19",
        "replay_max_price": 230.0,
    }
    value.update(overrides)
    return value


def armed_signal(account: str, **overrides):
    value = {
        "signal_id": f"armed-{account}",
        "symbol": "NVDA",
        "action": "ENTRY_LONG",
        "model_id": account,
        "forward_test_start": "2026-08-19",
        "replay_max_price": 190.0,
    }
    value.update(overrides)
    return value


def monitor_state(*, v24_events=None, v25_events=None, v24_armed=None, v25_armed=None):
    return {
        "books": {
            "PAPER_SHADOW_V24": {
                "armed_limit_reached": False,
                "armed_signals": v24_armed or [],
                "events": v24_events or [],
            },
            "PAPER_SHADOW_V25": {
                "armed_limit_reached": False,
                "armed_signals": v25_armed or [],
                "events": v25_events or [],
            },
        }
    }


def test_valid_runtime_strategy_and_armed_contract_passes():
    state = monitor_state(
        v24_events=[strategy_event("PAPER_SHADOW_V24")],
        v25_armed=[armed_signal("PAPER_SHADOW_V25")],
    )

    result = inspect_contract(state, runtime())

    assert result["ok"] is True
    assert result["violations"] == []
    assert result["checked_strategy_events"] == 1
    assert result["checked_armed_signals"] == 1
    assert "none detected" in render_markdown(result)


def test_deployed_forward_start_drift_fails_closed():
    result = inspect_contract(
        monitor_state(),
        runtime(forward_test_start="2026-08-20"),
    )

    assert result["ok"] is False
    assert any("PROCESSOR_FORWARD_START_DRIFT" in item for item in result["violations"])


def test_strategy_event_forward_start_drift_fails_closed():
    bad = strategy_event("PAPER_SHADOW_V24", forward_test_start="2026-08-18")

    result = inspect_contract(monitor_state(v24_events=[bad]), runtime())

    assert result["ok"] is False
    assert "PAPER_SHADOW_V24:STRATEGY_FORWARD_START_DRIFT:2026-08-18" in result["violations"]


def test_entry_without_replay_ceiling_fails_closed():
    bad = strategy_event("PAPER_SHADOW_V25", replay_max_price=None)

    result = inspect_contract(monitor_state(v25_events=[bad]), runtime())

    assert result["ok"] is False
    assert "PAPER_SHADOW_V25:ENTRY_REPLAY_MAX_PRICE_INVALID" in result["violations"]


def test_armed_signal_requires_exact_model_start_and_replay_ceiling():
    bad = armed_signal(
        "PAPER_SHADOW_V24",
        model_id="PAPER_SHADOW_V25",
        forward_test_start=None,
        replay_max_price=0,
    )

    result = inspect_contract(monitor_state(v24_armed=[bad]), runtime())

    assert result["ok"] is False
    assert "PAPER_SHADOW_V24:ARMED_MODEL_ID_DRIFT:PAPER_SHADOW_V25" in result["violations"]
    assert "PAPER_SHADOW_V24:ARMED_FORWARD_START_DRIFT:MISSING" in result["violations"]
    assert "PAPER_SHADOW_V24:ARMED_REPLAY_MAX_PRICE_INVALID" in result["violations"]


def test_test_proof_traffic_is_not_used_for_strategy_contract_drift():
    proof = strategy_event(
        "PAPER_SHADOW_V25",
        signal_id="TV-SHADOW-E2E-20260819-01",
        forward_test_start=None,
        replay_max_price=None,
    )

    result = inspect_contract(monitor_state(v25_events=[proof]), runtime())

    assert result["ok"] is True
    assert result["checked_strategy_events"] == 0


def test_armed_evidence_limit_fails_closed():
    state = monitor_state()
    state["books"]["PAPER_SHADOW_V25"]["armed_limit_reached"] = True

    result = inspect_contract(state, runtime())

    assert result["ok"] is False
    assert "PAPER_SHADOW_V25:ARMED_EVIDENCE_LIMIT_REACHED" in result["violations"]
