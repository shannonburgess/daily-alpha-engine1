# Agentic Command Center Typed Adapters V1

## Purpose

Stage 9J-A now includes typed, read-only projection adapters for the latest verified-green institutional packet types available from Stages 9D through 9H. The adapters translate upstream governed truth into the generic command-center schema without recomputing investment, model-risk, or provider-health decisions.

## Included projections

- `DataPlaneReadinessSnapshot` -> platform DATA_PLANE component.
- `ProviderReliabilityReport` -> domain-level reliability component plus provider scorecards.
- `ModelGovernancePacket` -> security-level governance component plus per-model eligibility components.
- `ModelStressPacket` -> security-level stress component plus per-model robustness components.

## Projection rules

Every projected component preserves the exact upstream `as_of` boundary and immutable source record ID. Upstream PASS/WARNING/BLOCKED severity is preserved and cannot be silently upgraded. Provider/model packet IDs, assessment IDs, policy IDs, registry IDs, model-view IDs, validation IDs, scenario-assessment IDs, and incident IDs are retained as metrics or drill-down lineage.

The adapter layer does not reinterpret a provider as healthy, promote a model, change a stress verdict, create a portfolio proposal, or make an execution decision. It only produces deterministic UI/API-facing projections of already-governed upstream records.

## Data-plane warning semantics

Stage 9D can report a platform WARNING while an optional domain is BLOCKED. The command-center component therefore records optional blocked domains as warning-grade operational issues when the upstream platform status is WARNING. Required-domain blocks remain blocker-grade when the upstream platform status is BLOCKED. This preserves the Stage 9D severity decision instead of accidentally escalating or suppressing it during projection.

## Provider reliability semantics

The domain report and each provider assessment are projected separately so a future UI can show both the aggregate domain condition and provider-level drill-down. Historical incidents remain lineage/metrics on reliability components rather than being automatically treated as unresolved live blockers; active-incident lifecycle can be added as a separate operational surface later.

## Model governance and stress semantics

Security-level packet components preserve the aggregate gate. Per-model components expose lifecycle stage, validation lineage, CIO-research eligibility, stress pass ratio, scenario coverage, and stress qualification. These projections do not grant portfolio-construction, execution, capital, or live authority.

## Deferred Stage 9I adapter

Model-performance / alpha-decay projection remains intentionally deferred until Stage 9I receives an executable CI gate. The generic `MODEL_PERFORMANCE` component kind already exists, so adding the typed Stage 9I adapter later will not require changing the command-center schema.

## Safety boundary

This layer is repository-only and read-only. It does not deploy AWS, activate vendors or credentials, connect a broker, mutate TradingView or SH24/SH25, mutate PAPER ledgers, automate options, authorize execution/capital, or enable live trading.
