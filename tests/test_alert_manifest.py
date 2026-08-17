from daily_alpha.alert_manifest import (
    AlertPlanAction,
    DesiredAlert,
    ObservedAlert,
    desired_alerts_from_ranked_candidates,
    plan_alert_changes,
)
from daily_alpha.candidates import CandidateAssessment, CandidateBucket


def candidate(symbol: str, bucket: CandidateBucket) -> CandidateAssessment:
    return CandidateAssessment(
        symbol=symbol,
        ovtlyr_status="ENTRY_WATCH",
        bucket=bucket,
        score=75.0,
        instrument_selected="NO_TRADE",
        fallback_reason="research-only candidate",
        sector="Technology",
        sector_net_score=10,
        pine_entry=False,
        risk_gate_passed=True,
        optionable=True,
    )


def desired(symbol: str, strategy_version="2.4", timeframe="1D") -> DesiredAlert:
    return DesiredAlert(
        symbol=symbol,
        strategy_version=strategy_version,
        timeframe=timeframe,
        enabled=True,
        source_ranked_at="2026-08-17T05:30:00-07:00",
        review_after="2026-08-18T05:30:00-07:00",
    )


def observed(
    symbol: str,
    strategy_version="2.4",
    timeframe="1D",
    enabled=True,
) -> ObservedAlert:
    return ObservedAlert(
        alert_key=f"alert-{symbol}",
        symbol=symbol,
        strategy_version=strategy_version,
        timeframe=timeframe,
        enabled=enabled,
    )


def plan(desired_items=(), observed_items=(), *, fresh=True, complete=True):
    return plan_alert_changes(
        desired=tuple(desired_items),
        observed=tuple(observed_items),
        source_ranked_at="2026-08-17T05:30:00-07:00",
        strategy_version="2.4",
        source_fresh=fresh,
        source_complete=complete,
    )


def test_candidate_translation_includes_watchable_buckets_only():
    alerts = desired_alerts_from_ranked_candidates(
        candidates=(
            candidate("AAPL", CandidateBucket.ENTRY_WATCH),
            candidate("NVDA", CandidateBucket.OPTION_SETUP),
            candidate("MSFT", CandidateBucket.STOCK_FALLBACK),
            candidate("BAD", CandidateBucket.DATA_ERROR),
            candidate("PASS", CandidateBucket.NO_TRADE),
        ),
        strategy_version="2.4",
        timeframe="1D",
        source_ranked_at="2026-08-17T05:30:00-07:00",
        review_after="2026-08-18T05:30:00-07:00",
    )

    assert [item.symbol for item in alerts] == ["AAPL", "MSFT", "NVDA"]
    assert all(item.strategy_version == "2.4" for item in alerts)


def test_same_input_is_idempotent_no_change():
    result = plan((desired("AAPL"),), (observed("AAPL"),))

    assert result.dry_run is True
    assert result.mutation_allowed is False
    assert result.proposed_mutations == ()
    assert result.items[0].action == AlertPlanAction.NO_CHANGE


def test_added_and_removed_candidates_create_reproducible_diff():
    result = plan(
        (desired("NVDA"),),
        (observed("AAPL"),),
    )

    actions = {item.symbol: item.action for item in result.items}
    assert actions == {
        "AAPL": AlertPlanAction.DISABLE,
        "NVDA": AlertPlanAction.CREATE,
    }
    assert result.mutation_allowed is False


def test_strategy_version_change_requires_explicit_migration():
    result = plan(
        (desired("AAPL", strategy_version="2.4"),),
        (observed("AAPL", strategy_version="2.3"),),
    )

    assert result.items[0].action == AlertPlanAction.MIGRATE_STRATEGY
    assert result.items[0].reason == "EXPLICIT_STRATEGY_VERSION_MIGRATION_REQUIRED"


def test_stale_candidate_source_fails_closed_without_alert_changes():
    result = plan((desired("AAPL"),), (), fresh=False)

    assert result.has_data_error is True
    assert result.proposed_mutations == ()
    assert result.items[0].action == AlertPlanAction.DATA_ERROR
    assert result.items[0].reason == "STALE_CANDIDATE_SOURCE"


def test_incomplete_candidate_source_fails_closed():
    result = plan((desired("AAPL"),), (), complete=False)

    assert result.has_data_error is True
    assert result.items[0].reason == "INCOMPLETE_CANDIDATE_SOURCE"


def test_configuration_drift_is_update_not_silent_mutation():
    result = plan(
        (desired("AAPL", timeframe="1D"),),
        (observed("AAPL", timeframe="4H"),),
    )

    assert result.items[0].action == AlertPlanAction.UPDATE
    assert result.items[0].reason == "CONFIGURATION_DRIFT"
    assert result.mutation_allowed is False
