import json
from datetime import UTC, datetime, timedelta

from daily_alpha.strategy_forensics import diagnose_opportunity
from daily_alpha.strategy_forensics_artifact import write_strategy_forensics_artifacts
from daily_alpha.strategy_forensics_observations import (
    DecisionObservation,
    PriceBarObservation,
    build_forensics_path,
)


def test_writer_archives_cutoff_bounded_path_evidence(tmp_path):
    observed_at = datetime(2026, 8, 18, 20, 0, tzinfo=UTC)
    evidence = build_forensics_path(
        DecisionObservation(
            decision_id="wait-aaa-20260818",
            symbol="AAA",
            strategy_version="v2.4",
            decision="WAIT",
            reason="ADX_BELOW_GATE",
            observed_at=observed_at,
            reference_price=100.0,
            stop_price=95.0,
        ),
        (
            PriceBarObservation(
                observed_at=observed_at + timedelta(hours=1),
                high=105.0,
                low=99.0,
                close=104.0,
            ),
            PriceBarObservation(
                observed_at=observed_at + timedelta(hours=2),
                high=112.0,
                low=103.0,
                close=110.0,
            ),
        ),
        evaluation_cutoff=observed_at + timedelta(hours=2),
    )
    diagnostic = diagnose_opportunity(evidence.path)

    paths = write_strategy_forensics_artifacts(
        tmp_path,
        [diagnostic],
        path_evidence=[evidence],
    )

    primary = json.loads(paths["json"].read_text(encoding="utf-8"))
    archived = json.loads(paths["path_evidence"].read_text(encoding="utf-8"))

    assert primary["path_evidence_count"] == 1
    assert archived["count"] == 1
    assert archived["cutoff_bounded"] is True
    assert archived["observations"][0]["decision_id"] == "wait-aaa-20260818"
    assert archived["observations"][0]["bars_used"] == 2
    assert archived["observations"][0]["path"]["max_price_after"] == 112.0
    assert archived["trading_authorized"] is False
    assert archived["live_trading_enabled"] is False
