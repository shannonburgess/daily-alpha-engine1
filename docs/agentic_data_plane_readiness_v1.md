# Agentic Intelligence V1 — Stage 9D Data-Plane Operational Readiness

Stage 9D converts provider configuration plus Stage 9B transport telemetry into deterministic operational readiness for the institutional data plane. It answers a different question from the provider registry: not "do we have adapters configured?" but "at this exact as-of boundary, do we have enough healthy, fresh, independent sources to trust this data domain?"

## Inputs

The engine consumes the provider registry, domain-specific readiness policies, immutable `SourceTransportTelemetry`, and an exact timezone-aware `as_of`. Future telemetry is ignored during historical evaluation, so a later recovery cannot retroactively make an earlier data state healthy.

Each domain policy defines minimum healthy upstream independence groups, required provider roles, an optional latency budget, an optional stricter freshness SLA, and whether the domain is required for platform readiness.

## Provider assessment

For each configured provider capability in a domain, the engine selects the latest telemetry available at the as-of boundary. Missing telemetry is explicit. Effective freshness advances as time passes after the telemetry observation; a once-fresh provider therefore becomes stale without needing a fabricated new health event.

Only `HEALTHY` providers inside both freshness and latency budgets count toward strict redundancy. `DEGRADED`, `STALE`, `UNAVAILABLE`, `CONFLICT`, `DATA_ERROR`, and `MISSING` states remain visible and do not satisfy required independent-source or role coverage.

## Domain readiness

A required domain is `BLOCKED` when healthy independence-group count is below policy or a required provider role is absent. An optional domain becomes `WARNING` for the same condition. A domain with sufficient healthy coverage but degraded configured providers is also warning-grade rather than silently hiding the impaired source.

The market-data policy can therefore require both Massive (`MASSIVE_MARKET_DATA`, PRIMARY) and Databento (`DATABENTO_MARKET_DATA`, SECONDARY) to be healthy before cross-provider market reconciliation is considered operationally ready.

## Platform snapshot / command center

The platform snapshot aggregates domain states and exposes deterministic counts of healthy, degraded/error, stale, and unavailable/missing providers plus blocked and warning domains. The snapshot ID is independent of telemetry input ordering and is suitable for command-center history, alert evidence, and later incident review.

A required blocked domain makes the platform data plane `BLOCKED`. Optional degradation makes the platform `WARNING`. This readiness does not authorize trading; it is an operations/evidence gate for downstream research and model layers.

## Authority boundary

Stage 9D is research/operations visibility only. `research_only=true`, `trading_authorized=false`, and `live_trading_enabled=false` are hard invariants. The stage performs no AWS deployment, secret activation, vendor call, broker connection, TradingView or SH24/SH25 mutation, PAPER ledger mutation, execution, capital authorization, or live trading.
