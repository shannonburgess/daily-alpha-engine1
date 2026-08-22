# Agentic Intelligence Stage 9N — Transport-Neutral Command-Center API Contract V1

## Purpose

Stage 9N defines the read-only application contract that a later HTTP, gRPC, desktop, web, or mobile transport can expose without letting the transport layer recompute or mutate Daily Alpha investment truth.

The contract sits above:

- Stage 9J current command-center snapshot and platform / portfolio / security drill-down views;
- Stage 9K point-in-time audit diffs;
- Stage 9L bounded immutable history/query semantics; and
- Stage 9M retained-predecessor timeline composition.

No server, router, authentication provider, database, AWS resource, broker connection, TradingView change, PAPER mutation, or live-trading authority is introduced.

## Operations

`CommandCenterAPIOperation` defines five read-only operations:

1. `CURRENT_SNAPSHOT` — exact current governed snapshot;
2. `PLATFORM_VIEW` — Stage 9J platform drill-down and status tiles;
3. `PORTFOLIO_VIEW` — one exact portfolio drill-down;
4. `SECURITY_VIEW` — one exact security drill-down; and
5. `TIMELINE` — Stage 9L query mapped through the Stage 9M timeline service.

The request identity is transport-independent. A later HTTP adapter may map these operations to URLs, and a later gRPC adapter may map them to RPC methods, without changing request identity or downstream truth.

## Scope and query rules

- Platform IDs, portfolio IDs, and security IDs are normalized before request identity is calculated.
- Current/platform reads are platform-scoped.
- Portfolio and security drill-down operations require exactly the corresponding scope ID.
- History range, readiness-status, ordering, page-size, and continuation cursor fields are accepted only for `TIMELINE`.
- Timeline requests are converted directly to the existing `CommandCenterHistoryQuery`; Stage 9L remains authoritative for cursor integrity, range validation, retention, and pagination.
- A current snapshot whose platform does not match the request fails closed.

## Response semantics

`CommandCenterAPIResponse` is a deterministic envelope with:

- exact request ID and operation;
- `OK` or `NOT_FOUND` result status;
- one resource ID when found;
- exact upstream snapshot/query IDs;
- the already-governed Stage 9J or Stage 9M payload; and
- hard false authority flags.

`NOT_FOUND` is intentionally not coupled to an HTTP status code. The later transport adapter decides how to represent the result while preserving the same application-layer response semantics.

## No recomputation

Stage 9N does not calculate market data, model scores, CIO opinions, portfolio weights, risk verdicts, command-center status, audit diffs, or timeline predecessor relationships. It delegates to the existing governed builders/services and serializes their outputs.

## Authority boundary

Every request and response is permanently read-only:

- `research_only=true`
- `paper_ledger_mutation_authorized=false`
- `portfolio_construction_authorized=false`
- `execution_authorized=false`
- `trading_authorized=false`
- `live_trading_enabled=false`

No transport adapter may treat an `OK` command-center response as execution or capital authorization.

## Future transport layer

A later stage may bind this contract to an authenticated network transport and authorization policy. That future layer must remain outside canonical investment logic and must preserve exact request/response IDs, scope rules, point-in-time lineage, and read-only authority.
