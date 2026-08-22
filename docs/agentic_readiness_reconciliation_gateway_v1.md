# Daily Alpha readiness-gated canonical reconciliation V1

## Purpose

Stage 9E binds operational provider health to canonical data authority. Stage 9D answers whether a provider is healthy, fresh, independent, and within latency policy at an exact as-of boundary. The pre-existing market and research reconcilers answer whether observations agree semantically. Stage 9E requires both conditions before data can become canonical.

A provider observation marked `COMPLETE` is therefore not sufficient by itself. If the provider runtime is degraded, stale, unavailable, conflicting, in data-error state, or absent from the domain readiness assessment, the observation cannot silently participate in canonicalization.

## Control flow

```text
Stage 9B transport telemetry
          |
          v
Stage 9D domain operational readiness
          |
          | exact as-of + domain readiness ID
          v
Stage 9E InstitutionalReconciliationGateway
          |
          +--> eligibility gate per observation/provider
          |      - HEALTHY -> eligible
          |      - DEGRADED/STALE/UNAVAILABLE/CONFLICT/DATA_ERROR/MISSING -> excluded
          |      - provider not assessed for domain -> fail closed
          |
          +--> MARKET_BARS / MARKET_QUOTES
          |      -> MarketDataReconciler
          |
          +--> FUNDAMENTALS / ESTIMATES_REVISIONS / MACRO /
                 NEWS_CATALYSTS / INSTITUTIONAL / BEHAVIORAL
                 -> ResearchFactReconciler

Result = readiness snapshot ID + domain readiness ID + eligibility lineage
       + canonical state ID + combined blockers/warnings
```

## Exact point-in-time binding

`DataRequest.as_of`, `DataPlaneReadinessSnapshot.as_of`, and the selected `DomainOperationalReadiness.as_of` must be exactly equal. A newer readiness snapshot cannot be used to repair or reinterpret an older reconciliation attempt. This prevents future provider recovery telemetry from leaking into historical research replay.

## Observation eligibility

Every incoming observation receives an `ObservationEligibilityAssessment` containing:

- immutable observation ID;
- provider ID and independence group;
- whether the observation was eligible;
- Stage 9D runtime status;
- runtime assessment ID;
- deterministic exclusion reason when ineligible.

Only `ProviderRuntimeStatus.HEALTHY` observations are passed to the semantic reconcilers. Configured but unhealthy providers are excluded with warnings. A provider that is not present in the domain readiness assessment is treated as an unexpected data-plane injection and blocks the attempt.

## Severity propagation

The gateway never upgrades a weaker upstream state:

- blocked domain readiness prevents reconciliation and produces no canonical state;
- a blocked canonical reconciler result remains blocked;
- a readiness warning propagates even when the canonical reconciler itself passes;
- exclusion warnings remain attached to the gateway result;
- only a clean readiness PASS plus clean canonical PASS can produce gateway PASS.

This makes the gateway result the authoritative ingress lineage record for downstream feature and research consumption.

## Deterministic lineage

`CanonicalReconciliationResult` binds:

- `DataRequest.request_id`;
- domain and exact as-of boundary;
- canonical route;
- Stage 9D data-plane snapshot ID;
- Stage 9D domain readiness ID;
- eligibility assessment IDs;
- incoming, eligible, and excluded observation IDs;
- canonical state ID when one exists;
- blockers and warnings;
- permanent research-only authority flags.

Input observation ordering is normalized, so reversing fixture order does not change the result ID or canonical state ID.

## Initial supported routes

### Market data

- `MARKET_BARS` -> `MarketDataReconciler.reconcile_bar`
- `MARKET_QUOTES` -> `MarketDataReconciler.reconcile_quote`

This is the path used by Massive and Databento observations from Stage 9C.

### Research facts

- `FUNDAMENTALS`
- `ESTIMATES_REVISIONS`
- `MACRO`
- `NEWS_CATALYSTS`
- `INSTITUTIONAL`
- `BEHAVIORAL`

These domains dispatch to `ResearchFactReconciler`, preserving the existing primary-source, corroboration, single-source-warning, and authority semantics. FMP and Benzinga therefore remain vendor/secondary research evidence; Stage 9E does not elevate their epistemic authority.

## Command-center meaning

The command center can now distinguish four separate states that previously could be conflated:

1. provider configured;
2. provider operationally healthy;
3. observation eligible for reconciliation;
4. observation accepted into a canonical state.

A future UI can expose the IDs and reasons from each boundary without needing to infer why a data point was accepted or rejected.

## Hard authority boundary

Stage 9E remains data governance only:

- no AWS deployment;
- no vendor call or credential activation;
- no paid-service activation;
- no broker connection;
- no TradingView mutation;
- no SH24/SH25 mutation;
- no PAPER/live execution mutation;
- no capital authorization;
- no execution authorization;
- `trading_authorized = false`;
- `live_trading_enabled = false`.

Operational readiness and canonical data quality are necessary research controls, not permission to trade.
