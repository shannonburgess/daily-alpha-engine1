from daily_alpha.staging_reporting import _packet_from_shortlist


def _row():
    return {
        "symbol": "AAA",
        "ovtlyr_status": "ACTIVE_BUY",
        "display_label": "ACTIVE BUY",
        "score": 42.0,
        "orats_status": "DATA_ERROR",
        "orats_reason": "ORATS_DATA_ERROR",
        "sector": "Technology",
        "classification_reason": "Ongoing OVTLYR BUY state.",
    }


def test_active_buy_continuity_is_visible_in_customer_facing_candidate_reasons():
    packet = _packet_from_shortlist(
        [_row()],
        report_date="2026-08-19",
        run_id="test",
        generated_at="2026-08-19T06:30:00+00:00",
        buy_continuity={
            "AAA": {
                "current_buy_streak_start": "2026-08-15",
                "consecutive_buy_observations": 4,
                "last_meaningful_change_date": "2026-08-15",
                "research_eligibility": "ACTIVE_BUY_ELIGIBLE",
            }
        },
    )

    candidate = packet.candidates[0]
    assert candidate.signal_label == "ACTIVE BUY"
    assert candidate.data_status == "DATA_ERROR"
    assert "BUY_STREAK_START=2026-08-15" in candidate.reasons
    assert "BUY_OBSERVATIONS=4" in candidate.reasons
    assert "BUY_LAST_CHANGE=2026-08-15" in candidate.reasons
    assert "BUY_ELIGIBILITY=ACTIVE_BUY_ELIGIBLE" in candidate.reasons


def test_shortlist_candidate_remains_readable_without_continuity_record():
    packet = _packet_from_shortlist(
        [_row()],
        report_date="2026-08-19",
        run_id="test",
        generated_at="2026-08-19T06:30:00+00:00",
        buy_continuity={},
    )

    candidate = packet.candidates[0]
    assert candidate.signal_label == "ACTIVE BUY"
    assert not any(reason.startswith("BUY_STREAK_START=") for reason in candidate.reasons)
