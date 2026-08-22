from datetime import UTC, date, datetime, timedelta

import pytest

from daily_alpha.agentic.aws_transport import (
    AwsTransportError,
    EventBridgeTriggerMetadata,
    InMemoryIdempotencyLedger,
    PublicAdapterRoute,
    PublicPrimaryTransportRouter,
    QueueDeliveryEnvelope,
    RateLimitPolicy,
    RawArchivePointer,
    RetryDisposition,
    RetryPolicy,
    SecretReference,
    SourceTransportTelemetry,
    StepFunctionsExecutionMetadata,
    TransportMode,
    TransportRequestEnvelope,
    TransportResponseReceipt,
    classify_http_status,
    classify_transport_error,
)
from daily_alpha.agentic.durable_evidence import SourceHealthStatus
from daily_alpha.agentic.public_primary_adapters import FredAlfredAdapter, OpenFigiAdapter

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _trigger() -> EventBridgeTriggerMetadata:
    return EventBridgeTriggerMetadata(
        rule_name="daily-alpha-public-source-pull",
        event_id="evt-1",
        triggered_at=NOW,
        detail_type="PUBLIC_SOURCE_REFRESH",
    )


def _openfigi_envelope(*, attempt: int = 1) -> TransportRequestEnvelope:
    request = OpenFigiAdapter.mapping_request(id_type="TICKER", id_value="AAPL")
    return TransportRequestEnvelope(
        provider_id="OPENFIGI",
        mode=TransportMode.SCHEDULED_PULL,
        request_spec=request,
        created_at=NOW + timedelta(seconds=attempt - 1),
        trigger_id=_trigger().trigger_id,
        attempt=attempt,
    )


def _success_receipt(body: bytes) -> TransportResponseReceipt:
    return TransportResponseReceipt.from_http_response(
        envelope=_openfigi_envelope(),
        body=body,
        received_at=NOW + timedelta(seconds=1),
        status_code=200,
        latency_ms=125.0,
        headers={"content-type": "application/json"},
    )


def test_retry_policy_is_capped_and_attempt_bounded():
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=1, max_delay_seconds=5, multiplier=2)
    assert policy.delay_seconds(1) == 1
    assert policy.delay_seconds(2) == 2
    assert policy.delay_seconds(4) == 5
    assert policy.delay_seconds(2, retry_after_seconds=30) == 5
    assert policy.can_retry(4) is True
    assert policy.can_retry(5) is False


def test_http_and_transport_error_classification():
    assert classify_http_status(200) is RetryDisposition.SUCCESS
    assert classify_http_status(429) is RetryDisposition.RATE_LIMITED
    assert classify_http_status(503) is RetryDisposition.RETRYABLE
    assert classify_http_status(404) is RetryDisposition.PERMANENT_FAILURE
    assert classify_transport_error("timeout") is RetryDisposition.RETRYABLE
    assert classify_transport_error("rate_limit") is RetryDisposition.RATE_LIMITED
    assert classify_transport_error("certificate_invalid") is RetryDisposition.PERMANENT_FAILURE


def test_fred_request_requires_logical_secret_reference_but_never_secret_value():
    request = FredAlfredAdapter.observations_request(
        series_id="CPIAUCSL",
        as_of_date=date(2026, 8, 21),
    )
    with pytest.raises(AwsTransportError, match="TRANSPORT_REQUEST_SECRET_REFERENCE_REQUIRED"):
        TransportRequestEnvelope(
            provider_id="FRED_ALFRED",
            mode=TransportMode.SCHEDULED_PULL,
            request_spec=request,
            created_at=NOW,
            trigger_id=_trigger().trigger_id,
        )
    envelope = TransportRequestEnvelope(
        provider_id="FRED_ALFRED",
        mode=TransportMode.SCHEDULED_PULL,
        request_spec=request,
        created_at=NOW,
        trigger_id=_trigger().trigger_id,
        secret_reference=SecretReference("FRED_API_KEY"),
    )
    assert envelope.secret_reference.secret_name == "FRED_API_KEY"
    assert "api_key" not in dict(request.query)


def test_idempotency_key_is_stable_across_retries_while_envelope_id_changes():
    first = _openfigi_envelope(attempt=1)
    second = _openfigi_envelope(attempt=2)
    assert first.idempotency_key == second.idempotency_key
    assert first.envelope_id != second.envelope_id


def test_duplicate_delivery_is_rejected_by_reference_idempotency_ledger():
    ledger = InMemoryIdempotencyLedger()
    key = _openfigi_envelope().idempotency_key
    assert ledger.claim(key) is True
    assert ledger.claim(key) is False


