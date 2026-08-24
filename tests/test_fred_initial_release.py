# ruff: noqa: I001

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from daily_alpha.fred_initial_release import (
    FRED_INITIAL_RELEASE_CONTRACT,
    FRED_INITIAL_RELEASE_KNOWN_AT_POLICY,
    FRED_INITIAL_RELEASE_OUTPUT_TYPE,
    build_fred_initial_release_feature,
    parse_fred_initial_release_history,
)
from daily_alpha.model_training import ModelTrainingError


CAPTURED_AT = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)


def _raw(*, output_type: int = 4) -> bytes:
    return json.dumps(
        {
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "observation_start": "2026-07-01",
            "observation_end": "2026-07-31",
            "output_type": output_type,
            "observations": [
                {
                    "realtime_start": "2026-07-02",
                    "realtime_end": "9999-12-31",
                    "date": "2026-07-01",
                    "value": "4.33",
                },
                {
                    "realtime_start": "2026-07-03",
                    "realtime_end": "9999-12-31",
                    "date": "2026-07-02",
                    "value": "4.34",
                },
                {
                    "realtime_start": "2026-07-06",
                    "realtime_end": "9999-12-31",
                    "date": "2026-07-03",
                    "value": "4.35",
                },
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _receipt(raw: bytes, **overrides: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1",
        "provider": "FRED",
        "target": "DFF",
        "captured_at": CAPTURED_AT.isoformat(),
        "capture_mode": "HISTORICAL_BACKFILL",
        "requested_start_date": "2026-07-01",
        "requested_end_date": "2026-07-31",
        "known_at_basis": "CAPTURED_AT_ONLY",
        "historical_known_at_backdating_authorized": False,
        "raw_s3_key": "data-feeds/staging/fred/raw/2026/08/24/req-01-DFF.json",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    receipt.update(overrides)
    return receipt


def test_initial_release_history_creates_deterministic_provider_specific_lineage() -> None:
    raw = _raw()
    first = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))
    second = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    assert first == second
    assert first.batch_id == second.batch_id
    assert len(first.batch_id) == 64
    assert first.output_type == FRED_INITIAL_RELEASE_OUTPUT_TYPE
    assert first.availability_contract == FRED_INITIAL_RELEASE_CONTRACT
    assert first.known_at_policy == FRED_INITIAL_RELEASE_KNOWN_AT_POLICY
    assert first.evidence.provider == "FRED"
    assert first.evidence.capture_mode == "HISTORICAL_BACKFILL"
    assert first.evidence.captured_at == CAPTURED_AT
    assert first.evidence.known_at_basis == "CAPTURED_AT_ONLY"
    assert first.evidence.historical_known_at_backdating_authorized is False
    assert tuple(item.value for item in first.observations) == (4.33, 4.34, 4.35)
    assert first.observations[0].known_at == datetime(2026, 7, 3, 0, 0, tzinfo=UTC)
    assert first.observations[0].known_at < first.evidence.captured_at
    assert all(item.source_revision.startswith("fred-initial-release-v1:") for item in first.observations)


def test_feature_uses_latest_initial_release_provably_known_by_decision() -> None:
    raw = _raw()
    batch = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    observation = build_fred_initial_release_feature(
        batch=batch,
        security_id="dino",
        decision_at=datetime(2026, 7, 5, 20, 0, tzinfo=UTC),
        feature_name="fed_funds_rate_initial_release",
    )

    assert observation.security_id == "DINO"
    assert observation.feature_value == 4.34
    assert observation.known_at == datetime(2026, 7, 4, 0, 0, tzinfo=UTC)
    assert observation.decision_at < CAPTURED_AT
    assert observation.source_revision.startswith("fred-initial-release-v1:")


def test_date_only_release_evidence_is_not_used_on_same_release_date() -> None:
    raw = _raw()
    batch = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    observation = build_fred_initial_release_feature(
        batch=batch,
        security_id="DINO",
        decision_at=datetime(2026, 7, 3, 20, 0, tzinfo=UTC),
        feature_name="fed_funds_rate_initial_release",
    )

    # The July 2 observation has realtime_start=July 3, but date-only evidence cannot
    # prove an intraday release timestamp. It becomes eligible July 4 00:00 UTC.
    assert observation.feature_value == 4.33
    assert observation.known_at == datetime(2026, 7, 3, 0, 0, tzinfo=UTC)


def test_no_value_known_at_decision_fails_closed() -> None:
    raw = _raw()
    batch = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    with pytest.raises(ModelTrainingError, match="FRED_INITIAL_RELEASE_NO_VALUE_KNOWN_AT_DECISION"):
        build_fred_initial_release_feature(
            batch=batch,
            security_id="DINO",
            decision_at=datetime(2026, 7, 2, 20, 0, tzinfo=UTC),
            feature_name="fed_funds_rate_initial_release",
        )


@pytest.mark.parametrize(
    ("raw", "receipt_overrides", "match"),
    [
        (_raw(output_type=1), {}, "FRED_INITIAL_RELEASE_OUTPUT_TYPE_REQUIRED"),
        (_raw(), {"capture_mode": "CURRENT_WINDOW", "requested_start_date": "2026-08-17", "requested_end_date": "2026-08-24"}, "FRED_INITIAL_RELEASE_HISTORICAL_CAPTURE_REQUIRED"),
        (_raw(), {"provider": "MASSIVE", "target": "DINO", "raw_s3_key": "data-feeds/staging/massive/raw/2026/08/24/req-01-DINO.json"}, "FRED_INITIAL_RELEASE_PROVIDER_REQUIRED"),
    ],
)
def test_provider_contract_cannot_be_applied_to_wrong_transport_semantics(
    raw: bytes,
    receipt_overrides: dict[str, object],
    match: str,
) -> None:
    receipt = _receipt(raw, **receipt_overrides)
    with pytest.raises(ModelTrainingError, match=match):
        parse_fred_initial_release_history(raw_body=raw, receipt=receipt)


def test_provider_missing_value_sentinel_is_excluded_without_invalidating_batch() -> None:
    payload = json.loads(_raw())
    payload["observations"][1]["value"] = "."
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    batch = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    assert tuple(item.value for item in batch.observations) == (4.33, 4.35)
    assert tuple(item.observation_date.isoformat() for item in batch.observations) == (
        "2026-07-01",
        "2026-07-03",
    )


def test_missing_value_or_release_date_fails_closed() -> None:
    payload = json.loads(_raw())
    payload["observations"][0]["value"] = None
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ModelTrainingError, match="FRED_INITIAL_RELEASE_VALUE_MISSING"):
        parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    payload = json.loads(_raw())
    del payload["observations"][0]["realtime_start"]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ModelTrainingError, match="FRED_INITIAL_RELEASE_REALTIME_START_REQUIRED"):
        parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))


