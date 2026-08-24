from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path

from daily_alpha.pine_v25_armed_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_COMMIT,
    PINE_V25_SOURCE_SHA256,
    PINE_V25_STRATEGY_VERSION,
)
from daily_alpha.pine_v25_parity import PINE_V25_SOURCE_BLOB_SHA, PINE_V25_SOURCE_PATH

ARCHIVE_PATH = Path("tradingview/da_turtle_20_10_v2_5_shadow_challenger.pine.gz.b64")
SOURCE_GATE_PATH = Path("tradingview/v2_5_shadow_challenger_source_gate.json")


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _decoded_archived_source() -> bytes:
    encoded = ARCHIVE_PATH.read_text(encoding="utf-8").strip()
    return gzip.decompress(base64.b64decode(encoded))


def test_v2_5_frozen_source_path_restores_exact_audited_git_blob_lineage():
    source = Path(PINE_V25_SOURCE_PATH)
    data = source.read_bytes()

    assert source.is_file()
    assert PINE_V25_MODEL_ID == "PAPER_SHADOW_V25"
    assert PINE_V25_STRATEGY_VERSION == "2.5"
    assert PINE_V25_SOURCE_COMMIT == "b2a214c6b7a689453df5de7bb870c352456ebe8c"
    assert _git_blob_sha(data) == PINE_V25_SOURCE_BLOB_SHA


def test_v2_5_archived_compiled_transform_matches_independent_frozen_sha256():
    source_bytes = _decoded_archived_source()
    pine = source_bytes.decode("utf-8")

    assert hashlib.sha256(source_bytes).hexdigest() == PINE_V25_SOURCE_SHA256
    assert "DAILY ALPHA v2.5 RESEARCH CHALLENGER" in pine
    assert "PAPER / RESEARCH ONLY." in pine
    assert "process_orders_on_close=true" in pine
    assert "calc_on_every_tick=false" in pine
    assert "calc_on_order_fills=false" in pine
    assert 'shorttitle="DA-T20/10-SH25"' in pine
    assert '"Enable Paper Shadow Forward Test"' in pine
    assert '"Attach v2.5 Shadow Webhook Messages"' in pine


def test_v2_5_source_gate_binds_archive_identity_and_remains_non_authorizing():
    gate = json.loads(SOURCE_GATE_PATH.read_text(encoding="utf-8"))

    assert gate["model_id"] == PINE_V25_MODEL_ID
    assert gate["strategy_version"] == PINE_V25_STRATEGY_VERSION
    assert gate["shadow_transform_sha256"] == PINE_V25_SOURCE_SHA256
    assert gate["shadow_archive_path"] == ARCHIVE_PATH.as_posix()
    assert gate["shadow_archive_encoding"] == "gzip+base64"
    assert gate["shadow_source_status"] == "ARCHIVED_EXACT_TRANSFORM_AND_COMPILED_IN_TRADINGVIEW"
    assert gate["activation_ready"] is False
    assert gate["safety"]["trading_authorized"] is False
    assert gate["safety"]["live_trading_enabled"] is False
    assert gate["safety"]["webhook_activation_authorized"] is False
    assert gate["safety"]["aws_production_deployment_authorized"] is False
