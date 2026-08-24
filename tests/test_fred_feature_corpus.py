import hashlib
import json
from datetime import UTC, datetime

import pytest

from daily_alpha.fred_feature_corpus import (
    FredMacroFeatureSpec,
    build_fred_macro_feature_corpus,
)
from daily_alpha.fred_initial_release import parse_fred_initial_release_history
from daily_alpha.model_training import ModelTrainingError


def _batch(series_id: str, rows: list[tuple[str, str, float]], suffix: str):
    observations = [
        {
            "date": observation_date,
            "realtime_start": realtime_start,
            "realtime_end": realtime_start,
            "value": str(value),
        }
        for observation_date, realtime_start, value in rows
    ]
    raw_body = json.dumps(
        {"observations": observations, "output_type": 4},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(raw_body).hexdigest()
    receipt = {
        "schema": "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1",
        "provider": "FRED",
        "target": series_id,
        "captured_at": "2026-08-24T06:00:00+00:00",
        "capture_mode": "HISTORICAL_BACKFILL",
        "requested_start_date": rows[0][0],
        "requested_end_date": rows[-1][0],
        "known_at_basis": "CAPTURED_AT_ONLY",
        "historical_known_at_backdating_authorized": False,
        "raw_s3_key": (
            f"data-feeds/staging/fred/raw/2026/08/24/{suffix}-{series_id}.json"
        ),
        "raw_sha256": digest,
        "raw_bytes": len(raw_body),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return parse_fred_initial_release_history(raw_body=raw_body, receipt=receipt)


def test_builds_complete_deterministic_macro_feature_matrix():
    dgs10_early = _batch(
        "DGS10",
        [
            ("2026-07-01", "2026-07-01", 4.20),
            ("2026-07-02", "2026-07-02", 4.25),
        ],
        "a",
    )
    dgs10_late = _batch(
        "DGS10",
        [("2026-07-03", "2026-07-03", 4.30)],
        "b",
    )
    dff = _batch(
        "DFF",
        [
            ("2026-07-01", "2026-07-01", 5.33),
            ("2026-07-02", "2026-07-02", 5.33),
            ("2026-07-03", "2026-07-03", 5.34),
        ],
        "c",
    )
    specs = (
        FredMacroFeatureSpec(series_id="DGS10", feature_name="macro_dgs10"),
        FredMacroFeatureSpec(series_id="DFF", feature_name="macro_dff"),
    )
    decisions = (
        datetime(2026, 7, 3, 16, 0, tzinfo=UTC),
        datetime(2026, 7, 4, 16, 0, tzinfo=UTC),
    )

    corpus = build_fred_macro_feature_corpus(
        batches=(dgs10_late, dff, dgs10_early),
        feature_specs=tuple(reversed(specs)),
        security_ids=("SPY", "DINO"),
        decision_times=tuple(reversed(decisions)),
    )
    repeated = build_fred_macro_feature_corpus(
        batches=(dgs10_early, dgs10_late, dff),
        feature_specs=specs,
        security_ids=("DINO", "SPY"),
        decision_times=decisions,
    )

    assert corpus.corpus_id == repeated.corpus_id
    assert corpus.security_ids == ("DINO", "SPY")
    assert corpus.decision_times == decisions
    assert len(corpus.observations) == 8
    assert corpus.labels_created is False
    assert corpus.retuning_authorized is False
    assert corpus.promotion_authorized is False
    assert corpus.paper_mutation_authorized is False
    assert corpus.trading_authorized is False
    assert corpus.live_trading_enabled is False

    lookup = {
        (item.security_id, item.decision_at, item.feature_name): item
        for item in corpus.observations
    }
    assert lookup[("DINO", decisions[0], "macro_dgs10")].feature_value == 4.25
    assert lookup[("DINO", decisions[1], "macro_dgs10")].feature_value == 4.30
    assert lookup[("SPY", decisions[0], "macro_dff")].feature_value == 5.33
    assert lookup[("SPY", decisions[1], "macro_dff")].feature_value == 5.34
    assert all(item.known_at <= item.decision_at for item in corpus.observations)
    assert corpus.source_revisions


def test_rejects_overlapping_bounded_captures_for_same_series():
    first = _batch(
        "DGS10",
        [("2026-07-01", "2026-07-01", 4.20)],
        "a",
    )
    overlapping = _batch(
        "DGS10",
        [("2026-07-01", "2026-07-01", 4.20)],
        "b",
    )

    with pytest.raises(ModelTrainingError, match="FRED_CORPUS_OVERLAPPING_BATCH_DATE"):
        build_fred_macro_feature_corpus(
            batches=(first, overlapping),
            feature_specs=(
                FredMacroFeatureSpec(
                    series_id="DGS10",
                    feature_name="macro_dgs10",
                ),
            ),
            security_ids=("DINO",),
            decision_times=(datetime(2026, 7, 2, 16, 0, tzinfo=UTC),),
        )


def test_fails_closed_when_no_initial_release_was_known_at_decision():
    batch = _batch(
        "DGS10",
        [("2026-07-02", "2026-07-02", 4.25)],
        "a",
    )

    with pytest.raises(ModelTrainingError, match="FRED_CORPUS_NO_VALUE_KNOWN_AT_DECISION"):
        build_fred_macro_feature_corpus(
            batches=(batch,),
            feature_specs=(
                FredMacroFeatureSpec(
                    series_id="DGS10",
                    feature_name="macro_dgs10",
                ),
            ),
            security_ids=("DINO",),
            decision_times=(datetime(2026, 7, 2, 16, 0, tzinfo=UTC),),
        )


def test_rejects_undeclared_or_missing_series():
    dgs10 = _batch(
        "DGS10",
        [("2026-07-01", "2026-07-01", 4.20)],
        "a",
    )
    dff = _batch(
        "DFF",
        [("2026-07-01", "2026-07-01", 5.33)],
        "b",
    )
    decision = (datetime(2026, 7, 2, 16, 0, tzinfo=UTC),)

    with pytest.raises(ModelTrainingError, match="FRED_CORPUS_UNDECLARED_SERIES"):
        build_fred_macro_feature_corpus(
            batches=(dgs10, dff),
            feature_specs=(
                FredMacroFeatureSpec(
                    series_id="DGS10",
                    feature_name="macro_dgs10",
                ),
            ),
            security_ids=("DINO",),
            decision_times=decision,
        )

    with pytest.raises(ModelTrainingError, match="FRED_CORPUS_DECLARED_SERIES_MISSING"):
        build_fred_macro_feature_corpus(
            batches=(dgs10,),
            feature_specs=(
                FredMacroFeatureSpec(
                    series_id="DGS10",
                    feature_name="macro_dgs10",
                ),
                FredMacroFeatureSpec(series_id="DFF", feature_name="macro_dff"),
            ),
            security_ids=("DINO",),
            decision_times=decision,
        )