def test_all_provider_missing_value_sentinels_fail_closed() -> None:
    payload = json.loads(_raw())
    for observation in payload["observations"]:
        observation["value"] = "."
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(ModelTrainingError, match="FRED_INITIAL_RELEASE_OBSERVATIONS_REQUIRED"):
        parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))


def test_conflicting_same_observation_date_fails_closed() -> None:
    payload = json.loads(_raw())
    conflict = dict(payload["observations"][0])
    conflict["value"] = "9.99"
    payload["observations"].append(conflict)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(
        ModelTrainingError,
        match="FRED_INITIAL_RELEASE_CONFLICTING_OBSERVATION_DATE",
    ):
        parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))


def test_future_claimed_release_after_raw_capture_fails_closed() -> None:
    payload = json.loads(_raw())
    payload["observations"][0]["realtime_start"] = "2026-08-25"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(ModelTrainingError, match="FRED_INITIAL_RELEASE_AFTER_CAPTURE"):
        parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))


def test_raw_hash_tampering_still_fails_at_transport_evidence_boundary() -> None:
    raw = _raw()
    receipt = _receipt(raw)
    receipt["raw_sha256"] = "0" * 64

    with pytest.raises(ModelTrainingError, match="FEED_RAW_SHA256_MISMATCH"):
        parse_fred_initial_release_history(raw_body=raw, receipt=receipt)


def test_batch_cannot_authorize_promotion_paper_trading_or_live() -> None:
    raw = _raw()
    batch = parse_fred_initial_release_history(raw_body=raw, receipt=_receipt(raw))

    assert batch.research_only is True
    assert batch.promotion_authorized is False
    assert batch.paper_mutation_authorized is False
    assert batch.trading_authorized is False
    assert batch.live_trading_enabled is False

    for flag in (
        "promotion_authorized",
        "paper_mutation_authorized",
        "trading_authorized",
        "live_trading_enabled",
    ):
        with pytest.raises(ModelTrainingError, match="FRED_INITIAL_RELEASE_CANNOT_AUTHORIZE_ACTION"):
            replace(batch, **{flag: True})
