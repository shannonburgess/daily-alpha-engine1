# Daily Alpha Engine

Auditable quantitative research, staging, and PAPER-trading platform for the Daily Alpha workflow.

> **Current authority:** research / staging / PAPER only. No live brokerage execution. `trading_authorized=false` and `live_trading_enabled=false` remain the governing safety state.

## Engineering takeover / onboarding

**Start here:** [`docs/engineering_handoff/README.md`](docs/engineering_handoff/README.md)

The handoff pack contains the current-state matrix, architecture, operations runbook, point-in-time data/model lineage rules, manual gates, contribution standards, and prioritized open work. New engineers should use that folder as the concise system-of-record entry point rather than relying on historical chat context.

## Current merged capability areas

The repository includes substantial tested/traceable capability for:

- OVTLYR-style universe normalization, comparison, ranking, and opportunity workflows;
- deterministic risk and decision contracts;
- option/stock research and PAPER decision paths with explicit stale-data behavior;
- audited TradingView/Pine SH24 CONTROL and SH25 CHALLENGER source/parity contracts;
- paired SH24/SH25 evidence and proof gates;
- PAPER ledgers, shadow monitoring, diagnostics, and staging workflows;
- prospect V1 canonical opportunity-board presentation across Newsletter/Dashboard/API with real staging proof;
- leak-proof point-in-time training dataset assembly;
- deterministic ridge and logistic research baselines using TRAIN only, VALIDATION-only selection, and untouched TEST evaluation;
- post-TEST comparison against frozen SH24/SH25 controls;
- isolated Massive/Tiingo/FRED staging ingestion infrastructure;
- bounded manual historical feed capture that explicitly forbids historical `known_at` backdating;
- deterministic feed receipt/raw-byte lineage into point-in-time model feature evidence;
- GitHub Actions CI, deployment, diagnostics, backtests, proof, and monitoring workflows.

Code capability and empirical proof are intentionally separated. Fixture/synthetic regression success is not a predictive-alpha claim, and a historical payload captured today is not automatically historically point-in-time eligible.

## Repository layout

- `src/daily_alpha/` — core deterministic domain logic.
- `tests/` — regression/contract test suite.
- `lambda_handlers/` — main staging Lambda handlers.
- `staging_lambda_handlers/` — physically isolated staging-only services such as data-feed ingestion.
- `tradingview/` — frozen/audited Pine source and parity artifacts.
- `infra/` — AWS infrastructure, IAM, and bootstrap material.
- `scripts/` — build/render/validation utilities.
- `.github/workflows/` — CI, staging deployment/proof, PAPER monitoring, diagnostics, backtests, and manual evidence workflows.
- `docs/` — detailed subsystem documentation.
- `docs/engineering_handoff/` — concise takeover and operating documentation.

## Local setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
ruff check .
pytest -q
```

Validate a daily CSV:

```bash
daily-alpha path/to/ovtlyr.csv
```

## Data and secrets

- Put local daily files in `data/incoming/`; contents are ignored by Git.
- Generated research outputs belong in `data/output/`; contents are ignored by Git.
- Never commit provider tokens, brokerage/custodian credentials, account numbers, or private `.env` contents.
- Use environment variables or managed secret stores according to the relevant deployment/runbook contract.

## Current major evidence gates

1. Capture and ingest the unchanged external TradingView SH24/SH25 paired evidence required to complete parity classification.
2. Deploy/prove the isolated Phase 1 Massive/Tiingo/FRED staging ingestion stack if newer workflow evidence has not already cleared that gate.
3. Build a genuine historical point-in-time feature/label corpus with trustworthy historical availability/revision lineage.
4. Run the first genuine walk-forward ridge/logistic empirical evaluation and only then compare the untouched TEST result against frozen SH24/SH25.
5. Continue PAPER soak/reliability before any separate future live-capital governance discussion.

See [`docs/engineering_handoff/OPEN_WORK.md`](docs/engineering_handoff/OPEN_WORK.md) for the prioritized backlog.

## Disclaimer

This software is for research, staging, and PAPER trading. It does not itself provide authorization to place live trades or deploy capital.