def test_response_receipt_checksum_archive_key_and_point_in_time():
    body = b'{"ok":true}'
    receipt = _success_receipt(body)
    receipt.validate_body(body)
    receipt.validate_point_in_time(NOW + timedelta(seconds=30), max_age_seconds=60)
    archive = RawArchivePointer.for_receipt(
        bucket_name="daily-alpha-raw-fixture",
        receipt=receipt,
        archived_at=NOW + timedelta(seconds=2),
        kms_key_alias="alias/daily-alpha-data",
    )
    assert archive.object_key.startswith("raw/openfigi/2026/08/21/")
    assert archive.body_sha256 == receipt.body_sha256
    assert archive.content_length == len(body)
    with pytest.raises(AwsTransportError, match="TRANSPORT_BODY_CHECKSUM_MISMATCH"):
        receipt.validate_body(b"tampered")


def test_stale_and_future_receipts_fail_closed():
    body = b'{}'
    receipt = _success_receipt(body)
    with pytest.raises(AwsTransportError, match="TRANSPORT_RECEIPT_STALE"):
        receipt.validate_point_in_time(NOW + timedelta(minutes=10), max_age_seconds=60)
    with pytest.raises(AwsTransportError, match="FUTURE_TRANSPORT_RECEIPT_NOT_ALLOWED"):
        receipt.validate_point_in_time(NOW, max_age_seconds=60)


def test_queue_delivery_can_be_classified_for_dlq_after_replay_exhaustion():
    delivery = QueueDeliveryEnvelope(
        receipt_id="r" * 64,
        idempotency_key="i" * 64,
        delivery_id="delivery-1",
        first_seen_at=NOW,
        delivered_at=NOW + timedelta(seconds=5),
        replay_count=3,
        failure_code="MALFORMED_PAYLOAD",
    )
    assert delivery.should_send_to_dlq(max_replays=2) is True
    assert delivery.should_send_to_dlq(max_replays=3) is False


def test_rate_limit_and_orchestration_contracts_are_deterministic():
    policy = RateLimitPolicy("SEC_EDGAR", requests_per_second=5.0, burst_capacity=10)
    assert policy.policy_id == RateLimitPolicy(
        "SEC_EDGAR",
        requests_per_second=5.0,
        burst_capacity=10,
    ).policy_id
    trigger = _trigger()
    execution = StepFunctionsExecutionMetadata(
        state_machine_name="daily-alpha-public-source-ingestion",
        execution_name="exec-1",
        started_at=NOW,
    )
    assert trigger.trigger_id
    assert execution.execution_id


def test_transport_telemetry_preserves_health_latency_and_freshness():
    telemetry = SourceTransportTelemetry(
        provider_id="SEC_EDGAR",
        observed_at=NOW,
        status=SourceHealthStatus.HEALTHY,
        latency_ms=85.0,
        freshness_seconds=2.0,
        last_success_at=NOW - timedelta(seconds=2),
    )
    assert telemetry.provider_id == "SEC_EDGAR"
    assert telemetry.telemetry_id


def test_openfigi_receipt_handoff_verifies_bytes_and_parses_deterministically():
    body = b'[{"data":[{"figi":"BBG000B9XRY4","ticker":"AAPL"}]}]'
    receipt = _success_receipt(body)
    result = PublicPrimaryTransportRouter.handoff(
        route=PublicAdapterRoute.OPENFIGI_MAPPING,
        receipt=receipt,
        body=body,
    )
    assert len(result.records) == 1
    assert result.records[0].figi == "BBG000B9XRY4"
    assert result.handoff_id


def test_non_success_receipt_cannot_reach_adapter():
    body = b'{"error":"busy"}'
    receipt = TransportResponseReceipt.from_http_response(
        envelope=_openfigi_envelope(),
        body=body,
        received_at=NOW + timedelta(seconds=1),
        status_code=503,
        latency_ms=100,
    )
    with pytest.raises(AwsTransportError, match="NON_SUCCESS_RECEIPT_CANNOT_HANDOFF"):
        PublicPrimaryTransportRouter.handoff(
            route=PublicAdapterRoute.OPENFIGI_MAPPING,
            receipt=receipt,
            body=body,
        )


def test_malformed_json_is_explicit_transport_failure():
    body = b"not-json"
    receipt = _success_receipt(body)
    with pytest.raises(AwsTransportError, match="TRANSPORT_JSON_PAYLOAD_INVALID"):
        PublicPrimaryTransportRouter.handoff(
            route=PublicAdapterRoute.OPENFIGI_MAPPING,
            receipt=receipt,
            body=body,
        )


def test_transport_contracts_cannot_authorize_trading_or_live_execution():
    request = OpenFigiAdapter.mapping_request(id_type="TICKER", id_value="AAPL")
    with pytest.raises(AwsTransportError, match="TRANSPORT_REQUEST_MUST_REMAIN_RESEARCH_ONLY"):
        TransportRequestEnvelope(
            provider_id="OPENFIGI",
            mode=TransportMode.SCHEDULED_PULL,
            request_spec=request,
            created_at=NOW,
            trigger_id=_trigger().trigger_id,
            trading_authorized=True,
        )
