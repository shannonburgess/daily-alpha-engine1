# GitHub staging proof-reader policy

The canonical AWS staging workflow deploys the inert 37-resource data-plane foundation with the dedicated CloudFormation execution role `DailyAlphaCloudFormationStagingRole`, while the GitHub OIDC caller remains `DailyAlphaGitHubStagingDeployRole`.

After CloudFormation deployment succeeds, the GitHub caller performs read-only proof checks. The authoritative policy for those checks is:

`infra/aws/staging/github-staging-proof-reader-policy.json`

It grants only the reads already exercised by `.github/workflows/deploy-aws-staging-data-plane-foundation.yml`:

- CloudFormation stack status, failure diagnostics, and exact resource inventory;
- S3 encryption, public-access-block, versioning, and bucket-policy reads for the staging raw-evidence bucket;
- DynamoDB point-in-time-recovery status reads for the two staging state tables.

It grants no create, update, delete, tag, object write, table item write, queue message, IAM, STS, broker, PAPER, TradingView, production, or live-trading authority.

## Apply once

From an authorized AWS administrative shell:

```bash
aws iam put-role-policy \
  --role-name DailyAlphaGitHubStagingDeployRole \
  --policy-name DailyAlphaStagingPostDeployProofReader \
  --policy-document file://infra/aws/staging/github-staging-proof-reader-policy.json
```

If running outside a repository checkout, copy the exact JSON from approved `main` before applying it. Do not replace it with a broader managed policy.

The foundation is `STAGING_PROVEN` only when the canonical workflow is green and proves the exact 37-resource inventory, S3 controls/policy, DynamoDB PITR, and zero activation resources while `trading_authorized=false` and `live_trading_enabled=false` remain unchanged.
