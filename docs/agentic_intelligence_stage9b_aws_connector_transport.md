# Agentic Intelligence Stage 9B — AWS Connector & Transport Framework

## Purpose

Stage 9B defines the repo-side AWS data-plane transport contracts that sit between external
providers and Daily Alpha's deterministic source adapters. The layer is intentionally
provider-neutral and contains no AWS deployment code, live credentials, broker routing,
or trading authority.

## Target AWS flow

```text
EventBridge schedule/event
        |
        v
Step Functions orchestration
        |
        v
Connector Lambda / streaming consumer
        |
        +---- Secrets Manager logical reference only
        |
        +---- provider rate-limit / quota policy
        |
        +---- retry / capped exponential backoff
        |
        v
HTTPS / stream response
        |
        v
TransportResponseReceipt
        |
        +---- immutable raw bytes -> S3 archive key + SHA-256
        |
        +---- delivery envelope -> SQS -> processor -> DLQ on poison/replay exhaustion
        |
        v
checksum + freshness + idempotency validation
        |
        v
Stage 9A deterministic adapter
        |
        v
canonical ProviderObservation / reference record
        |
        v
Evidence / Feature / Research Council / CIO layers
```

## Contracts

- `TransportMode`: scheduled pull, event/webhook, or streaming.
- `RetryPolicy`: capped exponential retry with explicit attempt limits and Retry-After support.
- `RetryDisposition`: success, retryable, rate-limited, or permanent failure.
- `RateLimitPolicy`: provider-specific request rate, burst, and optional daily quota metadata.
- `SecretReference`: logical Secrets Manager name/version stage only; no secret material.
- `EventBridgeTriggerMetadata`: deterministic trigger lineage.
- `StepFunctionsExecutionMetadata`: deterministic orchestration lineage.
- `TransportRequestEnvelope`: provider request plus trigger, attempt, and stable idempotency key.
- `TransportResponseReceipt`: HTTP metadata, body checksum/length, latency, and retry disposition.
- `RawArchivePointer`: deterministic S3 raw-response key, checksum, size, archive time, and KMS alias.
- `QueueDeliveryEnvelope`: SQS delivery/replay state with poison-message/DLQ decision helper.
- `InMemoryIdempotencyLedger`: reference model for future DynamoDB conditional-put semantics.
- `SourceTransportTelemetry`: source health, latency, freshness, last-success lineage.
- `PublicPrimaryTransportRouter`: checksum-verified handoff into OpenFIGI, SEC EDGAR, and FRED/ALFRED adapters.

## Idempotency

Retries intentionally create new request-envelope IDs but preserve one stable
`idempotency_key` for the same provider/request/trigger. A future DynamoDB table can use the
same key for conditional writes so at-least-once SQS/EventBridge delivery does not create
duplicate canonical evidence.

## Raw-response retention

The raw payload is not stored inside the receipt. The receipt stores SHA-256 and content
length; the immutable payload is intended for S3. The deterministic object shape is:

```text
raw/<provider>/<YYYY>/<MM>/<DD>/<request_id>/<receipt_id>.json
```

The adapter handoff re-hashes the bytes before parsing. If checksum or length differs from
the receipt, processing fails closed.

## Retry and failure classification

- `2xx` -> SUCCESS
- `429` -> RATE_LIMITED
- `408`, `425`, and `5xx` -> RETRYABLE
- other `4xx` -> PERMANENT_FAILURE
- timeout / temporary DNS / connection-reset / temporary TLS errors -> RETRYABLE
- permanent credential/certificate/request errors -> PERMANENT_FAILURE

Retry exhaustion and malformed/poison payloads are intended to move to DLQ rather than be
silently discarded.

## Source health

Transport health is separate from investment judgment. Provider latency/freshness and
success/error state can be converted into immutable source-health evidence and surfaced to
the Data Supervisor. An unhealthy required source can therefore fail closed without any AI
agent deciding whether to ignore the outage.

## Security boundary

Stage 9B does not hold secret values. A request that requires a secret must provide a
`SecretReference` matching the adapter's logical secret name. The future Lambda retrieves
the value from Secrets Manager at runtime; logs/receipts/archive metadata must never contain
that value.

## Authority boundary

Stage 9B is data transport only. All transport request/receipt contracts remain
research-only and explicitly reject trading/live enablement. The layer cannot:

- place or route an order,
- authorize capital,
- override CIO/Fusion,
- override the deterministic Risk Governor,
- bypass the Governance Lock,
- mutate SH24/SH25,
- mutate TradingView,
- deploy AWS resources.

## Future implementation

After this contract is CI-green, the same interfaces can back actual AWS infrastructure:

- EventBridge Scheduler / EventBridge events,
- Step Functions,
- Lambda and/or Kinesis consumers,
- Secrets Manager,
- S3 immutable raw archive,
- SQS + DLQ,
- DynamoDB idempotency/current transport state,
- CloudWatch metrics/alarms.

Stage 9C can then add Massive, Databento, FMP, and Benzinga adapters behind the same
transport framework in fixture/shadow mode before any live provider is enabled.
