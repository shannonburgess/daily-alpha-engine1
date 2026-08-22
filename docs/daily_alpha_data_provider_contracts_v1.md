# Daily Alpha Institutional Data Provider Contracts V1

## Purpose

Daily Alpha owns its canonical data contract. External vendors, brokers, primary sources, and future internal feeds are adapters behind that contract. No downstream research, agent, portfolio, risk, or execution component should depend directly on a vendor-specific schema.

## Core principles

1. Provider independence: vendors can be replaced without rewriting the investment platform.
2. Point-in-time requests: every request has an explicit `as_of` boundary.
3. Permanent identity: security-scoped requests use canonical `security_id`, not ticker alone.
4. Explicit failure states: stale, unavailable, conflicting, and erroneous data are represented explicitly.
5. True redundancy: two adapters that depend on the same upstream source count as one independence group.
6. Provenance: every observation has provider, upstream group, version, timestamps, confidence, status, and provenance.
7. Research-only foundation: provider contracts cannot authorize trading or live execution.

## Supported data domains

The V1 contract recognizes:

- market bars
- market quotes
- corporate actions
- earnings/events
- SEC filings
- fundamentals
- estimates/revisions
- macro
- news/catalysts
- institutional activity
- behavioral/alternative data
- portfolio/account data
- options-chain data

Recognizing a domain does not activate an automated strategy. It only gives the platform a canonical place to ingest and evaluate that class of data.

## Provider roles

Each domain capability is tagged as one of:

- `PRIMARY`
- `SECONDARY`
- `BROKER_REFERENCE`
- `OPTIONAL`

The registry also records an `independence_group`. This prevents false redundancy when two APIs are ultimately sourced from the same upstream feed.

## Requests

`DataRequest` is vendor-neutral and point-in-time. A request is either:

- security-scoped through `security_id`, or
- global-scoped through a stable series identifier such as a macro series.

Historical windows may be requested, but the end of the requested window cannot exceed the `as_of` boundary.

## Observations

`ProviderObservation` is the canonical output from any adapter. It contains:

- provider ID
- independence group
- data domain
- metric
- canonical subject key
- value
- observed timestamp
- received timestamp
- source version
- evidence status
- confidence
- reason code
- provenance
- deterministic observation ID

An observation must match its request and may not contain information observed or received after the request's `as_of` boundary.

## Redundancy policy

`RedundancyPolicy` specifies the minimum number of independent upstream groups and any required roles for a data domain. `ProviderRegistry.assess_coverage()` reports whether the architecture satisfies that requirement before any provider is selected for production use.

For critical deterministic data, the target architecture should generally use at least two truly independent upstream groups, with the broker treated as account-state authority and, where useful, a market-data reference rather than the sole market authority.

## Current scope

This stage does not select or purchase vendors, call external APIs, deploy AWS, alter SH24/SH25, modify TradingView, mutate PAPER execution, connect a broker, automate options, or enable live trading.

## Next stage

Stage 4C should implement the first domain-specific reconciliation layer for market data: canonical bars/quotes, cross-source agreement, freshness, conflict detection, and deterministic canonical market state.
