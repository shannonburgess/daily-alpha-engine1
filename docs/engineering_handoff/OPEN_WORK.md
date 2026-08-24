# Open Work

This backlog is intentionally ordered by evidence/operational value, not by how much historical code already exists on draft branches.

## Priority 1 — Complete SH24 / SH25 external TradingView parity evidence

Repository-side source identity, paired capture contracts, replay/evaluation gates, and paired proof classification are merged.

Remaining work is primarily external evidence:

- capture actual unchanged SH24/SH25 TradingView input settings;
- capture exact script-instance/export identity;
- obtain the required machine-readable signal/per-bar outcome exports;
- ingest the paired packet using the frozen same-market-evidence contract;
- classify as `PASSED` or genuine `FAILED_PARITY` only after the comparison exists.

Until then: `MISSING_EXTERNAL_EVIDENCE`.

## Priority 2 — Prove and extend genuine point-in-time data

### Phase 1 staging ingestion

- verify/apply the bounded AWS bootstrap in `infra/aws/staging/DATA_FEED_INGESTION_BOOTSTRAP.md` if it has not already been completed;
- dispatch `deploy-staging-data-feed-ingestion.yml` from current `main`;
- require real Massive/Tiingo/FRED + CloudWatch proof before marking issue #354 staging-proven.

### Historical availability

The merged generic historical backfill is deliberately capture-time-only. Continue provider-specific work that can prove historical availability/revision semantics instead of weakening `known_at`.

FRED/ALFRED vintage semantics are a natural next research slice because provider real-time/vintage metadata can support stronger historical lineage than a generic backfill.

## Priority 3 — First genuine empirical model run

Once the corpus is trustworthy:

1. freeze the feature schema and label definition;
2. assemble the point-in-time dataset;
3. define chronological TRAIN/VALIDATION/TEST windows;
4. fit the simple ridge baseline on TRAIN only;
5. run the logistic baseline under the same evidence discipline;
6. select on VALIDATION only;
7. evaluate the fixed winner on untouched TEST;
8. compare the completed TEST result against frozen SH24 and SH25 controls;
9. record results without automatic promotion.

Do not add a more complex tree/ensemble model merely because the implementation is interesting. Add complexity only if genuine OOS evidence shows the interpretable baselines leave measurable value on the table.

## Priority 4 — Continue PAPER soak / reliability

Accumulate trustworthy genuine-strategy shadow evidence and keep improving diagnosis for:

- signal lineage;
- blocker/reason distribution;
- data freshness/availability;
- strategy source/version drift;
- bar vs receipt timestamp integrity;
- book isolation;
- ledger/fill behavior.

Keep E2E/connectivity proof traffic separate from genuine strategy diagnosis.

## Priority 5 — Product/release hardening after evidence gates

The prospect V1 staging proof has succeeded, but any material change to the customer-facing contract should be re-proven. Continue readability/format quality, operational monitoring, and release discipline without conflating staging proof with live-capital authorization.

## Priority 6 — Reconcile valuable draft architecture from current main

There is substantial unmerged historical work. Treat it as a design/code reference, not as current truth.

Notable draft areas include:

- Personal CIO / multi-asset contracts (#328);
- public/private opportunity architecture (#329);
- Cost & Model Governor (#331);
- sector residual momentum research (#321);
- older stacked institutional data-plane/model-governance/command-center PRs (roughly #285–#315 and their dependencies).

For any slice that becomes a priority:

1. identify the smallest desired capability;
2. recreate/rebase it from current `main`;
3. reconcile it with newer point-in-time, SH24/SH25, prospect, and PAPER contracts;
4. rerun the full current suite;
5. merge only after current-main validation.

Do not force the entire stale stack into `main`.

## Explicitly not an open implementation shortcut

Do **not** “finish” the platform by:

- enabling live trading;
- fabricating TradingView evidence;
- backdating historical data availability;
- promoting a model without genuine OOS evidence;
- weakening IAM because a deployment is inconvenient;
- bypassing failing tests;
- treating a draft branch's historical CI as current validation.

Those actions would reduce trustworthiness rather than complete the build.
