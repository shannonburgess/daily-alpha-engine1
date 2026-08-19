import base64
import gzip
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_GATE = REPO_ROOT / "tradingview" / "v2_5_shadow_challenger_source_gate.json"
SHADOW_ARCHIVE = (
    REPO_ROOT / "tradingview" / "da_turtle_20_10_v2_5_shadow_challenger.pine.gz.b64"
)
EXPECTED_SHADOW_SHA256 = (
    "77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718"
)


def _decoded_shadow_source() -> bytes:
    encoded = SHADOW_ARCHIVE.read_text(encoding="utf-8").strip()
    return gzip.decompress(base64.b64decode(encoded))


def test_v25_source_gate_records_archived_compiled_shadow_but_stays_fail_closed() -> None:
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))

    assert gate["model_id"] == "PAPER_SHADOW_V25"
    assert gate["strategy_version"] == "2.5"
    assert gate["source_status"] == "EXACT_TRADINGVIEW_SOURCE_CAPTURED_USER_EXPORT"
    assert gate["source_capture_sha256"] == (
        "0845f41a36cda1b33c8308249afc15e2fc70369791db0113b1f47118d935419b"
    )
    assert gate["shadow_transform_sha256"] == EXPECTED_SHADOW_SHA256
    assert gate["shadow_archive_path"] == (
        "tradingview/da_turtle_20_10_v2_5_shadow_challenger.pine.gz.b64"
    )
    assert gate["shadow_archive_encoding"] == "gzip+base64"
    assert gate["shadow_source_status"] == (
        "ARCHIVED_EXACT_TRANSFORM_AND_COMPILED_IN_TRADINGVIEW"
    )
    assert gate["activation_ready"] is False
    assert gate["safety"] == {
        "trading_authorized": False,
        "live_trading_enabled": False,
        "webhook_activation_authorized": False,
        "aws_production_deployment_authorized": False,
    }


def test_v25_archived_shadow_decodes_to_exact_reviewed_source() -> None:
    source_bytes = _decoded_shadow_source()
    source = source_bytes.decode("utf-8")

    assert hashlib.sha256(source_bytes).hexdigest() == EXPECTED_SHADOW_SHA256
    assert 'shorttitle="DA-T20/10-SH25"' in source
    assert 'enableShadowForwardTest = input.bool(' in source
    assert 'enableWebhookOrders = input.bool(' in source
    assert '"Attach v2.5 Shadow Webhook Messages"' in source
    assert '"PAPER_SHADOW_V25"' in source
    assert 'shadowForwardStartIso' in source
    assert '"forward_test_start"' in source
    assert '"replay_max_price"' in source
    assert 'maxChaseAtr = input.float(' in source
    assert '1.0,' in source


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


def test_v25_gate_records_verified_flat_common_start_and_disabled_activation() -> None:
    gate = json.loads(SOURCE_GATE.read_text(encoding="utf-8"))
    prereqs = gate["verified_activation_prerequisites"]

    assert prereqs["v24_loaded_compiled_flat"] is True
    assert prereqs["v25_loaded_compiled_flat"] is True
    assert prereqs["common_forward_test_start"] == "2026-08-19"
    assert prereqs["staging_forward_start_configured"] is True
    assert prereqs["v24_forward_test_enabled"] is False
    assert prereqs["v25_forward_test_enabled"] is False
    assert prereqs["v24_webhook_enabled"] is False
    assert prereqs["v25_webhook_enabled"] is False
