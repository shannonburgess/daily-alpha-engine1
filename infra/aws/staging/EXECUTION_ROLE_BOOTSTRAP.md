# Daily Alpha staging CloudFormation execution-role bootstrap

This is the bounded bootstrap contract for the dedicated service role `DailyAlphaCloudFormationStagingRole` used by CloudFormation to create the inert staging data-plane foundation.

The authoritative policy document is:

`infra/aws/staging/cloudformation-execution-role-policy.json`

The policy intentionally covers the full create/read/stabilize/update/rollback lifecycle for only the resource types present in `data-plane-foundation.template.json`:

- one S3 raw-evidence bucket and its bucket policy;
- two DynamoDB state tables, including TTL and point-in-time recovery;
- 32 staging SQS queues/DLQs;
- one bounded CloudWatch Logs log group.

It deliberately grants no Lambda, EventBridge, Scheduler, Step Functions, API Gateway, Secrets Manager, KMS administration, IAM, broker, PAPER mutation, object-write, queue-send, table-item-write, TradingView or live-trading authority. The only wildcard resource is `logs:DescribeLogGroups`, an AWS Logs read/list action that does not support the same resource-level scoping as mutations; all mutating permissions remain scoped to the exact staging resources.

The GitHub OIDC caller role `DailyAlphaGitHubStagingDeployRole` remains separate. It needs CloudFormation control-plane permissions plus the already-approved service-conditioned `iam:PassRole` for exactly `DailyAlphaCloudFormationStagingRole`; it must not receive the resource-creation permissions in this policy.

## Apply the complete policy once

From an authorized AWS administrative shell, apply the repo policy as one inline policy rather than adding permissions reactively one error at a time:

```bash
aws iam put-role-policy \
  --role-name DailyAlphaCloudFormationStagingRole \
  --policy-name DailyAlphaStagingDataPlaneFoundation \
  --policy-document file://infra/aws/staging/cloudformation-execution-role-policy.json
```

If the command is being run outside a checkout of this repository, copy the exact JSON from the authoritative `main`/approved PR before applying it. Do not hand-edit a broader replacement.

## Recovery after a failed create

A failed create may leave the stack in `ROLLBACK_COMPLETE` or `ROLLBACK_FAILED`. Because the raw-evidence bucket has `DeletionPolicy: Retain`, cleanup must preserve evidence and only remove that retained bucket if an explicit emptiness check proves there are no current objects, prior versions, delete markers or multipart uploads.

After the service-role policy is corrected and the failed stack is clean, rerun the unchanged canonical workflow `.github/workflows/deploy-aws-staging-data-plane-foundation.yml` from exact authoritative `main`.

The foundation is **STAGING_PROVEN** only when the workflow itself is green and the post-deploy gates prove:

1. exact 37-resource inventory;
2. S3 encryption, public-access block, versioning and TLS-deny policy;
3. point-in-time recovery enabled for both DynamoDB tables;
4. zero activation resources;
5. `trading_authorized=false` and `live_trading_enabled=false` remain unchanged.
