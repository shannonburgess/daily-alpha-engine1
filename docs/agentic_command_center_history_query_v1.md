# Agentic Command-Center History / Query V1

## Purpose

Stage 9L adds a storage-neutral, read-only history/query contract above the Stage 9K point-in-time audit diff. The purpose is to let a future Daily Alpha UI/API retrieve exact governed command-center snapshots over time without introducing a database, mutable presentation truth, or a second decision engine.

The repository stores only already-governed `InstitutionalCommandCenterSnapshot` objects. It does not recompute data-provider health, model state, Research Council views, CIO decisions, portfolio proposals, risk decisions, PAPER outcomes, or trading signals.

## Contract surface

`InstitutionalCommandCenterHistoryRepository` intentionally exposes only:

- `append(snapshot)` — append one immutable governed snapshot under bounded retention;
- `get(snapshot_id)` — retrieve one retained snapshot record by exact identity;
- `query(query)` — retrieve one bounded deterministic page for an exact scope.

There is deliberately no update/delete mutation interface. The included `BoundedInMemoryCommandCenterHistoryRepository` is a fixture/reference adapter for contract proof only. It is not durable storage and is not a production deployment.

## Exact scope and point-in-time rules

Every stored snapshot belongs to one exact `(platform_id, portfolio_id, security_id)` scope. Platform, portfolio, and security history do not silently mix. Within a scope:

- the exact same snapshot may be re-appended idempotently;
- two different snapshots at the same `as_of` boundary fail closed;
- snapshot/component truth is preserved verbatim rather than recomputed;
- queries can apply inclusive `start_as_of` / `end_as_of` filters and optional readiness status filtering.

Timezone-naive query boundaries and reversed ranges fail closed.

## Retention

Retention is explicit and deterministic through `CommandCenterRetentionPolicy.max_records_per_scope`. When a scope exceeds the configured bound, the oldest retained snapshot is evicted first and the append result reports the exact evicted snapshot IDs.

Retention is a repository-capacity contract, not a license to mutate a retained record. An evicted record is simply no longer retained by the bounded repository adapter.

## Pagination and cursors

History pages have a maximum page size of 100 and support deterministic `OLDEST_FIRST` or `NEWEST_FIRST` ordering. Continuation cursors are opaque to callers and bound to the full query identity, including scope, time filters, status filter, order, and page size.

A cursor contains an integrity checksum and the exact retained anchor snapshot. The repository fails closed when:

- cursor bytes are malformed or altered;
- a cursor is reused with a different query;
- retention has evicted the cursor's anchor before the next page request.

This prevents silent page drift. The checksum is a deterministic integrity check for the repo-only contract; it is not an authentication or authorization token.

## API-ready facts

Each history record serializes exact governed snapshot identity and summary facts:

- snapshot ID and `as_of`;
- platform / portfolio / security scope;
- aggregate readiness status;
- PASS / WARNING / BLOCKED / unresolved issue counts;
- exact component IDs;
- read-only authority flags.

Future clients can retrieve the exact snapshot and apply the Stage 9K deterministic audit diff between adjacent retained snapshots. The history layer does not synthesize investment conclusions.

## Authority boundary

Stage 9L is research/operations visibility only. Its records and pages hard-code:

- `research_only=true`;
- `paper_ledger_mutation_authorized=false`;
- `portfolio_construction_authorized=false`;
- `execution_authorized=false`;
- `trading_authorized=false`;
- `live_trading_enabled=false`.

No AWS/database persistence, broker integration, TradingView/SH24/SH25 mutation, PAPER-ledger mutation, options automation, capital authorization, or live trading is introduced by this stage.

## Dependency chain

Stage 9L is stacked on Stage 9K PR #309, which carries the complete Stage 9J/9I ancestry. It remains a draft/unmerged repo-only layer unless explicitly authorized for merge.
