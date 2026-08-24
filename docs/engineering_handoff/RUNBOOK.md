# Engineering Runbook

This runbook is intentionally conservative. When a workflow or AWS state disagrees with this document, stop and inspect the current repository/runtime rather than forcing the expected outcome.

## Local development

Requirements: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
ruff check .
pytest -q
```

Primary project configuration: `pyproject.toml`.

Do not merge a change with a red required CI run.

## Normal branch / PR flow

1. Fetch authoritative `main` and record its SHA.
2. Create a focused branch from that exact current `main`.
3. Make the smallest coherent change.
4. Add/update regression coverage and documentation where behavior/operations change.
5. Open a PR with explicit scope and safety boundaries.
6. Wait for `.github/workflows/test.yml` to complete Ruff and the full test suite.
7. Review the diff semantically; green CI alone is not merge approval.
8. Re-check base/head drift before merge.
9. Merge only the reviewed, current branch.

If a branch is old or stacked on historical ancestry, prefer recreating the desired slice from current `main` instead of force-merging it.

## Main staging Lambdas

Workflow: `.github/workflows/deploy-staging-lambdas.yml`.

This is the staging deployment path for the existing engine/report/PAPER Lambda set. Read the workflow before dispatch/re-run because changes under `lambda_handlers/**` or related runtime code may affect more than one service.

After a deployment, use the repository's smoke/functional workflows rather than assuming a successful CloudFormation/Lambda update means end-to-end behavior is correct.

Relevant workflows include:

- `smoke-test-staging-lambdas.yml`;
- `functional-test-staging-engine.yml`;
- `functional-test-staging-paper-ledger.yml`.

## Prospect V1 staging proof

Workflow: `.github/workflows/prove-prospect-v1-staging.yml`.

This is manual-only. Its proven contract temporarily enables the prospect V1 runtime in staging, invokes the real staging report/newsletter path, verifies the canonical opportunity-board delivery contract, and restores the exact prior Lambda environment.

Historical note: an earlier failure was caused by an invalid report session; the fixed workflow uses the valid manual report session while retaining unique proof identity in the run ID.

Do not use an old failed-run re-run if the fix exists only on newer `main`; dispatch from current `main` instead.

## Phase 1 Massive / Tiingo / FRED ingestion

Primary workflow: `.github/workflows/deploy-staging-data-feed-ingestion.yml`.

The ingestion service is intentionally isolated under `staging_lambda_handlers/` and is not meant to be silently coupled to the normal engine/report/PAPER deployment.

Before first deployment/proof, follow:

`infra/aws/staging/DATA_FEED_INGESTION_BOOTSTRAP.md`

Apply only the documented bounded IAM additions. Do not broaden the GitHub caller or expose provider secret values.

The deployment/proof workflow is expected to:

- render the repo-backed CloudFormation template;
- use short-lived GitHub OIDC AWS credentials;
- deploy the isolated ingestion stack;
- verify function safety configuration;
- verify EventBridge canary schedules;
- invoke Massive, Tiingo and FRED canaries;
- validate research-only receipts;
- validate CloudWatch success evidence and alarms;
- publish sanitized proof evidence.

Check issue #354 and workflow history before declaring `STAGING_PROVEN`.

## Historical feed capture

Workflow: `.github/workflows/capture-historical-staging-data-feeds.yml`.

This is manual-only and intentionally bounded.

Key controls:

- exact `main` required;
- explicit confirmation required;
- provider/target/date validation before AWS/provider calls;
- maximum 31 calendar days per run;
- future end dates rejected;
- deployed ingestion smoke capability checked before provider call;
- sanitized receipt validation after capture;
- `known_at_basis=CAPTURED_AT_ONLY`;
- `historical_known_at_backdating_authorized=false`.

Historical capture creates immutable raw evidence; it does not make the payload historically point-in-time eligible by itself.

## PAPER shadow monitoring

Primary monitoring/diagnostic workflows include:

- `monitor-paper-shadows.yml`;
- `watch-paper-shadow-monitor.yml`;
- `diagnose-shadow-signal-coverage.yml`;
- `refresh-paper-shadow-monitor-on-source-change.yml`;
- `refresh-paper-shadow-monitor-after-source-diagnostic.yml`.

Genuine current-session strategy events should preserve exact SH24/SH25 source/version/book/timeframe/timestamp lineage. E2E/connectivity proof traffic must not be misclassified as genuine strategy evidence.

A monitor finding is diagnostic evidence; it must not mutate TradingView or grant live execution authority.

## TradingView parity proof

Repository-side documentation starts with:

- `docs/pine_paired_evidence_capture_v1.md`;
- `docs/pine_historical_parity_evidence_v1.md`;
- `docs/pine_parity_evidence_readiness.md`;
- `docs/sh25_parity_reconciliation.md`.

The final paired evidence requires real unchanged TradingView script-instance/settings/export evidence. Do not invent or infer missing input values.

Classification discipline:

- missing/cross-wired/unavailable external evidence -> `MISSING_EXTERNAL_EVIDENCE`;
- observed Pine/Python comparison discrepancy -> `FAILED_PARITY`;
- all required evidence and comparisons complete -> `PASSED`.

## Failure triage order

When a workflow fails:

1. Identify the exact workflow run, commit SHA, job, and failed step.
2. Pull the step/job logs before changing code.
3. Determine the failing layer: lint/test, workflow contract, AWS auth/IAM, Lambda configuration, provider response, data contract, or downstream application logic.
4. Fix the narrow root cause.
5. Run CI again on the new head.
6. Never call a skipped test step “passing.”
7. Never re-run an old workflow commit when the fix exists only on newer `main`.

## Secrets

Never commit API keys, tokens, account numbers, broker credentials, or `.env` values.

The repository uses logical secret references/environment configuration and AWS Secrets Manager for staged provider credentials. Logging and proof receipts should be sanitized and must not emit secret values.

## Rollback discipline

For staging changes that temporarily mutate an environment (for example, a proof runtime flag), snapshot exact prior state and restore it in a finally/always path. Verify the restoration before accepting the proof.

For code deployment problems, prefer reverting/redeploying a known-good commit over ad-hoc runtime edits that are not represented in Git history.
