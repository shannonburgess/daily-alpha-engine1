# Ranked Candidate → Alert Lifecycle

Status: dry-run/research-only design. No TradingView mutation is enabled.

Tracks: #89.

## Boundary

The ranked Daily Alpha candidate set is an **input to alert monitoring**, not trade authorization. An alert can observe a symbol/strategy condition; it cannot bypass the Pine event contract, fresh ORATS checks, portfolio-risk gates or paper/live execution boundaries.

## Desired-state manifest

Each desired alert records:

- symbol;
- explicit strategy version;
- timeframe;
- enabled state;
- ranked-candidate source timestamp;
- review/expiration timestamp.

The source timestamp must be fresh and complete before any change can be proposed.

## Deterministic diff

The dry-run planner compares desired state with the separately observed alert inventory and emits one of:

- `CREATE` — desired candidate has no observed alert;
- `UPDATE` — same strategy version but configuration drift exists;
- `DISABLE` — observed active alert is no longer desired;
- `MIGRATE_STRATEGY` — strategy version differs and requires an explicit migration path;
- `NO_CHANGE` — desired and observed state already match;
- `DATA_ERROR` — source candidate data is stale or incomplete.

A re-run against unchanged inputs should produce `NO_CHANGE`, not duplicate create/update actions.

## v2.3 → v2.4 migration rule

Existing v2.3 alerts must not be silently edited into v2.4. The planner emits `MIGRATE_STRATEGY`, preserving the observed v2.3 identity and the desired v2.4 state in the audit record. A future authorized mutation layer should create/transition the v2.4 alert explicitly and retain the old alert history.

## Approval boundary

The current `AlertPlan` always returns:

- `dry_run = True`
- `mutation_allowed = False`

No connector/API call to TradingView exists in this work. A later mutation layer requires explicit user approval, reconciliation, rate limiting, retries and post-change drift checks.

## Staging validation

Before real alert automation can be authorized:

1. generate manifests from immutable ranked-candidate outputs;
2. prove stale/incomplete source inputs produce only `DATA_ERROR`;
3. prove identical inputs are idempotent;
4. prove removed candidates produce `DISABLE`, not historical deletion;
5. prove strategy-version changes produce explicit migrations;
6. prove the planner cannot create a paper-trade ledger event;
7. compare desired vs observed alerts and preserve the diff as an audit artifact;
8. require human approval before the first real TradingView mutation.
