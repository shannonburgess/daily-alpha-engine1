# Architecture

This document describes the **current merged core**. Draft/stacked institutional extensions are called out separately and must not be mistaken for production or merged behavior.

## High-level current flow

```text
Market / reference inputs
  ├─ OVTLYR-style universe inputs
  ├─ Massive / Tiingo / FRED staging evidence
  ├─ TradingView Pine signals (SH24 / SH25)
  └─ ORATS research/option evidence where available
            |
            v
Immutable evidence + point-in-time lineage
  ├─ source/provider identity
  ├─ captured_at / known_at boundaries
  ├─ raw SHA-256 / evidence IDs
  └─ source revision / strategy version / book identity
            |
            v
Deterministic normalization and feature contracts
            |
            v
Discovery / ranking / opportunity-board logic
            |
            +-------------------------------+
            |                               |
            v                               v
Research model path                    Frozen Pine control path
TRAIN -> VALIDATION -> TEST            SH24 CONTROL / SH25 CHALLENGER
            |                               |
            +------------ evaluation --------+
                         |
                         v
                 risk / decision gates
                         |
                         v
                 PAPER-only execution
                         |
                         v
       newsletter / dashboard / API / monitoring
```

## Repository boundaries

### `src/daily_alpha/`

Core domain logic. This is where deterministic contracts, evidence identities, model-training protocols, parity checks, decision rules, reports, and PAPER-domain logic belong.

Important current model/evidence areas include:

- point-in-time dataset assembly;
- model fit/evaluation protocols;
- ridge and logistic baselines;
- frozen SH24/SH25 post-TEST benchmark;
- feed receipt -> point-in-time feature evidence;
- Pine source/version/parity contracts.

### `tests/`

Regression and contract protection for the repository. Tests are not optional documentation: many important invariants are easiest to understand by reading their regression test next to the implementation.

Current CI entry point: `.github/workflows/test.yml`.

### `lambda_handlers/`

Staging/runtime handlers for the existing Daily Alpha engine/report/PAPER services. Changes here can participate in the normal staging deployment path and require extra caution.

### `staging_lambda_handlers/`

Physically isolated staging-only services. The Phase 1 Massive/Tiingo/FRED ingestion handler lives here specifically so it can be merged without silently redeploying or connecting the main engine/report/PAPER services.

### `tradingview/`

Audited/frozen Pine sources and related source-gate artifacts. Treat these files as evidence-bearing source identities. Never casually rewrite a frozen Pine file to make a parity test pass.

### `infra/`

AWS infrastructure, CloudFormation templates, bounded IAM policies, and bootstrap instructions. Prefer exact-resource permissions and documented additive policy changes over broadening existing roles.

### `.github/workflows/`

Operational interface for CI, deployment, diagnostics, backtests, PAPER monitors, and manual proofs. Workflows can have very different authority. Read the trigger and environment before running one.

Notable workflows include:

- `test.yml` — repository Ruff + pytest gate.
- `deploy-staging-lambdas.yml` — main staging Lambda deployment path.
- `prove-prospect-v1-staging.yml` — manual V1 prospect staging proof.
- `deploy-staging-data-feed-ingestion.yml` — manual isolated Phase 1 feed deployment/proof.
- `capture-historical-staging-data-feeds.yml` — manual bounded historical raw-evidence capture.
- `monitor-paper-shadows.yml` / `watch-paper-shadow-monitor.yml` — PAPER-shadow monitoring.
- `diagnose-shadow-signal-coverage.yml` — shadow-signal diagnostics.

## Authority architecture

Daily Alpha intentionally separates research truth from execution authority.

A model fit, parity result, risk approval, staging proof, or PAPER signal does **not** automatically grant live execution.

The recurring authority flags are deliberate:

```text
promotion_authorized=false
paper_mutation_authorized=false   # where applicable to research-only contracts
trading_authorized=false
live_trading_enabled=false
```

A new engineer must preserve this separation when extending the system.

## SH24 / SH25 roles

- **SH24 CONTROL** — frozen control strategy identity.
- **SH25 CHALLENGER** — frozen challenger strategy identity.

The paired parity layer requires exact strategy/source/version/book lineage and the same point-in-time market evidence for comparisons. External TradingView evidence remains separate from Python-side harness capability.

## Research-model roles

The current merged adaptive-model track deliberately begins with interpretable baselines. Complexity should be added only after genuine out-of-sample evidence demonstrates that the simpler baselines leave measurable value on the table.

The required chronology is:

```text
TRAIN only: fit / normalization / target construction
VALIDATION only: candidate and threshold selection
TEST only: final untouched evaluation
post-TEST only: frozen SH24/SH25 benchmark comparison
```

TEST must never feed fitting, feature selection, threshold selection, or hyperparameter selection.

## Customer-facing prospect path

The prospect V1 contract maintains a Top Picks presentation while retaining the complete canonical qualifying opportunity board across the supported surfaces. Staging proof validates that the same canonical board is preserved across Newsletter/Dashboard/API. The prospect runtime is designed to remain explicitly controlled rather than silently enabling a customer-facing release.

## Draft / future architecture

The repository also contains significant historical draft/stacked work for broader institutional command-center, Personal CIO, public/private opportunities, multi-asset expansion, provider routing, and Cost & Model Governor concepts.

Those designs may be useful references, but they are **not part of this current merged-core diagram unless a specific slice has been recreated/revalidated on current `main`**.
