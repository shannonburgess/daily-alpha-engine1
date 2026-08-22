# Daily Alpha provider reliability and data-quality incident attribution V1

## Purpose

Stage 9F adds the historical operations layer above the institutional data plane. Stage 9D answers whether a provider is healthy at an exact point in time. Stage 9E records whether each provider observation was eligible to enter canonical reconciliation. Stage 9F converts those immutable records into rolling provider reliability scorecards and explicit data-quality incidents for the command center.

This closes an important institutional gap: a platform should not only know that data is currently available; it should know which source is repeatedly failing, how often it is healthy, how often its observations are excluded, and whether redundancy quality is deteriorating.

## Inputs

The engine consumes only already-governed repo contracts:

- `DataPlaneReadinessSnapshot` history from Stage 9D;
- `CanonicalReconciliationResult` history from Stage 9E;
- `ProviderRegistry` capability/role metadata;
- a versionable `ProviderReliabilityPolicy`;
- an explicit point-in-time `as_of` boundary.

It does not call vendors or infer health from wall-clock time.

## Rolling point-in-time window

`ProviderReliabilityPolicy.window_seconds` defines the evidence window ending at `as_of`. History after `as_of` is ignored, so a future provider recovery or outage cannot alter a historical reliability report. Records older than the window are excluded.

Duplicate readiness snapshots and reconciliation results are deduplicated by their immutable IDs. Input ordering therefore does not change the report identity.

## Provider scorecard

For every provider configured for the policy domain, `ProviderReliabilityAssessment` records:

- provider ID, independence group, and domain role;
- runtime sample count;
- healthy runtime count and healthy ratio;
- reconciliation observation count;
- eligible and excluded observation counts;
- exclusion ratio;
- incident IDs;
- deterministic blockers and warnings;
- PASS / WARNING / BLOCKED status.

The initial policy supports:

- minimum runtime sample history;
- minimum healthy-runtime ratio;
- maximum observation-exclusion ratio;
- role-aware blocking behavior.

Insufficient history is shown as a warning rather than pretending a new provider has proven reliability. PRIMARY and SECONDARY roles block when configured thresholds are breached by default; OPTIONAL sources remain warning-grade unless policy changes explicitly.

## Data-quality incidents

The report creates immutable incidents for operational failures and reconciliation exclusions.

Runtime incident classes:

- `RUNTIME_DEGRADED`
- `RUNTIME_STALE`
- `RUNTIME_UNAVAILABLE`
- `RUNTIME_CONFLICT`
- `RUNTIME_DATA_ERROR`
- `RUNTIME_MISSING`

Reconciliation incident classes:

- `OBSERVATION_EXCLUDED`
- `UNASSESSED_PROVIDER`

Unavailable, conflict, data-error, and unassessed-provider events are critical. Degraded, stale, missing, and lower-severity observation exclusions are warning-grade. Incident identity binds the provider, domain, event time, source assessment/eligibility ID, and exact reasons.

## Unexpected provider injection

A Stage 9E reconciliation result can contain an observation from a provider that was not assessed for the domain. Stage 9E fails that reconciliation closed. Stage 9F additionally creates a critical `UNASSESSED_PROVIDER` incident and blocks the reliability report so the command center can attribute the event instead of treating it as a generic data failure.

## Command-center output

`ProviderReliabilityReport` contains:

- exact domain and `as_of` boundary;
- rolling-window start;
- reliability-policy ID;
- domain status;
- deterministic provider scorecards;
- deterministic incident set;
- provider-level blockers/warnings aggregated to command-center blockers/warnings;
- a stable `report_id` for audit and historical replay.

A future UI can use the report to show provider SLA history, redundancy degradation, exclusion rates, incident timelines, and source-specific operational debt without re-deriving logic in the presentation layer.

## Relationship to canonical authority

The control chain is now:

```text
Transport response / telemetry
          |
          v
Stage 9D operational readiness
          |
          v
Stage 9E readiness-gated canonical reconciliation
          |
          v
Stage 9F reliability scorecard + incident attribution
          |
          v
Command-center operational evidence
```

Stage 9F observes and attributes; it does not bypass Stage 9D or Stage 9E and it cannot make an unhealthy provider eligible.

## Hard authority boundary

Stage 9F is operations/research governance only:

- no AWS deployment;
- no live vendor calls;
- no credential resolution or paid-service activation;
- no broker connection;
- no TradingView mutation;
- no SH24/SH25 mutation;
- no PAPER/live execution mutation;
- no capital authorization;
- no execution authorization;
- `trading_authorized = false`;
- `live_trading_enabled = false`.

Provider reliability is evidence about the integrity of research inputs, not permission to trade.
