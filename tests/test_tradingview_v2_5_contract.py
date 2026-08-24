from __future__ import annotations

import hashlib
from pathlib import Path

from daily_alpha.pine_v25_armed_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_COMMIT,
    PINE_V25_SOURCE_SHA256,
    PINE_V25_STRATEGY_VERSION,
)
from daily_alpha.pine_v25_parity import PINE_V25_SOURCE_BLOB_SHA, PINE_V25_SOURCE_PATH


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def test_v2_5_frozen_source_is_present_and_exactly_matches_audited_lineage():
    source = Path(PINE_V25_SOURCE_PATH)
    data = source.read_bytes()

    assert source.is_file()
    assert PINE_V25_MODEL_ID == "PAPER_SHADOW_V25"
    assert PINE_V25_STRATEGY_VERSION == "2.5"
    assert PINE_V25_SOURCE_COMMIT == "b2a214c6b7a689453df5de7bb870c352456ebe8c"
    assert _git_blob_sha(data) == PINE_V25_SOURCE_BLOB_SHA
    assert hashlib.sha256(data).hexdigest() == PINE_V25_SOURCE_SHA256


def test_v2_5_frozen_source_preserves_close_order_and_research_only_safety_semantics():
    pine = Path(PINE_V25_SOURCE_PATH).read_text()

    assert "DAILY ALPHA v2.5 RESEARCH CHALLENGER" in pine
    assert "PAPER / RESEARCH ONLY." in pine
    assert "process_orders_on_close=true" in pine
    assert "calc_on_every_tick=false" in pine
    assert "calc_on_order_fills=false" in pine
    assert 'shorttitle="DA-T20/10-SH25"' in pine
    assert '"Enable Paper Shadow Forward Test"' in pine
    assert '"Attach v2.5 Shadow Webhook Messages"' in pine
