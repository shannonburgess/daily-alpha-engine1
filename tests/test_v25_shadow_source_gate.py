import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_GATE = REPO_ROOT / "tradingview" / "v2_5_shadow_challenger_source_gate.json"


def test_v25_source_gate_records_exact_user_source_capture_but_stays_fail_closed() -> None:
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))

    assert gate["model_id"] == "PAPER_SHADOW_V25"
    assert gate["strategy_version"] == "2.5"
    assert gate["source_status"] == "EXACT_TRADINGVIEW_SOURCE_CAPTURED_USER_EXPORT"
    assert gate["source_capture_sha256"] == (
        "0845f41a36cda1b33c8308249afc15e2fc70369791db0113b1f47118d935419b"
    )
    assert gate["shadow_transform_sha256"] == (
        "77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718"
    )
    assert gate["shadow_source_status"] == (
        "GENERATED_FROM_CAPTURED_SOURCE_PENDING_REPO_ARCHIVE_AND_TRADINGVIEW_COMPILE"
    )
    assert gate["activation_ready"] is False
    assert gate["safety"] == {
        "trading_authorized": False,
        "live_trading_enabled": False,
        "webhook_activation_authorized": False,
        "aws_production_deployment_authorized": False,
    }


def test_v25_source_gate_records_audited_no_chase_and_runner_contract() -> None:
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))
    params = gate["audited_parameters"]

    assert params["minimum_adx"] == 25.0
    assert params["persistent_armed_breakout"] is True
    assert params["maximum_bars_to_keep_breakout_armed"] == 10
    assert params["maximum_entry_distance_above_breakout_atr"] == 1.0
    assert params["invalidate_below_breakout_atr"] == 0.5
    assert params["structural_runner_exit"] is True
    assert params["structural_exit_lookback"] == 20
    assert params["structural_exit_confirmation_bars"] == 1
    assert params["break_even_after_harvest"] is False
    assert params["legacy_adaptive_bear_flip_exit"] is False
    assert params["legacy_10_bar_turtle_exit"] is False
    assert params["webhook_attachment_default"] is False
    assert params["webhook_secret_default"] == ""


def test_v25_source_gate_records_corrected_persistent_arm_state_logic() -> None:
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))
    logic = gate["verified_source_logic"]

    assert logic["breakout_arms_on_price_event_before_trend_quality_confirmation"] is True
    assert logic["armed_state_not_invalidated_only_because_trend_or_adx_not_ready"] is True
    assert logic["armed_entry_requires_price_at_or_above_breakout"] is True
    assert logic["armed_entry_requires_price_at_or_below_plus_1_atr_no_chase_ceiling"] is True
    assert logic["structural_runner_exit_enabled"] is True
