# Daily Alpha Institutional Command Center Projection V1

## Purpose

Stage 9J defines the read-only projection contract for a future institutional command center, UI, and API. It is stacked directly on verified Stage 9I so realized model performance and alpha-decay state can appear beside data, provider, model-governance, stress, Research Council, CIO, portfolio-construction, and Risk Governor truth without giving the presentation layer investment authority.

The command center is a projection of governed truth. It does not become another decision maker and cannot recompute, upgrade, override, or mutate upstream investment state.

## Why a projection layer

Daily Alpha already has separate institutional surfaces for data-plane readiness, provider reliability, model governance, model stress, realized model performance, Research Council output, CIO decisions, portfolio proposals, and deterministic risk governance.

A UI or API must not import those objects and invent its own severity, lineage, or recommendation semantics. Stage 9J therefore creates one small, immutable projection envelope that carries the exact upstream record identity into presentation systems.

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

Supported component kinds are:

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

## Deterministic API and drill-down surface

`InstitutionalCommandCenterAPIView` indexes the same immutable snapshot into deterministic platform, portfolio, and security scopes. Scope status remains the worst upstream component status within that scope, and scope identity is independent of input ordering.

Each scope also exposes deterministic component-kind tiles. A tile reports only facts already present in projected components:

- component kind
- PASS / WARNING / BLOCKED status counts
- total component count
- unresolved blocker/warning count
- exact component IDs for drill-down

This supports UI tiles for provider health, model governance/stress/performance, Research Council, CIO, portfolio proposals, Risk Governor vetoes, and explicitly projected incidents without reinterpreting metrics or creating new recommendation logic.

`INCIDENT` is intentionally conservative. Stage 9F historical incident IDs remain lineage on provider-reliability components and are not automatically called unresolved incidents. An INCIDENT tile appears only when an upstream lifecycle surface explicitly projects an incident as a command-center component.

The serialized API surface includes:

- schema version and deterministic API-view ID
- snapshot ID and as-of boundary
- platform/portfolio/security identities
- aggregate PASS/WARNING/BLOCKED counts
- unresolved issue count
- deterministic component IDs
- deterministic component-kind tiles
- component projections with exact source-record/lineage IDs
- explicit false authority flags

This is suitable for a later HTTP/GraphQL/websocket presentation layer without giving that layer investment or execution authority.

## Typed upstream projections

Stage 9J currently projects governed truth from:

- Stage 9D data-plane readiness
- Stage 9F provider reliability
- Stage 9G model governance
- Stage 9H model stress
- Stage 9I realized model performance / alpha decay
- Research Council output
- CIO/Fusion decisions
- Portfolio Construction proposals
- deterministic Risk Governor decisions

Adapters preserve upstream severity and exact lineage; they do not recompute eligibility, recommendations, sizing, or risk decisions.

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
