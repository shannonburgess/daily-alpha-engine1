from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime

import pytest

from daily_alpha.pine_paired_evidence_capture import (
    PinePairedEvidenceCaptureError,
    assess_paired_historical_evidence_readiness,
    build_paired_parity_capture_packet,
    parse_tradingview_instance_manifest,
    render_paired_capture_skeleton,
    render_parameter_manifest_skeleton,
)
from daily_alpha.pine_v24_parity import V24Parameters
from daily_alpha.pine_v25_parity import V25Parameters


def _parameter_manifest(spec, parameter_type, **overrides):
    values = {}
    instance = parameter_type()
    for field in fields(parameter_type):
        value = getattr(instance, field.name)
        values[field.name] = value.isoformat() if isinstance(value, datetime) else value
    values.update(overrides)
    return json.dumps(
        {
            "model_id": spec.model_id,
            "strategy_version": spec.strategy_version,
            "source_blob_sha": spec.source_blob_sha,
            "process_orders_on_close": True,
            "parameters": values,
        },
        sort_keys=True,
    )


def _instance_manifest(spec, parameter_sha, *, instance_id="tv-instance-1", symbol="DINO"):
    return json.dumps(
        {
            "model_id": spec.model_id,
            "strategy_version": spec.strategy_version,
            "book_id": spec.book_id,
            "source_path": spec.source_path,
            "source_blob_sha": spec.source_blob_sha,
            "script_instance_id": instance_id,
            "chart_symbol": symbol,
            "chart_timeframe": "1D",
            "process_orders_on_close": True,
            "parameter_manifest_sha256": parameter_sha,
            "export_revision": "tv-export-2026-08-23T23:30:00Z",
            "captured_at": datetime(2026, 8, 23, 23, 30, tzinfo=UTC).isoformat(),
            "trading_authorized": False,
            "live_trading_enabled": False,
        },
        sort_keys=True,
    )


def test_capture_packet_freezes_control_challenger_identity_and_daily_close_semantics():
    packet = build_paired_parity_capture_packet("dino")

    assert packet.symbol == "DINO"
    assert packet.sh24.model_id == "PAPER_SHADOW_V24"
    assert packet.sh25.model_id == "PAPER_SHADOW_V25"
    assert packet.sh24.book_id != packet.sh25.book_id
    assert packet.sh24.source_blob_sha == "33091e312ad3069ff7d82825b370f2a73d93107c"
    assert packet.sh25.source_blob_sha == "2b00cd7f8a8954032177a14baa1f34c1ce2ac3e5"
    assert packet.sh24.process_orders_on_close is True
    assert packet.sh25.process_orders_on_close is True
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False
    assert len(packet.packet_id) == 64


def test_parameter_skeleton_requires_every_field_without_filling_defaults():
    packet = build_paired_parity_capture_packet("DINO")
    sh24 = render_parameter_manifest_skeleton(packet.sh24)
    sh25 = render_parameter_manifest_skeleton(packet.sh25)

    assert set(sh24["parameters"]) == {field.name for field in fields(V24Parameters)}
    assert set(sh25["parameters"]) == {field.name for field in fields(V25Parameters)}
    assert all(value is None for value in sh24["parameters"].values())
    assert all(value is None for value in sh25["parameters"].values())
    assert sh24["process_orders_on_close"] is True
    assert sh25["process_orders_on_close"] is True


def test_paired_capture_skeleton_is_one_shared_market_contract_and_never_authorizes_trading():
    skeleton = render_paired_capture_skeleton("DINO")

    assert skeleton["schema"] == "DAILY_ALPHA_PAIRED_PINE_EVIDENCE_CAPTURE_V1"
    assert skeleton["symbol"] == "DINO"
    assert skeleton["trading_authorized"] is False
    assert skeleton["live_trading_enabled"] is False
    assert skeleton["sh24"]["tradingview_instance"]["chart_symbol"] == "DINO"
    assert skeleton["sh25"]["tradingview_instance"]["chart_symbol"] == "DINO"
    assert "shared_market_csv_headers" in skeleton
    assert skeleton["sh24"]["tradingview_instance"]["script_instance_id"] is None
    assert skeleton["sh25"]["tradingview_instance"]["script_instance_id"] is None


