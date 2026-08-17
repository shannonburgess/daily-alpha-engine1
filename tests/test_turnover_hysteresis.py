import pytest

from daily_alpha.turnover_hysteresis import (
    CandidateState,
    HysteresisAction,
    HysteresisConfig,
    evaluate_hysteresis,
    qualifies_for_entry,
    qualifies_for_hold,
)


def config(**overrides):
    values = {
        "entry_score_min": 80.0,
        "hold_score_min": 70.0,
        "replace_edge_min": 8.0,
        "soft_persistence_days": 2,
        "entry_rank_max": 10,
        "hold_rank_max": 15,
    }
    values.update(overrides)
    return HysteresisConfig(**values)


def test_config_requires_hold_threshold_not_above_entry_threshold():
    with pytest.raises(ValueError, match="hold_score_min"):
        HysteresisConfig(entry_score_min=70, hold_score_min=80, replace_edge_min=5)


def test_config_requires_hold_rank_region_at_least_as_wide_as_entry_region():
    with pytest.raises(ValueError, match="hold_rank_max"):
        config(entry_rank_max=10, hold_rank_max=5)


def test_flat_portfolio_enters_only_when_challenger_meets_score_and_rank():
    cfg = config()
    qualifying = CandidateState(score=82, rank=8)
    weak_score = CandidateState(score=79, rank=8)
    weak_rank = CandidateState(score=90, rank=11)

    assert qualifies_for_entry(qualifying, cfg)
    assert not qualifies_for_entry(weak_score, cfg)
    assert not qualifies_for_entry(weak_rank, cfg)

    assert (
        evaluate_hysteresis(incumbent=None, challenger=qualifying, config=cfg).action
        == HysteresisAction.ENTER
    )
    assert (
        evaluate_hysteresis(incumbent=None, challenger=weak_score, config=cfg).action
        == HysteresisAction.NO_ACTION
    )


def test_hold_region_is_wider_than_entry_region():
    cfg = config()
    incumbent = CandidateState(score=72, rank=14)

    assert not qualifies_for_entry(incumbent, cfg)
    assert qualifies_for_hold(incumbent, cfg)
    decision = evaluate_hysteresis(incumbent=incumbent, challenger=None, config=cfg)
    assert decision.action == HysteresisAction.HOLD


def test_small_challenger_edge_does_not_force_churn():
    cfg = config()
    incumbent = CandidateState(score=78, rank=12)
    challenger = CandidateState(score=84, rank=5)

    decision = evaluate_hysteresis(incumbent=incumbent, challenger=challenger, config=cfg)

    assert decision.challenger_edge == 6
    assert decision.action == HysteresisAction.HOLD


def test_qualified_challenger_replaces_when_edge_is_large_enough():
    cfg = config()
    incumbent = CandidateState(score=74, rank=14)
    challenger = CandidateState(score=84, rank=5)

    decision = evaluate_hysteresis(incumbent=incumbent, challenger=challenger, config=cfg)

    assert decision.challenger_edge == 10
    assert decision.action == HysteresisAction.REPLACE


def test_additional_capacity_edge_raises_replacement_hurdle():
    cfg = config()
    incumbent = CandidateState(score=74, rank=14)
    challenger = CandidateState(score=84, rank=5)

    decision = evaluate_hysteresis(
        incumbent=incumbent,
        challenger=challenger,
        config=cfg,
        additional_replace_edge=4,
    )

    assert decision.effective_replace_edge_min == 12
    assert decision.action == HysteresisAction.HOLD


def test_soft_persistence_holds_temporarily_when_incumbent_leaves_hold_region():
    cfg = config(soft_persistence_days=2)
    incumbent = CandidateState(score=68, rank=16)

    day_one = evaluate_hysteresis(
        incumbent=incumbent,
        challenger=None,
        config=cfg,
        days_below_hold=1,
    )
    day_two = evaluate_hysteresis(
        incumbent=incumbent,
        challenger=None,
        config=cfg,
        days_below_hold=2,
    )

    assert day_one.action == HysteresisAction.HOLD_PERSISTENCE
    assert day_two.action == HysteresisAction.EXIT_SOFT


def test_challenger_must_qualify_for_new_entry_before_replacement():
    cfg = config()
    incumbent = CandidateState(score=68, rank=16)
    challenger = CandidateState(score=90, rank=20)

    decision = evaluate_hysteresis(
        incumbent=incumbent,
        challenger=challenger,
        config=cfg,
        days_below_hold=2,
    )

    assert decision.challenger_edge == 22
    assert decision.action == HysteresisAction.EXIT_SOFT


def test_hard_exit_always_overrides_hysteresis_and_challenger():
    cfg = config()
    incumbent = CandidateState(score=90, rank=1)
    challenger = CandidateState(score=100, rank=1)

    decision = evaluate_hysteresis(
        incumbent=incumbent,
        challenger=challenger,
        config=cfg,
        hard_exit=True,
    )

    assert decision.action == HysteresisAction.EXIT_HARD
    assert "overrides" in decision.reason
    assert decision.research_only is True


def test_negative_dynamic_inputs_fail_closed():
    cfg = config()
    incumbent = CandidateState(score=75, rank=10)

    with pytest.raises(ValueError, match="days_below_hold"):
        evaluate_hysteresis(
            incumbent=incumbent,
            challenger=None,
            config=cfg,
            days_below_hold=-1,
        )

    with pytest.raises(ValueError, match="additional_replace_edge"):
        evaluate_hysteresis(
            incumbent=incumbent,
            challenger=None,
            config=cfg,
            additional_replace_edge=-1,
        )
