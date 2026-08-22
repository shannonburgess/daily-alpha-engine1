# Daily Alpha Agentic Intelligence V1 — Stage 3 Durable Evidence

## Purpose

Stage 3 makes the Agentic Intelligence evidence layer reproducible across time without
connecting it to execution. The goal is to bind every later research/CIO decision to the
exact evidence, source policies, source-health state, and readiness result available at a
specific point in time.

## Core identities

- `evidence_id` — immutable source observation identity
- `snapshot_id` — exact evidence set available for one symbol at one as-of boundary
- `registry_fingerprint` — exact source-policy contract used by the supervisor
- `health_event_id` — immutable source-health/conflict observation
- `bundle_id` — snapshot + source-policy fingerprint + readiness + source-health lineage
- `decision_id` — later research/model/CIO output bound to one evidence bundle

## No-lookahead rule

A snapshot may include an evidence record only when both `observed_at <= as_of` and
`received_at <= as_of`. Evidence arriving after the historical boundary can never appear
in a replay of that boundary.

## Replay contract

Historical replay reconstructs a new in-memory evidence store from the immutable IDs in
the snapshot, re-runs the deterministic `DataSupervisor` against the recorded as-of time,
and recreates the bundle identity. Later evidence cannot change the result of an already
created snapshot.

## Source health

Source health is stored separately from market/security evidence so outages, degraded
feeds, conflicts, and data errors can be audited without rewriting evidence records.
Health events after the snapshot boundary are excluded from that point-in-time bundle.

## Decision lineage

Stage 3 does not make investment decisions. `DecisionLineage` is a research-only contract
for later Momentum/Rotation/Catalyst/CIO layers to bind `BUY`, `WAIT`, `HOLD`, `ADD`,
`TRIM`, `SELL`, or other research outputs to the exact bundle they consumed. A logical
model decision slot cannot be silently rewritten.

## Future persistence adapters

The reference implementation is intentionally local/in-memory. A future reviewed stage
may implement the same contract using:

- immutable S3 objects for evidence/snapshot archives
- DynamoDB indexes for current evidence, snapshot lookup, source health, and lineage
- optional queue/event transport for evidence publication

Those future adapters must preserve the same deterministic IDs and no-lookahead behavior.

## Safety boundary

This stage cannot authorize trading or live execution. It does not deploy AWS, alter
TradingView, mutate SH24/SH25, change candidate ranking, write a PAPER ledger, call a
broker, or create an automated options path. `trading_authorized=false` and
`live_trading_enabled=false` remain invariant.
