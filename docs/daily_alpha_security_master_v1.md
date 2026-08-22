# Daily Alpha Canonical Security Master V1

## Purpose

Daily Alpha is being built as a quantitative investment platform, not a ticker-driven trading bot. The Security Master gives every investable instrument a stable internal identity and makes security resolution point-in-time, reproducible, and auditable.

## Core principle

Ticker is an alias, not identity.

Every instrument receives a permanent `security_id`. The same `security_id` survives ticker changes, exchange changes, rebrands, and other corporate actions. Every version of a security definition has an effective interval and immutable `record_id`.

## Canonical fields

Each `SecurityMasterRecord` contains:

- permanent `security_id`
- stable `issuer_id`
- issuer name
- asset type
- primary ticker
- exchange MIC
- currency and country
- sector and industry
- listing status
- optionable state
- share class where applicable
- durable identifiers such as FIGI/CUSIP/ISIN/CIK/internal IDs
- point-in-time ticker aliases
- effective-from/effective-to timestamps
- source version and provenance
- hard research-only/live-safety flags

## Institutional invariants

1. Durable identifiers cannot silently move from one `security_id` to another.
2. Multiple active versions of the same `security_id` may not overlap.
3. Symbol resolution is always evaluated at an explicit timezone-aware `as_of` boundary.
4. Ambiguous tickers fail closed rather than selecting an arbitrary security.
5. A primary ticker must have a matching active alias at the version start.
6. Snapshot identity is deterministic and independent of insertion order.
7. Security Master records cannot authorize trading or live execution.

## Historical behavior

A ticker change is represented by non-overlapping versions of the same permanent security identity. Historical research can therefore resolve the old ticker before the change and the new ticker after the change while keeping all evidence, features, decisions, and attribution connected to the same `security_id`.

## Why this matters

All future Daily Alpha components should ultimately reference `security_id` rather than ticker alone:

- market data
- fundamentals
- SEC filings
- earnings/events
- news/catalysts
- institutional activity
- portfolio positions
- alpha engines
- agent research
- CIO decisions
- risk exposure
- execution receipts
- attribution and model learning

This prevents ticker reuse, symbol ambiguity, mergers, listings, and corporate actions from corrupting the historical investment record.

## Current scope

V1 is an in-memory/reference contract only. It does not select a data vendor, call an external API, deploy AWS infrastructure, alter SH24/SH25, modify TradingView, mutate PAPER execution, connect a broker, or enable live trading.

## Next stage

After Security Master V1 is proven, Stage 4B should define provider-agnostic institutional data interfaces keyed by `security_id`, beginning with market data, corporate actions, earnings/events, filings, fundamentals, macro, and news/catalyst sources.
