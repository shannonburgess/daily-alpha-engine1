# Agentic Command-Center Timeline Service V1

## Purpose

Stage 9M adds a repo-only, read-only service facade above Stage 9L history/query and Stage 9K point-in-time audit diffs. It is intended for a future Daily Alpha API/UI that needs to render a governed timeline without recomputing provider health, model state, Research Council opinions, CIO decisions, portfolio proposals, risk vetoes, PAPER outcomes, or trading signals.

The service consumes only immutable `InstitutionalCommandCenterSnapshot` history already retained by Stage 9L. It does not create a database, HTTP endpoint, cache, websocket, broker route, or second decision engine.

## Service contract

`InstitutionalCommandCenterTimelineService` exposes two read-only operations:

- `get(snapshot_id)` returns one retained timeline entry by exact snapshot identity;
- `query(CommandCenterHistoryQuery)` returns a bounded deterministic timeline page using Stage 9L's existing scope, filter, ordering, page-size, and opaque cursor semantics.

There is deliberately no append/update/delete surface in the timeline facade. Snapshot ingestion remains the responsibility of the Stage 9L repository contract.

## Timeline entries

Every `CommandCenterTimelineEntry` contains:

- the exact immutable Stage 9L `CommandCenterHistoryRecord`;
- an optional Stage 9K `InstitutionalCommandCenterAuditDiff` from the immediate previously retained snapshot in the same exact scope;
- exact predecessor snapshot identity when that retained predecessor exists;
- deterministic entry identity and API-ready serialization;
- hard read-only authority flags.

The facade never invents a predecessor. If bounded retention has already evicted earlier history, the oldest retained record has no audit diff. The UI must treat that as "no retained predecessor available," not as proof that no earlier snapshot ever existed.

## Predecessor semantics

Audit diffs always compare a record with the immediate chronologically previous **retained** snapshot in the same exact `(platform_id, portfolio_id, security_id)` scope. This rule is independent of display order and independent of optional status filtering.

For example, a PASS-only UI query may return two PASS snapshots even if a BLOCKED snapshot occurred between them. The later PASS entry is still diffed against the intervening retained BLOCKED snapshot so the UI can truthfully show the recovery rather than comparing two filtered neighbors and hiding the blocked state.

The facade asks Stage 9L for at most two records ending at the current record's exact `as_of` boundary. Because Stage 9L rejects different snapshots at the same scope/as-of boundary, the current record must be the first result and the second result, when present, is the exact retained predecessor. Any repository ordering or scope inconsistency fails closed.

## Pagination

Stage 9M does not create a second pagination system. The timeline page preserves Stage 9L's:

- query identity;
- matched count;
- page size;
- oldest/newest ordering;
- opaque query-bound continuation cursor;
- cursor tamper, cross-query reuse, and retention-anchor failure semantics.

This keeps UI/API traversal deterministic and prevents timeline presentation code from silently redefining history.

## Exact scope

Platform, portfolio, and security timelines remain isolated. A page requested for one exact scope cannot contain records from another scope. Timeline composition fails closed if a repository implementation returns a mismatched record or an audit diff cannot preserve exact scope identity.

## Authority boundary

Timeline entries and pages hard-code:

- `research_only=true`;
- `paper_ledger_mutation_authorized=false`;
- `portfolio_construction_authorized=false`;
- `execution_authorized=false`;
- `trading_authorized=false`;
- `live_trading_enabled=false`.

Stage 9M does not change SH24/SH25, TradingView, the stock-primary PAPER policy, #218 liquidity, earnings/event controls, concentration, portfolio risk, ORATS semantics, execution, capital authorization, or live trading.

## Deployment boundary

This stage is code-contract proof only. No network/API deployment, persistent database, AWS resource, credential, paid vendor, broker connection, TradingView mutation, PAPER-ledger mutation, options automation, execution authorization, or live-trading enablement is introduced.

## Dependency chain

Stage 9M is stacked directly on Stage 9L PR #311, which carries Stage 9K -> Stage 9J -> Stage 9I concrete ancestry. It remains draft/unmerged unless explicitly authorized.