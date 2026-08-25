# Daily Alpha Lambda production-candidate gate

## Recovered deployment evidence

The three AWS packages recovered on 2026-08-24 were byte-for-byte identical:

- `daily-alpha-engine.zip`
- `daily-alpha-report.zip`
- `daily-alpha-paper-trader.zip`
- SHA-256: `7b3694486ff5f4522f981603e8a8a7f4d6ace9b9301170825c4a06920c998617`

This is consistent with the current shared-package deployment model. One package contains the
Daily Alpha library plus every Lambda handler, while each AWS function selects its own configured
entry point:

| Function | Handler |
| --- | --- |
| `daily-alpha-engine` | `lambda_handlers.engine.lambda_handler` |
| `daily-alpha-report` | `lambda_handlers.report.lambda_handler` |
| `daily-alpha-paper-trader` | `lambda_handlers.paper_trader.lambda_handler` |
| `daily-alpha-pine-ingress` | `lambda_handlers.pine_webhook.lambda_handler` |
| `daily-alpha-pine-processor` | `lambda_handlers.pine_processor.lambda_handler` |

The recovered handler sources match the repository handler sources. The recovered ZIPs also
contained duplicate build trees and Python bytecode, so they are evidence artifacts rather than
canonical source and must not be committed or redeployed directly.

## Candidate build

`.github/workflows/build-production-lambda-candidate.yml` creates a clean, reviewable package:

1. runs Ruff and the complete pytest suite;
2. builds with the production-compatible Python runtime;
3. removes bytecode and rejects duplicate package trees;
4. imports all five configured handlers from the finished ZIP layout;
5. publishes the ZIP, complete file listing, commit SHA, package SHA-256, and safety manifest.

The workflow has read-only repository permission. It requests no AWS credential and performs no
deployment.

## Gates before any future production deployment

A separate deployment workflow remains blocked until all of these are explicitly established:

1. protected GitHub `production` environment with required human approval;
2. dedicated production OIDC role and least-privilege Lambda permissions;
3. immutable Lambda version publication and alias-based promotion;
4. pre-deployment configuration snapshot and documented rollback target;
5. post-deployment smoke checks for every handler;
6. continued `trading_authorized=false` and `live_trading_enabled=false` unless a separate
   governance process explicitly changes those controls.

A successful candidate build proves package integrity only. It does not authorize AWS deployment,
PAPER fills, brokerage routing, capital deployment, or live trading.
