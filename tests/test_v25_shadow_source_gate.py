import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_GATE = REPO_ROOT / "tradingview" / "v2_5_shadow_challenger_source_gate.json"


def test_v25_source_gate_is_fail_closed_until_exact_pine_is_archived() -> None:
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))

    assert gate["model_id"] == "PAPER_SHADOW_V25"
    assert gate["strategy_version"] == "2.5"
    assert gate["source_status"] == "EXACT_TRADINGVIEW_SOURCE_NOT_ARCHIVED"
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
