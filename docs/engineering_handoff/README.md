# Daily Alpha Engineering Handoff

**Start here if you are taking over engineering, quantitative research, AWS operations, or release responsibility for Daily Alpha.**

This folder is the concise system-of-record entry point for the repository. It is intentionally separate from chat history. Detailed subsystem documentation remains under `docs/`, but this pack explains how the pieces fit together, what is proven, what is not proven, and where a new engineer should work next.

## Verified baseline

This handoff was created from authoritative `main` commit:

`a1f071cd1b3816379cf4f31e727ae911c43b5b21`

At that baseline the most recent merged PR was #369, and its PR CI passed Ruff plus 923 tests. Always re-check current `main`, open PRs, and workflow evidence before relying on a status statement in this folder.

## Non-negotiable safety state

Daily Alpha is a research, staging, and PAPER system. The repository must not be interpreted as permission to trade live capital.

- `trading_authorized=false`
- `live_trading_enabled=false`
- model promotion is not automatic
- TradingView configuration must not be mutated merely to force parity
- fixture/synthetic test success is not predictive-alpha evidence
- historical data retrieved today must not be backdated as though it was known historically

## Read in this order

1. [`CURRENT_STATE.md`](CURRENT_STATE.md) — what is coded, tested, merged, deployed, proven, blocked, and not authorized.
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — repository layout and current merged system flow.
3. [`DATA_MODEL_LINEAGE.md`](DATA_MODEL_LINEAGE.md) — point-in-time evidence, hashes, model splits, and SH24/SH25 lineage rules.
4. [`RUNBOOK.md`](RUNBOOK.md) — local setup, CI, staging workflows, diagnostics, and rollback discipline.
5. [`MANUAL_GATES.md`](MANUAL_GATES.md) — actions that require an explicit human/external proof.
6. [`CONTRIBUTING.md`](CONTRIBUTING.md) — branch, PR, testing, safety, and merge rules.
7. [`OPEN_WORK.md`](OPEN_WORK.md) — prioritized remaining work and treatment of stale/draft branches.

## Repository map

- `src/daily_alpha/` — core deterministic research, evidence, model, parity, risk, report, and PAPER-domain logic.
- `tests/` — regression and contract tests. CI runs the complete suite.
- `lambda_handlers/` — existing staging Lambda entry points for engine/report/PAPER services.
- `staging_lambda_handlers/` — isolated staging-only services such as Phase 1 data-feed ingestion.
- `tradingview/` — frozen/audited Pine sources, source gates, and parity artifacts.
- `infra/` — AWS templates, bounded IAM policies, bootstrap notes, and deployment infrastructure.
- `scripts/` — deterministic render/build/validation utilities.
- `.github/workflows/` — CI, staging deploy/proof, diagnostics, backtests, PAPER monitoring, and manual evidence workflows.
- `docs/` — detailed subsystem documentation.

## First 30 minutes for a new engineer

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
ruff check .
pytest -q
```

Then:

1. Confirm the current `main` SHA.
2. Review recent merged PRs and any open draft PRs before creating a branch.
3. Read `CURRENT_STATE.md` and `OPEN_WORK.md`.
4. Do not assume an old branch is current just because its historical CI is green.
5. Do not deploy or dispatch a manual workflow until the relevant runbook/manual gate has been checked.

## Evidence vocabulary

Use these words precisely:

- **CODED** — source exists.
- **TESTED** — automated contract/regression tests exist.
- **CI GREEN** — the relevant commit/PR completed required CI successfully.
- **MERGED** — source is on authoritative `main`.
- **DEPLOYED** — code is present in the intended AWS/staging runtime.
- **STAGING_PROVEN** — the real staging path was executed and produced the required proof.
- **PAPER** — simulated execution/ledger behavior only.
- **LIVE** — live-capital execution; currently **not authorized**.

Never collapse these states into one word such as “done.”