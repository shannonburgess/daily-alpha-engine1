import hashlib
import json
from datetime import UTC, datetime

import pytest

from daily_alpha.fred_feature_corpus import (
    FredMacroFeatureSpec,
    build_fred_macro_feature_corpus,
)
from daily_alpha.fred_initial_release import parse_fred_initial_release_history
from daily_alpha.fred_training_dataset import build_fred_macro_training_dataset
from daily_alpha.model_dataset_builder import (
    RealizedRLabelObservation,
    TrainingDatasetAssemblyPolicy,
)
from daily_alpha.model_training import ModelTrainingError


def _batch():
    raw_body = json.dumps(
        {
            "observations": [
                {
                    "date": "2026-07-01",
                    "realtime_start": "2026-07-01",
                    "realtime_end": "2026-07-01",
                    "value": "4.20",
                },
                {
                    "date": "2026-07-02",
                    "realtime_start": "2026-07-02",
                    "realtime_end": "2026-07-02",
                    "value": "4.25",
                },
            ],
            "output_type": 4,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    receipt = {
        "schema": "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1",
        "provider": "FRED",
        "target": "DGS10",
        "captured_at": "2026-08-24T06:00:00+00:00",
        "capture_mode": "HISTORICAL_BACKFILL",
        "requested_start_date": "2026-07-01",
        "requested_end_date": "2026-07-02",
        "known_at_basis": "CAPTURED_AT_ONLY",
        "historical_known_at_backdating_authorized": False,
        "raw_s3_key": "data-feeds/staging/fred/raw/2026/08/24/a-DGS10.json",
        "raw_sha256": hashlib.sha256(raw_body).hexdigest(),
        "raw_bytes": len(raw_body),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return parse_fred_initial_release_history(raw_body=raw_body, receipt=receipt)


def _corpus():
    return build_fred_macro_feature_corpus(
        batches=(_batch(),),
        feature_specs=(
            FredMacroFeatureSpec(
                series_id="DGS10",
                feature_name="macro_dgs10",
            ),
        ),
        security_ids=("DINO",),
        decision_times=(
            datetime(2026, 7, 2, 16, 0, tzinfo=UTC),
            datetime(2026, 7, 3, 16, 0, tzinfo=UTC),
        ),
    )


def _policy(*, feature_name: str = "macro_dgs10"):
    return TrainingDatasetAssemblyPolicy(
        feature_schema_version="fred-macro-v1",
        label_definition="realized-r-1d-v1",
        required_feature_names=(feature_name,),
        label_horizon_days=1,
    )


def _labels():
    decisions = _corpus().decision_times
    return (
        RealizedRLabelObservation(
            security_id="DINO",
            decision_at=decisions[0],
            horizon_days=1,
            realized_r=0.50,
            known_at=datetime(2026, 7, 3, 21, 0, tzinfo=UTC),
            evidence_ids=("label-evidence-1",),
            source_revision="label-source-v1",
        ),
        RealizedRLabelObservation(
            security_id="DINO",
            decision_at=decisions[1],
            horizon_days=1,
            realized_r=-0.25,
            known_at=datetime(2026, 7, 4, 21, 0, tzinfo=UTC),
            evidence_ids=("label-evidence-2",),
            source_revision="label-source-v1",
        ),
    )


def test_binds_exact_corpus_to_immutable_training_dataset():
    corpus = _corpus()
    labels = _labels()
    packet = build_fred_macro_training_dataset(
        corpus=corpus,
        policy=_policy(),
        label_observations=tuple(reversed(labels)),
        as_of=datetime(2026, 7, 5, 0, 0, tzinfo=UTC),
    )
    repeated = build_fred_macro_training_dataset(
        corpus=corpus,
        policy=_policy(),
        label_observations=labels,
        as_of=datetime(2026, 7, 5, 0, 0, tzinfo=UTC),
    )

    assert packet.packet_id == repeated.packet_id
    assert packet.corpus_id == corpus.corpus_id
    assert packet.dataset_id == packet.assembly.dataset.dataset_id
    assert len(packet.assembly.dataset.examples) == 2
    assert set(packet.assembly.included_feature_observation_ids) == {
        item.observation_id for item in corpus.observations
    }
    assert packet.labels_created is False
    assert packet.retuning_authorized is False
    assert packet.promotion_authorized is False
    assert packet.paper_mutation_authorized is False
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False


def test_preserves_immature_label_exclusion_without_dropping_corpus_lineage():
    corpus = _corpus()
    labels = _labels()
    packet = build_fred_macro_training_dataset(
        corpus=corpus,
        policy=_policy(),
        label_observations=labels,
        as_of=datetime(2026, 7, 4, 12, 0, tzinfo=UTC),
    )

    assert len(packet.assembly.dataset.examples) == 1
    assert packet.assembly.excluded_immature_label_ids == (labels[1].label_id,)
    assert packet.corpus_id == corpus.corpus_id
    assert packet.batch_ids == corpus.batch_ids
    assert packet.corpus_source_revisions == corpus.source_revisions


def test_rejects_policy_that_does_not_match_fred_corpus_feature_schema():
    with pytest.raises(ModelTrainingError, match="FRED_TRAINING_FEATURE_SCHEMA_MISMATCH"):
        build_fred_macro_training_dataset(
            corpus=_corpus(),
            policy=_policy(feature_name="different_macro_feature"),
            label_observations=_labels(),
            as_of=datetime(2026, 7, 5, 0, 0, tzinfo=UTC),
        )


def test_rejects_label_row_outside_declared_corpus_matrix():
    labels = list(_labels())
    labels.append(
        RealizedRLabelObservation(
            security_id="SPY",
            decision_at=datetime(2026, 7, 2, 16, 0, tzinfo=UTC),
            horizon_days=1,
            realized_r=0.10,
            known_at=datetime(2026, 7, 3, 21, 0, tzinfo=UTC),
            evidence_ids=("outside-label",),
            source_revision="label-source-v1",
        )
    )

    with pytest.raises(ModelTrainingError, match="LABEL_WITHOUT_FEATURE_ROW"):
        build_fred_macro_training_dataset(
            corpus=_corpus(),
            policy=_policy(),
            label_observations=labels,
            as_of=datetime(2026, 7, 5, 0, 0, tzinfo=UTC),
        )


def test_packet_does_not_turn_capability_into_empirical_or_execution_authority():
    packet = build_fred_macro_training_dataset(
        corpus=_corpus(),
        policy=_policy(),
        label_observations=_labels(),
        as_of=datetime(2026, 7, 5, 0, 0, tzinfo=UTC),
    )

    assert packet.research_only is True
    assert packet.assembly.paper_mutation_authorized is False
    assert packet.assembly.trading_authorized is False
    assert packet.assembly.live_trading_enabled is False
    assert packet.assembly.dataset.training_authorized is False
    assert packet.assembly.dataset.paper_mutation_authorized is False
    assert packet.assembly.dataset.trading_authorized is False
    assert packet.assembly.dataset.live_trading_enabled is False
