from datetime import date

import pytest

from daily_alpha.pre_catalyst import (
    CatalystType,
    PreCatalystClass,
    PreCatalystObservation,
    PublicCatalyst,
    classify_pre_catalyst,
)


def _event(**overrides):
    values = {
        "ticker": "ANET",
        "event_type": CatalystType.CONFERENCE,
        "event_date": date(2026, 9, 15),
        "event_known_date": date(2026, 8, 20),
        "source_id": "issuer-ir-2026-08-20",
    }
    values.update(overrides)
    return PublicCatalyst(**values)


def _observation(**overrides):
    values = {
        "as_of_date": date(2026, 9, 1),
        "sessions_until_event": 10,
        "excess_return_10d_pct": 5.0,
        "relative_strength_acceleration": 0.8,
        "relative_volume": 1.6,
        "distance_to_20d_high_pct": 1.0,
        "bullish_trend_state": True,
        "options_positioning_score": 12.0,
    }
    values.update(overrides)
    return PreCatalystObservation(**values)


def test_event_cannot_enter_research_before_public_known_date():
    result = classify_pre_catalyst(
        _event(),
        _observation(as_of_date=date(2026, 8, 19), sessions_until_event=18),
    )

    assert result.classification == PreCatalystClass.NOT_PUBLICLY_KNOWN
    assert result.event_visible is False
    assert result.research_eligible is False
    assert "EVENT_NOT_YET_PUBLIC" in result.reason_codes


def test_strong_public_pre_catalyst_setup_can_classify_as_run():
    result = classify_pre_catalyst(_event(), _observation())

    assert result.classification == PreCatalystClass.PRE_CATALYST_RUN
    assert result.event_visible is True
    assert result.research_eligible is True
    assert result.score >= 70.0
    assert "RELATIVE_STRENGTH_ACCELERATING" in result.reason_codes
    assert "VOLUME_ACCUMULATION" in result.reason_codes


def test_weaker_setup_remains_watch_not_trade_authorization():
    result = classify_pre_catalyst(
        _event(),
        _observation(
            excess_return_10d_pct=-1.0,
            relative_strength_acceleration=-0.2,
            relative_volume=1.0,
            distance_to_20d_high_pct=7.0,
            bullish_trend_state=False,
            options_positioning_score=0.0,
        ),
    )

    assert result.classification == PreCatalystClass.PRE_CATALYST_WATCH
    assert result.research_eligible is True
    assert result.score < 70.0


def test_event_day_is_outside_pre_catalyst_window():
    result = classify_pre_catalyst(
        _event(),
        _observation(as_of_date=date(2026, 9, 15), sessions_until_event=0),
    )

    assert result.classification == PreCatalystClass.OUTSIDE_WINDOW
    assert result.research_eligible is False


def test_invalid_known_date_fails_closed():
    with pytest.raises(ValueError):
        classify_pre_catalyst(
            _event(event_known_date=date(2026, 9, 16)),
            _observation(),
        )
