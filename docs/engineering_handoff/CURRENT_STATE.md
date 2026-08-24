# Current Engineering State

Snapshot baseline: `a1f071cd1b3816379cf4f31e727ae911c43b5b21`.

This is a takeover-oriented status matrix, not a marketing checklist. Revalidate runtime claims against GitHub Actions/AWS evidence before changing a status.

| Subsystem | Coded | Tested / CI | Merged | Deployed / Proven | Current boundary |
| --- | --- | --- | --- | --- | --- |
| Core Python package and CI | yes | Ruff + complete pytest suite; latest merged PR path reached 923 tests | yes | repo/runtime dependent | research/PAPER only |
| Prospect V1 opportunity board | yes | yes | yes | staging proof succeeded via `prove-prospect-v1-staging.yml` | no live-trading authority |
| SH24 CONTROL | yes | extensive parity/source/monitor contracts | yes | Python/AWS evidence harness present | final external TradingView paired evidence still required |
| SH25 CHALLENGER | yes | extensive parity/source/monitor contracts | yes | exact source lineage restored on `main` | final external TradingView paired evidence still required |
| Paired SH24/SH25 parity proof gate | yes | yes | yes | evidence state can remain `MISSING_EXTERNAL_EVIDENCE` | do not call missing evidence a parity failure |
| PAPER shadow monitoring | yes | yes | yes | staging/PAPER monitoring workflows exist | read-only diagnostics; no live capital |
| Model dataset assembly | yes | leak-proof chronology and lineage regressions | yes | repo research capability | genuine empirical corpus still incomplete |
| Ridge baseline | yes | TRAIN-only fit / VALIDATION selection / untouched TEST regressions | yes | research capability | no predictive-alpha claim |
| Logistic baseline | yes | TRAIN-only fit / VALIDATION selection / untouched TEST regressions | yes | research capability | no predictive-alpha claim |
| Frozen-control OOS benchmark | yes | yes | yes | evaluation-only contract | TEST cannot influence fitting/selection |
| Massive/Tiingo/FRED staging ingestion | yes | yes | yes | **AWS deploy/proof still required** unless newer evidence supersedes this file | isolated; no PAPER/live route |
| Bounded historical feed capture | yes | yes | yes | manual workflow exists | `captured_at` only; no historical backdating |
| Feed receipt -> point-in-time model evidence | yes | yes | yes | repo capability | historical request dates never become `known_at` by themselves |
| Live brokerage execution | no authorization | n/a | n/a | no | `trading_authorized=false`; `live_trading_enabled=false` |

## Proven launch item

The prospect V1 staging proof has already completed successfully. Its contract verifies the canonical qualifying board across Newsletter/Dashboard/API and restores the exact prior staging Lambda environment after the temporary proof configuration. This is a staging presentation/delivery proof, not live trading authorization.

## TradingView parity state

The repository has strong SH24/SH25 source identity, replay, paired evidence, and comparison contracts. The remaining gate is external TradingView evidence captured from the unchanged real script instances/settings/exports. Until that arrives, the correct status is:

**MISSING EXTERNAL EVIDENCE — not FAILED PARITY.**

## Model research state

The repository can build immutable point-in-time training datasets, create deterministic walk-forward folds, fit interpretable ridge/logistic candidates using TRAIN only, select using VALIDATION only, evaluate untouched TEST, and compare a completed TEST result against frozen SH24/SH25 controls.

What has **not** been proven is predictive alpha from a genuine historical market corpus with trustworthy historical availability for all required features/labels. Do not promote a model or claim alpha based on fixture/synthetic regression tests.

## Data-feed state

The Phase 1 Massive/Tiingo/FRED ingestion Lambda, infrastructure, IAM policies, canary schedules, CloudWatch proof logic, bounded historical capture workflow, and receipt-to-model evidence bridge are merged. The ingestion service was intentionally isolated from the normal engine/report/PAPER auto-deploy path.

Before calling it staging-proven, verify issue #354 and the workflow history for `deploy-staging-data-feed-ingestion.yml`. At the baseline of this handoff the known gate was the bounded one-time IAM bootstrap described in `infra/aws/staging/DATA_FEED_INGESTION_BOOTSTRAP.md`, followed by the manual deployment/proof workflow.

## Branch hygiene warning

Several substantial draft/stacked PRs predate current `main` and contain useful architecture, but historical green CI on those branches is **not current-main validation**. Examples include the Personal CIO/public-private/cost-governor and older institutional command-center stacks. Recreate or carefully reconcile the desired slice from current `main`; do not force-merge stale ancestry.
