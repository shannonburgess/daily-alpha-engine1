from __future__ import annotations

from datetime import UTC, datetime

from scripts.shadow_liquidity_monitor import summarize


def summary(**overrides):
    value = {
        "generated_at": "2026-08-20T10:00:00+00:00",
        "current_file": "OVTLYR_2026-08-20.csv",
        "actionable_ranked_count": 2,
        "company_average_volume_gate_enabled": True,
        "company_min_average_volume": 1_500_000.0,
        "excluded_liquidity_filtered": 1,
        "excluded_liquidity_missing": 1,
        "etf_separate_liquidity_count": 1,
        "liquidity_evidence_file": "company_liquidity_eligibility.json",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    value.update(overrides)
    return value


def evidence(**overrides):
    value = {
        "schema_version": "2026-08-19-v1",
        "source": "OVTLYR_30_DAY_AVG_VOLUME",
        "source_file": "OVTLYR_2026-08-20.csv",
        "source_date": "2026-08-20",
        "generated_at": "2026-08-20T10:00:00+00:00",
        "company_min_average_volume": 1_500_000.0,
        "company_threshold_semantics": "STRICTLY_GREATER_THAN",
        "rows": [
            {
                "symbol": "AAPL",
                "security_type": "COMPANY_EQUITY",
                "average_daily_share_volume_30d": 50_000_000.0,
                "status": "ELIGIBLE",
                "detail": "STRICTLY_ABOVE_THRESHOLD",
                "actionable_liquidity": True,
            },
            {
                "symbol": "LOWV",
                "security_type": "COMPANY_EQUITY",
                "average_daily_share_volume_30d": 1_500_000.0,
                "status": "LIQUIDITY_FILTERED",
                "detail": "AT_OR_BELOW_THRESHOLD",
                "actionable_liquidity": False,
            },
            {
                "symbol": "MISS",
                "security_type": "COMPANY_EQUITY",
                "average_daily_share_volume_30d": None,
                "status": "LIQUIDITY_FILTERED",
                "detail": "MISSING_OR_NONPOSITIVE_VOLUME",
                "actionable_liquidity": False,
            },
            {
                "symbol": "SPY",
                "security_type": "ETF",
                "average_daily_share_volume_30d": 500_000.0,
                "status": "ETF_SEPARATE_RULES",
                "detail": "COMPANY_SHARE_VOLUME_GATE_NOT_APPLIED",
                "actionable_liquidity": True,
            },
        ],
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    value.update(overrides)
    return value


def shortlist():
    return [
        {"rank": 1, "symbol": "AAPL"},
        {"rank": 2, "symbol": "SPY"},
    ]


def test_pre_rollout_shortlist_can_wait_for_first_liquidity_publication():
    status = summarize(
        summary(generated_at="2026-08-20T03:00:00+00:00"),
        shortlist(),
        evidence=None,
        evidence_found=False,
    )

    assert status["ok"] is True
    assert status["state"] == "PENDING_FIRST_POST_MERGE_PUBLICATION"
    assert status["evidence_found"] is False


def test_post_rollout_missing_liquidity_evidence_fails_closed():
    status = summarize(
        summary(),
        shortlist(),
        evidence=None,
        evidence_found=False,
    )

    assert status["ok"] is False
    assert "LIQUIDITY_EVIDENCE_MISSING_AFTER_ROLLOUT" in status["violations"]


def test_valid_company_and_etf_liquidity_contract_passes():
    status = summarize(
        summary(),
        shortlist(),
        evidence=evidence(),
        evidence_found=True,
    )

    assert status["ok"] is True
    assert status["state"] == "ACTIVE"
    assert status["eligible_company_count"] == 1
    assert status["filtered_company_count"] == 1
    assert status["missing_volume_company_count"] == 1
    assert status["etf_count"] == 1


def test_company_at_threshold_cannot_appear_in_actionable_shortlist():
    status = summarize(
        summary(actionable_ranked_count=1),
        [{"rank": 1, "symbol": "LOWV"}],
        evidence=evidence(),
        evidence_found=True,
    )

    assert status["ok"] is False
    assert "LIQUIDITY_FILTERED_COMPANY_IN_SHORTLIST:LOWV" in status["violations"]


def test_liquidity_source_mismatch_fails_closed():
    status = summarize(
        summary(current_file="OVTLYR_2026-08-21.csv"),
        shortlist(),
        evidence=evidence(),
        evidence_found=True,
    )

    assert status["ok"] is False
    assert "LIQUIDITY_SHORTLIST_SOURCE_MISMATCH" in status["violations"]


def test_etf_is_not_forced_through_company_share_volume_threshold():
    status = summarize(
        summary(),
        shortlist(),
        evidence=evidence(),
        evidence_found=True,
    )

    assert status["ok"] is True
    assert "LIQUIDITY_FILTERED_COMPANY_IN_SHORTLIST:SPY" not in status["violations"]


def test_rollout_timestamp_is_timezone_aware_in_tests():
    assert datetime(2026, 8, 20, 3, 54, 57, tzinfo=UTC).utcoffset() is not None
