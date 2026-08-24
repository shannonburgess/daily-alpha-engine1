# Manual and External Gates

These gates exist because some actions either require external systems/human evidence or intentionally must not be automated into higher authority.

## 1. TradingView SH24 / SH25 paired evidence

**Human/external action required.**

Capture the actual unchanged TradingView evidence for both SH24 CONTROL and SH25 CHALLENGER, including the exact script-instance/input identity and machine-readable outcome/signal exports required by the paired evidence contract.

Rules:

- do not change TradingView inputs to make Python agree;
- do not guess missing default values;
- preserve exact source/version/model/book identity;
- preserve `process_orders_on_close=true`;
- use the same/frozen market evidence required by the paired comparison contract.

Until the evidence is captured and ingested, the status remains `MISSING_EXTERNAL_EVIDENCE` rather than `FAILED_PARITY`.

## 2. Phase 1 data-feed AWS bootstrap

**Human AWS action may be required before first deployment.**

Follow `infra/aws/staging/DATA_FEED_INGESTION_BOOTSTRAP.md` and apply only the documented bounded additive IAM policies. Then manually dispatch `Deploy Phase 1 staging data-feed ingestion` from current `main`.

Do not widen the GitHub caller unnecessarily and do not grant it direct feed-secret read access beyond the designed runtime boundary.

## 3. Historical feed capture

**Manual workflow dispatch required.**

Use `Capture bounded historical staging feed evidence` only after the deployed ingestion service proves it supports the backfill contract.

The workflow requires explicit confirmation and bounded dates. A successful historical raw capture is not permission to backdate `known_at`.

## 4. Prospect V1 staging proof / rollout changes

The prospect proof workflow is manual because it exercises real staging report/newsletter delivery and temporarily changes a staging runtime flag before restoring the exact prior environment.

A historical successful staging proof does not automatically authorize a production release or future behavior changes. Re-prove when a material release-affecting contract changes.

## 5. Model empirical promotion gate

No research model may be promoted merely because its code path is implemented or its fixture tests pass.

Before promotion discussion, require at minimum:

- genuine point-in-time feature/label corpus;
- documented source/known-at lineage;
- leak-proof TRAIN/VALIDATION/TEST execution;
- untouched TEST metrics;
- frozen SH24/SH25 post-TEST benchmark;
- robustness review appropriate to the sample/capacity;
- explicit separate approval for any PAPER or capital authority change.

## 6. PAPER -> live capital

There is **no current live-trading authorization**.

`trading_authorized=false` and `live_trading_enabled=false` are not convenience defaults to toggle during debugging. A future live-capital path requires a separate deliberate governance, broker/custodian, risk, operations, monitoring, reconciliation, and capital-authorization program.

No engineer should infer authority from a successful staging/PAPER/model/parity test.

## 7. Secrets and external accounts

Provider credentials must be entered/stored through the approved external secrets process, not pasted into source, issues, PRs, logs, or documentation.

When a task requires a user action in GitHub, AWS, TradingView, a provider portal, or another external account, document the exact action and wait for real evidence rather than fabricating completion.
