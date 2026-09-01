import json

from daily_alpha.strategy_forensics import (
    OpportunityPath,
    compare_model_decisions,
    diagnose_opportunity,
)
from daily_alpha.strategy_forensics_artifact import write_strategy_forensics_artifacts


def test_forensics_writer_publishes_deterministic_research_only_artifacts(tmp_path):
    diagnostics = [
        diagnose_opportunity(
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
        ),
        diagnose_opportunity(
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
        ),
    ]
    disagreement = compare_model_decisions(
        symbol="AMD",
        champion_version="2.4",
        challenger_version="2.5",
        champion_decision="WAIT",
        challenger_decision="ENTRY",
        champion_reason="ADX_TOO_LOW",
        challenger_reason="ARMED_BREAKOUT_CONFIRM",
    )

    paths = write_strategy_forensics_artifacts(
        tmp_path,
        reversed(diagnostics),
        disagreements=[disagreement],
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert [item["symbol"] for item in payload["diagnostics"]] == ["AMD", "CAT"]
    assert payload["summary"]["observations"] == 2
    assert payload["summary"]["missed_winner_count"] == 1
    assert payload["research_only"] is True
    assert payload["trading_authorized"] is False
    assert payload["live_trading_enabled"] is False

    model_payload = json.loads(
        paths["model_disagreements"].read_text(encoding="utf-8")
    )
    assert model_payload["count"] == 1
    assert model_payload["disagreement_count"] == 1
    assert model_payload["observations"][0]["symbol"] == "AMD"
    assert model_payload["trading_authorized"] is False
    assert model_payload["live_trading_enabled"] is False

    csv_text = paths["csv"].read_text(encoding="utf-8")
    assert "AMD" in csv_text
    assert "CAT" in csv_text
