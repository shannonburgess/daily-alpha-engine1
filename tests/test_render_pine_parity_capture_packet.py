from __future__ import annotations

import json

from scripts.render_pine_parity_capture_packet import render


def test_renderer_writes_deterministic_research_only_capture_packet(tmp_path):
    output = tmp_path / "capture.json"
    packet = render(symbol="dino", output=output)
    stored = json.loads(output.read_text(encoding="utf-8"))

    assert stored == packet
    assert packet["symbol"] == "DINO"
    assert len(packet["packet_id"]) == 64
    assert packet["trading_authorized"] is False
    assert packet["live_trading_enabled"] is False
    assert all(value is None for value in packet["sh24"]["parameter_manifest"]["parameters"].values())
    assert all(value is None for value in packet["sh25"]["parameter_manifest"]["parameters"].values())
