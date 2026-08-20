from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.shadow_universe_monitor import summarize


def _summary(now: datetime) -> dict[str, object]:
    return {
        "generated_at": (now - timedelta(hours=2)).isoformat(),
        "current_file": "OVTLYR_2026-08-19.csv",
        "actionable_ranked_count": 2,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _shortlist() -> list[dict[str, object]]:
    return [
        {"rank": 1, "symbol": "NVDA", "ovtlyr_status": "LEADER", "score": 88.0},
        {"rank": 2, "symbol": "MU", "ovtlyr_status": "EMERGING", "score": 82.0},
    ]


def test_healthy_universe_is_read_only_and_fingerprinted() -> None:
    now = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
    status = summarize(_summary(now), _shortlist(), now=now)

    assert status["ok"] is True
    assert status["actionable_count"] == 2
    assert len(status["universe_fingerprint_sha256"]) == 64
    assert status["trading_authorized"] is False
    assert status["live_trading_enabled"] is False
    assert status["tradingview_private_alert_universe_observable"] is False


def test_stale_universe_fails_closed() -> None:
    now = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
    summary = _summary(now)
    summary["generated_at"] = (now - timedelta(hours=19)).isoformat()

    status = summarize(summary, _shortlist(), now=now)

    assert status["ok"] is False
    assert "UNIVERSE_STALE" in status["violations"]


def test_count_and_duplicate_symbol_mismatch_fail_closed() -> None:
    now = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
    rows = _shortlist()
    rows[1]["symbol"] = "NVDA"
    summary = _summary(now)
    summary["actionable_ranked_count"] = 3

    status = summarize(summary, rows, now=now)

    assert status["ok"] is False
    assert "UNIVERSE_SHORTLIST_COUNT_MISMATCH" in status["violations"]
    assert "UNIVERSE_DUPLICATE_SYMBOL:NVDA" in status["violations"]


def test_rank_sequence_and_safety_drift_fail_closed() -> None:
    now = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
    rows = _shortlist()
    rows[1]["rank"] = 3
    summary = _summary(now)
    summary["live_trading_enabled"] = True

    status = summarize(summary, rows, now=now)

    assert status["ok"] is False
    assert "UNIVERSE_RANK_SEQUENCE_INVALID:MU" in status["violations"]
    assert "UNIVERSE_LIVE_TRADING_NOT_FALSE" in status["violations"]


def test_universe_fingerprint_is_deterministic_for_same_ranked_rows() -> None:
    now = datetime(2026, 8, 19, 23, 30, tzinfo=UTC)
    first = summarize(_summary(now), _shortlist(), now=now)
    second = summarize(_summary(now), _shortlist(), now=now)

    assert first["universe_fingerprint_sha256"] == second["universe_fingerprint_sha256"]
