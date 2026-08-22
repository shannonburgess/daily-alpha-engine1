# Daily Alpha Institutional Command Center Projection V1

## Purpose

Stage 9J-A defines the read-only projection contract for a future institutional command center, UI, and API. It is deliberately built from Stage 9H, the latest verified green institutional head, while Stage 9I waits for an executable GitHub Actions gate.

The command center is a projection of governed truth. It does not become another decision maker and cannot recompute, upgrade, override, or mutate upstream investment state.

## Why a projection layer

Daily Alpha already has separate institutional surfaces for data-plane readiness, provider reliability, model governance, model stress, Research Council output, CIO decisions, portfolio proposals, and deterministic risk governance. Stage 9I adds realized model performance and alpha-decay surveillance.

A UI or API must not import those objects and invent its own severity, lineage, or recommendation semantics. Stage 9J-A therefore creates one small, immutable projection envelope that carries the exact upstream record identity into presentation systems.

## Contract

Each `CommandCenterComponent` contains:

- component kind
- entity kind and entity ID
- exact timezone-aware `as_of` boundary
- exact immutable upstream `source_record_id`
- upstream PASS / WARNING / BLOCKED state
- optional security and portfolio identities
- canonical metrics for display
- blockers and warnings without reinterpretation
- immutable drill-down lineage IDs
- deterministic component identity
- hard read-only/no-trading authority flags

Supported component kinds intentionally include future Stage 9I performance state without importing Stage 9I implementation classes:

- DATA_PLANE
- PROVIDER_RELIABILITY
- MODEL_GOVERNANCE
- MODEL_STRESS
- MODEL_PERFORMANCE
- RESEARCH_COUNCIL
- CIO_DECISION
- PORTFOLIO_PROPOSAL
- RISK_GOVERNOR
- INCIDENT

Supported entity scopes are PLATFORM, PORTFOLIO, SECURITY, MODEL, PROVIDER, and DECISION.

## Snapshot behavior

`InstitutionalCommandCenterBuilder` produces an immutable `InstitutionalCommandCenterSnapshot` for one exact point in time.

The builder fails closed when:

- a component is from the future
- a component is stale relative to the exact snapshot boundary
- portfolio identity conflicts with the requested snapshot
- security identity conflicts with the requested snapshot
- two different components claim the same logical slot
- an upstream status is internally inconsistent with its blockers/warnings

Identical duplicate deliveries are idempotently deduplicated.

Snapshot status is a severity roll-up only:

- any BLOCKED component -> snapshot BLOCKED
- otherwise any WARNING component -> snapshot WARNING
- otherwise PASS

The command center cannot upgrade an upstream status.

## Deterministic API-ready surface

`to_dict()` provides a canonical serialization surface containing:

- schema version
- snapshot ID
- as-of boundary
- platform/portfolio/security identities
- aggregate PASS/WARNING/BLOCKED counts
- unresolved issue count
- deterministic component IDs
- the component projections and exact source-record/lineage IDs
- explicit false authority flags

This is suitable for a later HTTP/GraphQL/websocket presentation layer without giving that layer investment or execution authority.

## Dependency strategy

Stage 9J-A is intentionally decoupled from Stage 9I concrete types. Once Stage 9I is CI-green, Stage 9J will add typed adapters that translate each institutional upstream packet into `CommandCenterComponent` without changing this generic projection contract.

That avoids building new dependent code on an unverified head while still advancing the command-center architecture.

## Safety boundary

This stage is repo-only research/operations visibility.

It does not:

- deploy AWS
- activate a data-vendor credential or paid feed
- connect a broker
- mutate TradingView or SH24/SH25
- mutate PAPER ledgers
- authorize portfolio construction
- create orders or execution intents
- authorize capital
- authorize trading
- enable live trading

The command center reports governed state; it never creates authority.
