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

Do not copy Lambda/IAM/EventBridge resource-management permissions into the GitHub caller. CloudFormation remains the resource creator through the existing service-conditioned `iam:PassRole` boundary.

## Deployment and proof

After both bounded policies are installed, manually run:

`.github/workflows/deploy-staging-data-feed-ingestion.yml`

The workflow runs Ruff + pytest, injects the exact repo Lambda source into the CloudFormation template, validates/deploys the isolated stack, verifies the function role/environment, proves all three EventBridge rules are enabled, invokes Massive/Tiingo/FRED, requires research-only receipts, finds CloudWatch success records for all three providers, and verifies the failure/error/throttle alarms exist.

The schedules are intentionally low-volume staging canaries:

- Massive: weekdays at `22:20 UTC`, SPY + DINO;
- Tiingo: weekdays at `22:35 UTC`, SPY + DINO;
- FRED: weekdays at `14:05 UTC`, DFF + DGS10 + VIXCLS.

These schedules populate isolated research evidence only. They do not feed PAPER or live execution.
