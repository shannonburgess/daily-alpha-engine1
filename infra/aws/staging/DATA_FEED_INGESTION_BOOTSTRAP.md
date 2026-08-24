# Phase 1 staging data-feed ingestion bootstrap

This stack is intentionally separate from the already-proven 37-resource inert data-plane foundation. It adds one research-only Lambda, one dedicated runtime IAM role, three EventBridge schedules, one Lambda log group, CloudWatch metric filters, and three alarms for Massive, Tiingo, and FRED.

The three API secrets already live under:

- `daily-alpha/data-feeds/staging/massive`
- `daily-alpha/data-feeds/staging/tiingo`
- `daily-alpha/data-feeds/staging/fred`

No secret value belongs in GitHub, Lambda environment variables, CloudFormation parameters, logs, or receipts.

## Authority boundary

The ingestion Lambda can only:

1. read the three exact Secrets Manager secret families;
2. write immutable AES256 objects under the three exact S3 prefixes;
3. write its dedicated CloudWatch Logs stream.

It has no DynamoDB, SQS, Step Functions, EventBridge mutation, Lambda invoke, PAPER-ledger, broker, TradingView, capital, or live-trading permission. Every result and persisted receipt keeps `trading_authorized=false` and `live_trading_enabled=false`.

## One-time IAM bootstrap

The existing `DailyAlphaCloudFormationStagingRole` deliberately cannot create IAM/Lambda/EventBridge resources. Before the first deployment, an AWS administrator must attach the bounded extension in:

`infra/aws/staging/data-feed-ingestion-cloudformation-role-policy.json`

```bash
aws iam put-role-policy \
  --role-name DailyAlphaCloudFormationStagingRole \
  --policy-name DailyAlphaStagingDataFeedIngestion \
  --policy-document file://infra/aws/staging/data-feed-ingestion-cloudformation-role-policy.json
```

The GitHub OIDC caller must also receive only the bounded stack-control/proof policy in:

`infra/aws/staging/data-feed-ingestion-github-deploy-policy.json`

```bash
aws iam put-role-policy \
  --role-name DailyAlphaGitHubStagingDeployRole \
  --policy-name DailyAlphaStagingDataFeedIngestionDeploy \
  --policy-document file://infra/aws/staging/data-feed-ingestion-github-deploy-policy.json
```

That GitHub policy now includes one additional proof-only permission: `s3:GetObject` is scoped to the exact staging FRED evidence prefix under `daily-alpha-staging-raw-490809405132-us-east-2`. It does not grant bucket listing, object writes, deletes, or reads of Massive/Tiingo evidence. The narrow read exists only so a manual FRED proof run can rehydrate the exact immutable raw object and receipt after capture and validate them through the repository's provider-specific point-in-time parser.

Do not copy Lambda/IAM/EventBridge resource-management permissions into the GitHub caller. CloudFormation remains the resource creator through the existing service-conditioned `iam:PassRole` boundary.

## Deployment and proof

After both bounded policies are installed, manually run:

`.github/workflows/deploy-staging-data-feed-ingestion.yml`

The workflow runs Ruff + pytest, injects the exact repo Lambda source into the CloudFormation template, validates/deploys the isolated stack, verifies the function role/environment, proves all three EventBridge rules are enabled, invokes Massive/Tiingo/FRED, requires research-only receipts, finds CloudWatch success records for all three providers, and verifies the failure/error/throttle alarms exist.

After the updated ingestion Lambda is deployed and its smoke contract advertises `fred_historical_output_type=4`, the real FRED point-in-time evidence proof is a separate manual action:

`.github/workflows/prove-fred-initial-release-staging.yml`

The proof workflow is intentionally FRED-only and manual. It requires `PROVE_FRED`, exact authoritative `main`, a bounded 31-day observation window, and the staging environment. Before any provider call it verifies the deployed Lambda configuration and smoke contract. It then invokes one historical FRED capture, re-reads the exact raw object and transport receipt from S3, validates those bytes with `parse_fred_initial_release_history`, and emits a sanitized `DAILY_ALPHA_FRED_INITIAL_RELEASE_STAGING_PROOF_V1` artifact bound to the repo commit and deployed Lambda `CodeSha256`.

A successful proof establishes only that the captured staging evidence satisfies the `FRED_OUTPUT_TYPE_4_INITIAL_RELEASE_V1` historical-availability contract. It does not establish predictive alpha, model promotion, PAPER readiness, execution authority, or live trading.

The schedules are intentionally low-volume staging canaries:

- Massive: weekdays at `22:20 UTC`, SPY + DINO;
- Tiingo: weekdays at `22:35 UTC`, SPY + DINO;
- FRED: weekdays at `14:05 UTC`, DFF + DGS10 + VIXCLS.

These schedules populate isolated research evidence only. They do not feed PAPER or live execution.
