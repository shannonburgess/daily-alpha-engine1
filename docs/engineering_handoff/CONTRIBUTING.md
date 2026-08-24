# Contributing and Merge Discipline

Daily Alpha contains financial research and PAPER-execution logic. Changes should be reviewable, deterministic, traceable, and fail closed when evidence or authority is missing.

## Branching

- Start from the latest authoritative `main`.
- Record the base SHA in the PR when the change is evidence-sensitive or operationally significant.
- Prefer one coherent engineering slice per branch.
- Do not build new high-priority work on stale draft/stacked branches merely because they contain useful old code.

Recommended branch prefixes:

- `fix/` — narrow defects;
- `feat/` — product/runtime capability;
- `research/` — research-only/model/evidence work;
- `docs/` — documentation only;
- `test/` — regression/source-lineage repair.

## Required local/CI checks

```bash
ruff check .
pytest -q
```

`.github/workflows/test.yml` is the current repository quality gate. If CI stops at Ruff, pytest was skipped and must not be reported as passing.

## Testing expectations

Add regression coverage for behavior changes, especially when touching:

- timestamps / point-in-time eligibility;
- evidence IDs / hashes / source revisions;
- TRAIN/VALIDATION/TEST boundaries;
- Pine source/version/book identity;
- risk gates / PAPER ledger semantics;
- AWS proof/restore logic;
- authority flags;
- workflow triggers or manual confirmations.

Prefer tests that prove invariants under adversarial changes (for example, mutate TEST labels and prove fitted parameters do not change) rather than only testing the happy path.

## Determinism

Where practical, identities should be deterministic from normalized inputs. Input ordering, duplicate exact delivery, and retry behavior should not silently alter decision truth.

Use explicit error/reason codes for fail-closed conditions. Avoid catch-all behavior that converts missing/invalid evidence into a plausible value.

## Point-in-time discipline

Never use a payload's historical date as proof that the information was historically available.

A model feature must satisfy trustworthy `known_at <= decision_at`. A label must mature strictly after the decision and be known by the applicable dataset/split boundary.

TEST is evaluation-only. Do not use TEST for fitting, feature selection, threshold selection, hyperparameter selection, or retuning.

## Pine / TradingView discipline

Frozen SH24/SH25 source identity is evidence. Do not edit a frozen source to force parity.

Do not infer actual TradingView input values. Missing external evidence remains missing until captured.

## Safety and authority

Research code must not silently gain execution authority.

Preserve false authority flags unless a separate explicitly reviewed authority program changes them. Common invariants include:

```text
promotion_authorized=false
paper_mutation_authorized=false
trading_authorized=false
live_trading_enabled=false
```

Not every contract contains every flag, but no research/staging change should implicitly authorize live capital.

## Secrets

Never commit:

- API keys/tokens;
- broker/custodian credentials;
- account numbers;
- private `.env` contents;
- secret values in fixtures, logs, workflow summaries, issues, or PR text.

Use logical secret references and approved managed secret stores.

## PR description minimum

A substantial PR should state:

1. purpose;
2. exact behavior added/changed;
3. evidence/lineage impact;
4. what it deliberately does **not** do;
5. validation result (Ruff / complete pytest count once known);
6. deployment/proof state separately from merge state;
7. safety/authority state.

## Merge rule

Before merge:

1. CI green on the current PR head;
2. semantic diff review complete;
3. base/main drift checked;
4. no unresolved evidence/authority ambiguity;
5. expected head SHA used for sensitive merges where available.

A historical green run on an old branch is not current-main validation.

## Documentation rule

If a merge changes how an operator deploys, proves, diagnoses, or interprets a subsystem, update the relevant handoff/runbook documentation in the same PR or immediately afterward.
