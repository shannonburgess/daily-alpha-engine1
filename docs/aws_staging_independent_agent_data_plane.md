# Daily Alpha AWS Staging Independent-Agent Data Plane

## Purpose

This document defines the first repo-only infrastructure slice for the Daily Alpha institutional data plane. It prepares AWS **staging** boundaries without deploying resources, activating provider credentials, purchasing data, changing TradingView/SH24/SH25, mutating PAPER ledgers, or creating execution authority.

The frozen stock-primary pre-AWS reference is branch `baseline/stock-primary-pre-aws-2026-08-22` at commit `afc732404df05da8b941f52ec57a7199708169ba`. Active `main` remains authoritative.

## Core architecture rule

Every major data/research domain is an **independent specialist agent/service**. A shared AWS account and common infrastructure may be reused, but each domain owns an isolated queue/DLQ boundary, versioned append-only raw-evidence namespace, health state, freshness policy, lineage and fail-closed disposition.

No domain agent can place an order, mutate a PAPER book, override canonical liquidity/earnings/concentration/portfolio-risk controls, or enable live trading.

```text
provider / canonical source
        |
        v
future connector boundary
        |
        v
independent domain queue ---> domain DLQ
        |
        v
versioned append-only raw-evidence namespace
        |
        v
deterministic adapter / canonical observation
        |
        v
Data Supervisor / Research Council / CIO / Portfolio / Risk
```

The future shared orchestration shape remains:

```text
EventBridge / schedule-event ingress
        -> Step Functions orchestration
        -> domain connector / processor
        -> versioned append-only S3 raw evidence
        -> domain SQS + DLQ
        -> deterministic adapter / canonical evidence
        -> DynamoDB idempotency + bounded current/index state
        -> CloudWatch health / latency / freshness / failures
```

This first slice intentionally provisions **none** of the connector, scheduler, Step Functions, Lambda or secret resources. The IaC foundation is inert until a later explicitly approved staging-activation slice.

## Independent domain services

The canonical repo manifest is `config/aws_staging_agent_domains.json`. It declares these independent services:

- Reference / Security Identity Agent
- SEC Intelligence Agent
- Macro Agent
- Market Structure Primary Agent
- Market Verification Agent
- Fundamental Agent
- Estimate Revision Agent
- News / Catalyst Agent
- Sector Rotation Agent
- Liquidity / Capacity Agent
- Pine Signal Evidence Agent
- Earnings / Event Risk Agent
- Behavioral / Attention Agent
- Institutional Flow Agent
- Model Performance Agent
- Data Reliability / Supervisor Agent

Each manifest entry includes a permanent `agent_id`, a queue name, a DLQ name, a versioned append-only raw-evidence prefix, the governed data domain, a logical credential reference when one is eventually required, and hard false authority flags.

## Existing code contracts reused

This infrastructure layer must not duplicate provider semantics already modeled in the institutional stack:

- Stage 9A / PR #285 — OpenFIGI, SEC EDGAR and FRED/ALFRED adapters.
- Stage 9B / PR #287 — request envelopes, retries, rate limiting, idempotency, raw archive pointers, queue/DLQ semantics and transport telemetry.
- Stage 9C / PR #290 — Massive, Databento, FMP and Benzinga adapters.
- Stage 9D-9F — readiness, canonical eligibility and provider-reliability controls.

When those draft contracts are eventually approved and merged, runtime connectors must implement them rather than introduce a second transport or provider truth model.

## First IaC foundation

`infra/aws/staging/data-plane-foundation.template.json` defines only inert shared storage/state/queue boundaries:

1. encrypted/versioned S3 raw-evidence bucket with public access blocked;
2. DynamoDB idempotency ledger using on-demand billing and server-side encryption;
3. DynamoDB bounded current-state/index table using on-demand billing and point-in-time recovery;
4. one encrypted SQS queue and one encrypted DLQ for every independent domain service;
5. a bounded-retention CloudWatch log group.

The S3 bucket is **versioned and append-only by ingestion contract**, not WORM-enforced. This staging foundation intentionally does **not** enable S3 Object Lock or claim storage-enforced immutability. A future Object Lock/WORM policy would require a separate explicit approval because retention/governance mode changes deletion and recovery semantics.

It deliberately contains no:

- Lambda functions;
- EventBridge rules or Scheduler schedules;
- Step Functions state machines;
- API Gateway endpoints;
- Secrets Manager secret values/resources;
- broker connectivity;
- trading or execution resource.

A later deployment slice must be separately approved and must add least-privilege connector roles and runtime resources one domain at a time.

## Naming and isolation

Staging resources use the prefix `daily-alpha-staging-`. Domain service queue names use kebab-case names from the manifest. Raw evidence is namespaced as:

```text
raw/<domain>/<YYYY>/<MM>/<DD>/<request-or-event-id>/<receipt-id>.<format>
```

Canonical business objects must retain their own deterministic IDs and point-in-time `known_at` / `received_at` semantics. S3 object names are archive locations, not investment identities.

## Secrets policy

The manifest may contain only logical secret names such as:

- `FRED_API_KEY`
- `MASSIVE_API_KEY`
- `DATABENTO_API_KEY`
- `FMP_API_KEY`
- `BENZINGA_API_KEY`

No secret value, token, credential, API key, authorization header or signed URL may be committed, logged, archived, placed in deterministic IDs, or embedded in queue messages.

## Point-in-time and failure semantics

- Raw captures are append-only by ingestion/key convention; rewrites are not a valid ingestion behavior.
- S3 versioning preserves prior object versions if a key is overwritten accidentally, but versioning alone is not treated as WORM/immutable retention.
- Provider failures remain attributable to one domain/provider and cannot be hidden by a different domain succeeding.
- Missing/stale/conflicting required evidence fails closed at the appropriate canonical readiness boundary.
- Independent provider observations are not counted as redundant unless their upstream independence groups differ.
- Paid/vendor-normalized evidence cannot silently become regulator/issuer primary evidence.
- Historical/replay evaluation may use only evidence that was known at the requested as-of boundary.

## Stock-primary compatibility

This data plane is disconnected from entry authority during model validation.

- New Daily Alpha PAPER entries remain STOCK/shares only.
- Fresh confirmed Pine/scanner signal price remains the PAPER model-validation fill.
- ORATS/options cannot authorize, reject, delay or block a new STOCK PAPER entry.
- Company stocks remain subject to the canonical current 30-day average daily share volume strictly greater than 1,500,000 and the $10 server-side floor.
- Earnings/event, concentration and portfolio-risk controls remain authoritative.
- `trading_authorized=false`.
- `live_trading_enabled=false`.

## Activation sequence after explicit approval

1. Deploy the inert staging foundation.
2. Prove encryption, versioning, queue/DLQ isolation, idempotency and monitoring with synthetic fixture messages only.
3. Activate credential-free/primary sources first where possible: SEC EDGAR and OpenFIGI; FRED only after its logical key is safely provisioned.
4. Add one provider connector at a time behind the Stage 9B transport contract.
5. Persist raw captures and canonical observations while all new agents remain research/shadow only.
6. Measure incremental information/alpha contribution before any factor or agent is permitted to influence model promotion.
7. If storage-enforced WORM retention is desired, review S3 Object Lock retention/governance semantics as a separate approval gate before enabling it.

## Hard boundary

This slice is architecture and IaC preparation only. It does not authorize an AWS deployment, vendor activation, paid subscription, production resource, broker route, TradingView mutation, PAPER mutation, options automation, execution/capital authorization or live trading.
