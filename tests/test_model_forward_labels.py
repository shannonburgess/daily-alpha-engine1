from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.model_forward_labels import (
    ProspectiveRealizedRInputs,
    build_prospective_realized_r_label,
)
from daily_alpha.model_training import ModelTrainingError

ENTRY_RAW = b'{"results":[{"c":100.0}]}'
OUTCOME_RAW = b'{"results":[{"c":110.0}]}'
DECISION_AT = datetime(2026, 1, 2, 21, 0, tzinfo=UTC)
ENTRY_CAPTURED_AT = DECISION_AT - timedelta(minutes=5)
OUTCOME_CAPTURED_AT = DECISION_AT + timedelta(days=6, minutes=5)


def _receipt(
    *,
    raw: bytes,
    captured_at: datetime,
    provider: str = "MASSIVE",
    target: str = "MU",
    capture_mode: str = "CURRENT_WINDOW",
) -> dict[str, object]:
    provider_key = provider.lower()
    stamp = captured_at.strftime("%Y/%m/%d")
    return {
        "schema": "DAILY_ALPHA_STAGING_DATA_FEED_RECEIPT_V1",
        "provider": provider,
        "target": target,
        "captured_at": captured_at.isoformat(),
        "capture_mode": capture_mode,
        "requested_start_date": (captured_at.date() - timedelta(days=7)).isoformat(),
        "requested_end_date": captured_at.date().isoformat(),
        "known_at_basis": "CAPTURED_AT_ONLY",
        "historical_known_at_backdating_authorized": False,
        "raw_s3_key": (
            f"data-feeds/staging/{provider_key}/raw/{stamp}/req-01-{target}.json"
        ),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _inputs(**overrides: object) -> ProspectiveRealizedRInputs:
    values: dict[str, object] = {
        "security_id": "MU",
        "decision_at": DECISION_AT,
        "horizon_days": 5,
        "direction": "LONG",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "initial_risk_per_share": 5.0,
        "entry_source_as_of": ENTRY_CAPTURED_AT - timedelta(minutes=1),
        "exit_source_as_of": OUTCOME_CAPTURED_AT - timedelta(minutes=1),
    }
    values.update(overrides)
    return ProspectiveRealizedRInputs(**values)  # type: ignore[arg-type]


def _build(
    *,
    inputs: ProspectiveRealizedRInputs | None = None,
    entry_receipt: dict[str, object] | None = None,
    outcome_receipt: dict[str, object] | None = None,
):
    return build_prospective_realized_r_label(
        entry_raw_body=ENTRY_RAW,
        entry_receipt=entry_receipt
        or _receipt(raw=ENTRY_RAW, captured_at=ENTRY_CAPTURED_AT),
        outcome_raw_body=OUTCOME_RAW,
        outcome_receipt=outcome_receipt
        or _receipt(raw=OUTCOME_RAW, captured_at=OUTCOME_CAPTURED_AT),
        inputs=inputs or _inputs(),
    )


def test_builds_deterministic_long_realized_r_from_two_immutable_captures() -> None:
    first = _build()
    second = _build()

    assert first == second
    assert first.packet_id == second.packet_id
    assert len(first.packet_id) == 64
    assert first.label.security_id == "MU"
    assert first.label.realized_r == pytest.approx(2.0)
    assert first.label.known_at == OUTCOME_CAPTURED_AT
    assert first.label.evidence_ids == tuple(
        sorted(
            {
                first.entry_evidence.evidence_id,
                first.outcome_evidence.evidence_id,
            }
        )
    )
    assert first.label.source_revision.startswith("prospective-realized-r-v1:")
    assert first.retuning_authorized is False
    assert first.promotion_authorized is False
    assert first.paper_mutation_authorized is False
    assert first.trading_authorized is False
    assert first.live_trading_enabled is False


def test_short_direction_derives_realized_r_without_caller_supplied_label() -> None:
    packet = _build(
        inputs=_inputs(direction="SHORT", entry_price=100.0, exit_price=90.0)
    )

    assert packet.inputs.realized_r == pytest.approx(2.0)
    assert packet.label.realized_r == pytest.approx(2.0)


def test_historical_backfill_is_forbidden_for_prospective_labels() -> None:
    historical = _receipt(
        raw=OUTCOME_RAW,
        captured_at=OUTCOME_CAPTURED_AT,
        capture_mode="HISTORICAL_BACKFILL",
    )
    historical["requested_start_date"] = "2025-12-01"
    historical["requested_end_date"] = "2025-12-31"

    with pytest.raises(
        ModelTrainingError,
        match="FORWARD_LABEL_OUTCOME_MUST_USE_CURRENT_WINDOW_EVIDENCE",
    ):
        _build(outcome_receipt=historical)


def test_outcome_capture_must_exist_after_declared_horizon_matures() -> None:
    too_early = DECISION_AT + timedelta(days=4, hours=23)
    receipt = _receipt(raw=OUTCOME_RAW, captured_at=too_early)

    with pytest.raises(
        ModelTrainingError,
        match="FORWARD_LABEL_OUTCOME_CAPTURE_BEFORE_HORIZON_MATURITY",
    ):
        _build(outcome_receipt=receipt)


def test_entry_capture_must_be_available_by_decision_boundary() -> None:
    after_decision = DECISION_AT + timedelta(seconds=1)
    receipt = _receipt(raw=ENTRY_RAW, captured_at=after_decision)

    with pytest.raises(
        ModelTrainingError,
        match="FORWARD_LABEL_ENTRY_CAPTURE_AFTER_DECISION",
    ):
        _build(entry_receipt=receipt)


def test_evidence_target_must_match_label_security() -> None:
    wrong_target = _receipt(
        raw=OUTCOME_RAW,
        captured_at=OUTCOME_CAPTURED_AT,
        target="NVDA",
    )

    with pytest.raises(
        ModelTrainingError,
        match="FORWARD_LABEL_EVIDENCE_TARGET_MISMATCH",
    ):
        _build(outcome_receipt=wrong_target)


def test_fred_cannot_be_used_as_realized_market_return_evidence() -> None:
    fred_raw = b'{"observations":[]}'
    fred = _receipt(
        raw=fred_raw,
        captured_at=OUTCOME_CAPTURED_AT,
        provider="FRED",
        target="MU",
    )

    with pytest.raises(
        ModelTrainingError,
        match="FORWARD_LABEL_OUTCOME_PROVIDER_NOT_MARKET_DATA",
    ):
        build_prospective_realized_r_label(
            entry_raw_body=ENTRY_RAW,
            entry_receipt=_receipt(raw=ENTRY_RAW, captured_at=ENTRY_CAPTURED_AT),
            outcome_raw_body=fred_raw,
            outcome_receipt=fred,
            inputs=_inputs(),
        )


def test_input_contract_rejects_label_values_that_mature_too_early() -> None:
    with pytest.raises(
        ModelTrainingError,
        match="FORWARD_LABEL_EXIT_SOURCE_BEFORE_HORIZON_MATURITY",
    ):
        _inputs(exit_source_as_of=DECISION_AT + timedelta(days=4))
