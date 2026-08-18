import pytest

from daily_alpha.earnings_early_research import (
    EarlyConfirmationRule,
    EarlyEventPath,
    compare_early_entry_paths,
    first_confirmation,
)


def test_t_plus_one_close_above_event_high_confirms():
    path = EarlyEventPath(
        event_close=100.0,
        event_high=105.0,
        forward_closes=(106.0, 108.0),
        exit_price=120.0,
    )

    assert first_confirmation(path) == (1, 106.0)


def test_confirmation_can_wait_until_t_plus_two():
    path = EarlyEventPath(
        event_close=100.0,
        event_high=105.0,
        forward_closes=(104.0, 107.0, 110.0),
        exit_price=120.0,
    )

    assert first_confirmation(path, max_days=2) == (2, 107.0)
    assert first_confirmation(path, max_days=1) is None


def test_close_above_event_close_is_separate_looser_research_rule():
    path = EarlyEventPath(
        event_close=100.0,
        event_high=105.0,
        forward_closes=(102.0,),
        exit_price=110.0,
    )

    assert first_confirmation(path) is None
    assert first_confirmation(
        path,
        rule=EarlyConfirmationRule.CLOSE_ABOVE_EVENT_CLOSE,
    ) == (1, 102.0)


def test_compare_paths_keeps_no_entry_and_starter_only_separate():
    path = EarlyEventPath(
        event_close=100.0,
        event_high=105.0,
        forward_closes=(106.0,),
        exit_price=120.0,
    )

    no_entry, starter, scaled = compare_early_entry_paths(path)

    assert no_entry.scenario == "NO_ENTRY"
    assert no_entry.normalized_return_pct == 0.0
    assert starter.scenario == "STARTER_ONLY"
    assert starter.normalized_return_pct == pytest.approx(5.0)
    assert scaled.scenario == "STARTER_THEN_CONFIRM"
    assert scaled.final_fraction == 0.50
    assert scaled.confirmation_day == 1
    assert scaled.normalized_return_pct > starter.normalized_return_pct


def test_no_confirmation_never_scales_exposure():
    path = EarlyEventPath(
        event_close=100.0,
        event_high=105.0,
        forward_closes=(103.0, 104.0),
        exit_price=90.0,
    )

    _, starter, scaled = compare_early_entry_paths(path)

    assert scaled.confirmation_day is None
    assert scaled.final_fraction == 0.25
    assert scaled.normalized_return_pct == starter.normalized_return_pct


def test_invalid_fraction_policy_fails_closed():
    path = EarlyEventPath(
        event_close=100.0,
        event_high=105.0,
        forward_closes=(106.0,),
        exit_price=120.0,
    )

    with pytest.raises(ValueError):
        compare_early_entry_paths(path, starter_fraction=0.60, full_fraction=0.50)