def test_instance_manifest_binds_exact_source_book_symbol_timeframe_and_parameter_hash():
    packet = build_paired_parity_capture_packet("DINO")
    parameter_text = _parameter_manifest(packet.sh24, V24Parameters)
    parameter_sha = __import__("hashlib").sha256(parameter_text.encode()).hexdigest()
    manifest_text = _instance_manifest(packet.sh24, parameter_sha)

    manifest = parse_tradingview_instance_manifest(
        manifest_text,
        spec=packet.sh24,
        expected_symbol="DINO",
        expected_parameter_manifest_sha256=parameter_sha,
    )

    assert manifest.model_id == "PAPER_SHADOW_V24"
    assert manifest.book_id == "PAPER_SHADOW_V24"
    assert manifest.chart_timeframe == "1D"
    assert manifest.process_orders_on_close is True
    assert manifest.parameter_manifest_sha256 == parameter_sha
    assert manifest.trading_authorized is False
    assert manifest.live_trading_enabled is False
    assert len(manifest.sha256) == 64


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("book_id", "PAPER_SHADOW_V25", "TRADINGVIEW_BOOK_ID_MISMATCH"),
        ("source_blob_sha", "deadbeef", "TRADINGVIEW_SOURCE_BLOB_SHA_MISMATCH"),
        ("chart_symbol", "SPY", "TRADINGVIEW_CHART_SYMBOL_MISMATCH"),
        ("chart_timeframe", "5", "TRADINGVIEW_CHART_TIMEFRAME_MUST_BE_DAILY"),
        ("process_orders_on_close", False, "PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE"),
        ("trading_authorized", True, "TRADINGVIEW_CAPTURE_TRADING_AUTHORITY_MUST_BE_FALSE"),
        ("live_trading_enabled", True, "TRADINGVIEW_CAPTURE_LIVE_AUTHORITY_MUST_BE_FALSE"),
    ],
)
def test_instance_manifest_fails_closed_on_cross_wiring_or_authority(field, value, code):
    packet = build_paired_parity_capture_packet("DINO")
    parameter_text = _parameter_manifest(packet.sh24, V24Parameters)
    parameter_sha = __import__("hashlib").sha256(parameter_text.encode()).hexdigest()
    payload = json.loads(_instance_manifest(packet.sh24, parameter_sha))
    payload[field] = value

    with pytest.raises(PinePairedEvidenceCaptureError, match=code):
        parse_tradingview_instance_manifest(
            json.dumps(payload),
            spec=packet.sh24,
            expected_symbol="DINO",
            expected_parameter_manifest_sha256=parameter_sha,
        )


def test_instance_manifest_rejects_parameter_hash_from_another_export():
    packet = build_paired_parity_capture_packet("DINO")
    parameter_text = _parameter_manifest(packet.sh24, V24Parameters)
    parameter_sha = __import__("hashlib").sha256(parameter_text.encode()).hexdigest()
    wrong_sha = "0" * 64

    with pytest.raises(
        PinePairedEvidenceCaptureError,
        match="TRADINGVIEW_PARAMETER_MANIFEST_SHA256_MISMATCH",
    ):
        parse_tradingview_instance_manifest(
            _instance_manifest(packet.sh24, wrong_sha),
            spec=packet.sh24,
            expected_symbol="DINO",
            expected_parameter_manifest_sha256=parameter_sha,
        )


def test_paired_readiness_reports_exact_external_evidence_blockers_without_guessing_defaults():
    readiness = assess_paired_historical_evidence_readiness(symbol="DINO")

    assert readiness.ready is False
    assert readiness.paired_capture_id is None
    assert readiness.shared_market_sha256 is None
    assert readiness.trading_authorized is False
    assert readiness.live_trading_enabled is False
    assert "POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_MISSING" in readiness.blockers
    assert "EXACT_PINE_PARAMETER_MANIFEST_MISSING" in readiness.blockers
    assert "SH24_TRADINGVIEW_INSTANCE_EVIDENCE_NOT_PRESENT" in readiness.blockers
    assert "SH25_TRADINGVIEW_INSTANCE_EVIDENCE_NOT_PRESENT" in readiness.blockers
