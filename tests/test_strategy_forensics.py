from daily_alpha.strategy_forensics import (
    OpportunityPath,
    compare_model_decisions,
    diagnose_opportunity,
    summarize_forensics,
)


def test_wait_that_runs_three_r_is_classified_as_missed_winner():
    diagnostic = diagnose_opportunity(
        OpportunityPath(
            symbol="AMD",
            strategy_version="2.4",
            decision="WAIT",
            reason="ADX_TOO_LOW",
            reference_price=100.0,
            stop_price=95.0,
            max_price_after=115.0,
            min_price_after=98.0,
            terminal_price=112.0,
            bars_observed=20,
        )
    )

    assert diagnostic.mfe_r == 3.0
    assert diagnostic.mae_r == -0.4
    assert diagnostic.missed_r == 3.0
    assert diagnostic.classification == "MISSED_WINNER"
    assert diagnostic.trading_authorized is False
    assert diagnostic.live_trading_enabled is False


def test_executed_early_exit_measures_capture_and_remaining_runner():
    diagnostic = diagnose_opportunity(
        OpportunityPath(
            symbol="CAT",
            strategy_version="2.4",
            decision="ENTRY",
            reason="NORMAL_BREAKOUT",
            reference_price=100.0,
            stop_price=95.0,
            max_price_after=120.0,
            min_price_after=99.0,
            terminal_price=118.0,
            bars_observed=30,
            executed=True,
            exit_price=108.0,
        )
    )

    assert diagnostic.mfe_r == 4.0
    assert diagnostic.realized_r == 1.6
    assert diagnostic.mfe_capture_pct == 40.0
    assert diagnostic.missed_r == 2.4
    assert diagnostic.classification == "EARLY_EXIT_MISSED_RUNNER"


def test_forensics_summary_attributes_missed_r_by_reason():
    diagnostics = [
        diagnose_opportunity(
            OpportunityPath(
                symbol="AAA",
                strategy_version="2.4",
                decision="WAIT",
                reason="ADX_TOO_LOW",
                reference_price=100.0,
                stop_price=95.0,
                max_price_after=115.0,
                min_price_after=99.0,
                terminal_price=110.0,
                bars_observed=20,
            )
        ),
        diagnose_opportunity(
            OpportunityPath(
                symbol="BBB",
                strategy_version="2.4",
                decision="WAIT",
                reason="ADX_TOO_LOW",
                reference_price=50.0,
                stop_price=45.0,
                max_price_after=52.0,
                min_price_after=44.0,
                terminal_price=46.0,
                bars_observed=20,
            )
        ),
    ]

    summary = summarize_forensics(diagnostics)

    assert summary["observations"] == 2
    assert summary["missed_winner_count"] == 1
    assert summary["by_reason"][0]["reason"] == "ADX_TOO_LOW"
    assert summary["by_reason"][0]["observations"] == 2
    assert summary["by_reason"][0]["missed_winners"] == 1
    assert summary["research_only"] is True
    assert summary["trading_authorized"] is False


def test_champion_challenger_disagreement_is_explicit():
    observation = compare_model_decisions(
        symbol="VLO",
        champion_version="2.4",
        challenger_version="2.5",
        champion_decision="WAIT",
        challenger_decision="ENTRY",
        champion_reason="FRESH_BREAKOUT_CONSUMED",
        challenger_reason="ARMED_BREAKOUT_CONFIRM",
    )

    assert observation.disagrees is True
    assert observation.champion_decision == "WAIT"
    assert observation.challenger_decision == "ENTRY"
    assert observation.research_only is True
    assert observation.trading_authorized is False
