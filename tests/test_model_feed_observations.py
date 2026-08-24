from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.model_feed_observations import (
    FeedFeatureFact,
    build_point_in_time_feed_observations,
    validate_immutable_feed_evidence,
)
from daily_alpha.model_training import ModelTrainingError


RAW = b'{"results":[{"c":97.32}]}'
CAPTURED_AT = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
DECISION_AT = datetime(2026, 8, 24, 13, 30, tzinfo=UTC)
SOURCE_AS_OF = datetime(2026, 8, 23, 20, 0, tzinfo=UTC)


def _receipt(**overrides: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1",
        "provider": "MASSIVE",
        "target": "DINO",
        "captured_at": CAPTURED_AT.isoformat(),
        "raw_s3_key": "data-feeds/staging/massive/raw/2026/08/24/req-01-DINO.json",
        "raw_sha256": hashlib.sha256(RAW).hexdigest(),
        "raw_bytes": len(RAW),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    receipt.update(overrides)
    return receipt


def _fact(
    *,
    security_id: str = "DINO",
    feature_name: str = "close",
    feature_value: float = 97.32,
    decision_at: datetime = DECISION_AT,
    source_as_of: datetime = SOURCE_AS_OF,
) -> FeedFeatureFact:
    return FeedFeatureFact(
        security_id=security_id,
        decision_at=decision_at,
        feature_name=feature_name,
        feature_value=feature_value,
        source_as_of=source_as_of,
    )


def test_exact_receipt_and_raw_bytes_create_deterministic_point_in_time_observation() -> None:
    first = build_point_in_time_feed_observations(
        raw_body=RAW,
        receipt=_receipt(),
        facts=[_fact()],
    )
    second = build_point_in_time_feed_observations(
        raw_body=RAW,
        receipt=_receipt(),
        facts=[_fact()],
    )

    assert first == second
    assert first.batch_id == second.batch_id
    assert len(first.batch_id) == 64
    assert len(first.evidence.evidence_id) == 64
    observation = first.observations[0]
    assert observation.security_id == "DINO"
    assert observation.feature_name == "close"
    assert observation.feature_value == 97.32
    assert observation.known_at == CAPTURED_AT
    assert observation.decision_at == DECISION_AT
    assert observation.evidence_id == first.evidence.evidence_id
    assert observation.source_revision == first.evidence.source_revision


def test_feature_order_does_not_change_batch_identity() -> None:
    facts = [
        _fact(feature_name="close", feature_value=97.32),
        _fact(feature_name="volume", feature_value=2_500_000.0),
    ]
    forward = build_point_in_time_feed_observations(
        raw_body=RAW,
        receipt=_receipt(),
        facts=facts,
    )
    reverse = build_point_in_time_feed_observations(
        raw_body=RAW,
        receipt=_receipt(),
        facts=reversed(facts),
    )

    assert forward == reverse
    assert forward.batch_id == reverse.batch_id
    assert tuple(item.feature_name for item in forward.observations) == ("close", "volume")


@pytest.mark.parametrize(
    ("overrides", "raw", "match"),
    [
        ({"raw_sha256": "0" * 64}, RAW, "FEED_RAW_SHA256_MISMATCH"),
        ({"raw_bytes": len(RAW) + 1}, RAW, "FEED_RAW_BYTE_COUNT_MISMATCH"),
        (
            {"raw_s3_key": "data-feeds/staging/tiingo/raw/2026/08/24/x.json"},
            RAW,
            "FEED_RECEIPT_RAW_KEY_PROVIDER_MISMATCH",
        ),
        ({"schema": "OTHER"}, RAW, "FEED_RECEIPT_SCHEMA_INVALID"),
        ({"provider": "UNKNOWN"}, RAW, "FEED_RECEIPT_PROVIDER_INVALID"),
        ({"trading_authorized": True}, RAW, "FEED_RECEIPT_TRADING_AUTHORITY_INVALID"),
        ({"live_trading_enabled": True}, RAW, "FEED_RECEIPT_LIVE_AUTHORITY_INVALID"),
    ],
)
def test_receipt_integrity_and_authority_drift_fail_closed(
    overrides: dict[str, object],
    raw: bytes,
    match: str,
) -> None:
    with pytest.raises(ModelTrainingError, match=match):
        validate_immutable_feed_evidence(raw_body=raw, receipt=_receipt(**overrides))


def test_raw_body_change_cannot_reuse_receipt_identity() -> None:
    with pytest.raises(ModelTrainingError, match="FEED_RAW_SHA256_MISMATCH"):
        validate_immutable_feed_evidence(
            raw_body=RAW + b"\n",
            receipt=_receipt(),
        )


def test_capture_time_is_the_only_model_known_at_time() -> None:
    source_time = CAPTURED_AT - timedelta(hours=4)
    batch = build_point_in_time_feed_observations(
        raw_body=RAW,
        receipt=_receipt(),
        facts=[_fact(source_as_of=source_time)],
    )

    assert batch.observations[0].known_at == CAPTURED_AT
    assert batch.observations[0].known_at != source_time


def test_source_fact_cannot_claim_information_after_capture() -> None:
    with pytest.raises(ModelTrainingError, match="FEED_FEATURE_SOURCE_AFTER_CAPTURE"):
        build_point_in_time_feed_observations(
            raw_body=RAW,
            receipt=_receipt(),
            facts=[_fact(source_as_of=CAPTURED_AT + timedelta(seconds=1))],
        )


def test_receipt_captured_after_decision_cannot_be_backdated_into_features() -> None:
    with pytest.raises(ModelTrainingError, match="FEED_FEATURE_CAPTURE_AFTER_DECISION"):
        build_point_in_time_feed_observations(
            raw_body=RAW,
            receipt=_receipt(),
            facts=[_fact(decision_at=CAPTURED_AT - timedelta(seconds=1))],
        )


def test_duplicate_feature_fact_for_same_security_decision_and_name_fails_closed() -> None:
    with pytest.raises(ModelTrainingError, match="DUPLICATE_FEED_FEATURE_FACT"):
        build_point_in_time_feed_observations(
            raw_body=RAW,
            receipt=_receipt(),
            facts=[_fact(), _fact(feature_value=98.0)],
        )


def test_macro_feed_can_bind_a_fred_fact_to_an_equity_without_fabricating_known_at() -> None:
    fred_raw = b'{"observations":[{"date":"2026-08-21","value":"4.33"}]}'
    receipt = _receipt(
        provider="FRED",
        target="DFF",
        raw_s3_key="data-feeds/staging/fred/raw/2026/08/24/req-01-DFF.json",
        raw_sha256=hashlib.sha256(fred_raw).hexdigest(),
        raw_bytes=len(fred_raw),
    )
    batch = build_point_in_time_feed_observations(
        raw_body=fred_raw,
        receipt=receipt,
        facts=[
            _fact(
                security_id="DINO",
                feature_name="fed_funds_rate",
                feature_value=4.33,
            )
        ],
    )

    assert batch.evidence.provider == "FRED"
    assert batch.evidence.target == "DFF"
    assert batch.observations[0].known_at == CAPTURED_AT


def test_adapter_stays_research_only_and_cannot_create_labels_or_authority() -> None:
    batch = build_point_in_time_feed_observations(
        raw_body=RAW,
        receipt=_receipt(),
        facts=[_fact()],
    )

    assert batch.labels_created is False
    assert batch.research_only is True
    assert batch.retuning_authorized is False
    assert batch.promotion_authorized is False
    assert batch.paper_mutation_authorized is False
    assert batch.trading_authorized is False
    assert batch.live_trading_enabled is False

    for flag in (
        "labels_created",
        "retuning_authorized",
        "promotion_authorized",
        "paper_mutation_authorized",
        "trading_authorized",
        "live_trading_enabled",
    ):
        with pytest.raises(ModelTrainingError):
            replace(batch, **{flag: True})
