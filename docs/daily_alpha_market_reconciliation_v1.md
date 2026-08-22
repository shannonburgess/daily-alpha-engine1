# Daily Alpha Canonical Market Reconciliation V1

## Purpose

Daily Alpha should never treat a single external feed as unquestioned market truth. Market-data providers supply observations; the platform reconciles them into canonical market state only after point-in-time, freshness, independence, and agreement checks pass.

## Inputs

The reconciler consumes the provider-agnostic contracts from Stage 4B:

- `DataRequest`
- `ProviderObservation`
- `ProviderRegistry`
- provider role and independence-group metadata

Security-scoped requests are keyed by permanent `security_id`.

## Canonical bars

`MarketBar` normalizes:

- security ID
- timeframe
- bar start/end
- open/high/low/close
- volume

OHLC consistency, positivity, finite values, volume, and timezone-aware bar boundaries are validated before reconciliation.

## Canonical quotes

`MarketQuote` normalizes:

- security ID
- quote timestamp
- bid/ask
- bid/ask sizes
- last price when available

Crossed quotes, invalid prices, invalid sizes, and naive timestamps are rejected.

## Independent-source selection

Only one observation per upstream independence group is selected. Within a group the preferred observation is chosen deterministically using provider role, confidence, recency, and provider ID.

Provider role priority is:

1. PRIMARY
2. SECONDARY
3. BROKER_REFERENCE
4. OPTIONAL

This prevents multiple wrappers around the same upstream feed from creating false confidence.

## Freshness and source health

Observations must:

- match the original request
- be registered for the requested domain
- match the provider's declared independence group
- have `COMPLETE` evidence status
- be within that provider's freshness SLA
- contain no information after the request `as_of` boundary

Excluded sources remain visible in warnings and lineage.

## Agreement rules

V1 compares independent sources against the highest-priority verified reference observation.

For bars, the reconciler verifies:

- same security
- same timeframe
- exact bar-window alignment
- OHLC differences within configurable basis-point tolerance
- volume difference within configurable relative tolerance

For quotes, the reconciler verifies:

- same security
- quote timestamp skew within tolerance
- bid/ask/last differences within configurable basis-point tolerance

A material conflict produces `BLOCKED` and no canonical value.

## Output

`CanonicalMarketState` records:

- security ID
- domain and metric
- point-in-time boundary
- PASS / WARNING / BLOCKED
- canonical provider/upstream group when verified
- canonical normalized value when verified
- every source observation ID
- selected provider IDs
- independent groups
- blockers and warnings
- deterministic state ID
- hard research-only/live-safety flags

A blocked state is structurally prohibited from carrying a canonical value.

## Current scope

This stage does not select a market-data vendor, call a live API, deploy AWS, modify SH24/SH25, change TradingView, mutate PAPER execution, connect a broker, or authorize live trading.

## Next stage

After V1 market reconciliation is stable, the platform can add domain-specific point-in-time frameworks for corporate actions, earnings/events, SEC filings, fundamentals/estimates, macro, news/catalysts, institutional activity, and behavioral data, all using the same provider and evidence architecture.
