# Daily Alpha Command Center Audit Diff V1

## Purpose

Stage 9K adds a deterministic read-only change ledger above the Stage 9J institutional command center. It allows a future UI/API to answer “what changed?” between two exact governed snapshots without recomputing investment facts or gaining authority over research, portfolio construction, PAPER execution, capital, or live trading.

## Point-in-time contract

`InstitutionalCommandCenterAuditBuilder` compares two immutable `InstitutionalCommandCenterSnapshot` objects only when:

- the current `as_of` boundary is strictly later than the previous boundary
- platform identity matches
- requested portfolio scope matches
- requested security scope matches
- command-center schema version matches

Time reversal, cross-platform comparison, or portfolio/security scope drift fails closed.

## Logical-slot comparison

Components are matched by the same canonical logical slot used by the Stage 9J snapshot contract:

- component kind
- entity kind
- entity ID
- optional security ID
- optional portfolio ID

The diff never joins components by display order and is deterministic regardless of the order in which upstream components were supplied.

## Change classifications

Every logical slot is classified as exactly one of:

- `ADDED` — the current snapshot contains a newly surfaced slot
- `REMOVED` — the previous slot is no longer surfaced
- `STATUS_CHANGED` — PASS/WARNING/BLOCKED severity changed
- `CONTENT_CHANGED` — severity stayed the same but governed display facts changed
- `REFRESHED` — governed display facts stayed the same while the point-in-time/source projection refreshed

Display facts are limited to already-governed status, headline, metrics, blockers and warnings. Source-record IDs, component IDs and lineage IDs are preserved for audit drill-down but do not by themselves become a new investment conclusion.

## Transition direction

For matched slots, status movement is described mechanically as:

- `WORSENED` when PASS -> WARNING/BLOCKED or WARNING -> BLOCKED
- `IMPROVED` when BLOCKED -> WARNING/PASS or WARNING -> PASS
- `UNCHANGED` when severity is unchanged

Added/removed slots are `NOT_APPLICABLE` for status direction. These labels are observability facts only. They do not recommend a trade, change model promotion, or alter Risk Governor authority.

## API-ready audit surface

The serialized audit diff contains:

- deterministic diff ID
- previous/current snapshot IDs
- previous/current exact `as_of` boundaries
- platform/portfolio/security scope
- previous/current command-center status
- added/removed/status-changed/content-changed/refreshed counts
- worsened/improved counts
- deterministic per-slot changes
- exact previous/current component IDs
- exact previous/current source-record IDs
- exact previous/current lineage IDs
- explicit false authority flags

This supports command-center timeline views, audit history, incident review, model-health change review, CIO/Risk disagreement review, and future institutional reporting without creating another decision engine.

## Safety boundary

Stage 9K is repository-only and read-only. It does not:

- deploy AWS or create persistent infrastructure
- activate vendors, credentials or paid feeds
- connect a broker
- mutate TradingView or SH24/SH25
- mutate PAPER ledgers
- create an options execution path
- authorize portfolio construction, execution or capital
- authorize trading
- enable live trading

`research_only=true`, `paper_ledger_mutation_authorized=false`, `portfolio_construction_authorized=false`, `execution_authorized=false`, `trading_authorized=false`, and `live_trading_enabled=false` are explicit serialized invariants.
