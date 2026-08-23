import json
from pathlib import Path


POLICY_PATH = Path("infra/aws/staging/cloudformation-execution-role-policy.json")


def _policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_execution_role_policy_is_staging_bounded():
    policy = _policy()
    assert policy["Version"] == "2012-10-17"
    statements = policy["Statement"]
    assert len(statements) == 5

    forbidden_action_prefixes = (
        "iam:",
        "lambda:",
        "events:",
        "scheduler:",
        "states:",
        "apigateway:",
        "secretsmanager:",
        "kms:",
    )
    for statement in statements:
        actions = statement["Action"]
        if isinstance(actions, str):
            actions = [actions]
        assert all(
            not action.lower().startswith(forbidden_action_prefixes)
            for action in actions
        )
        resources = statement["Resource"]
        if isinstance(resources, str):
            resources = [resources]
        if statement["Sid"] != "DescribeDailyAlphaStagingLogGroups":
            assert "*" not in resources
            assert all("daily-alpha-staging-" in resource or "/daily-alpha/staging/data-plane" in resource for resource in resources)


def test_execution_role_policy_covers_cloudformation_resource_lifecycle():
    statements = {statement["Sid"]: statement for statement in _policy()["Statement"]}

    s3_actions = set(statements["ManageDailyAlphaStagingRawEvidenceBucket"]["Action"])
    assert {
        "s3:CreateBucket",
        "s3:GetEncryptionConfiguration",
        "s3:PutEncryptionConfiguration",
        "s3:GetBucketOwnershipControls",
        "s3:PutBucketOwnershipControls",
        "s3:GetBucketPublicAccessBlock",
        "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketVersioning",
        "s3:PutBucketVersioning",
        "s3:GetLifecycleConfiguration",
        "s3:PutLifecycleConfiguration",
        "s3:GetBucketTagging",
        "s3:PutBucketTagging",
        "s3:GetBucketPolicy",
        "s3:PutBucketPolicy",
        "s3:DeleteBucketPolicy",
    } <= s3_actions

    dynamodb_actions = set(statements["ManageDailyAlphaStagingStateTables"]["Action"])
    assert {
        "dynamodb:CreateTable",
        "dynamodb:DescribeTable",
        "dynamodb:DeleteTable",
        "dynamodb:TagResource",
        "dynamodb:ListTagsOfResource",
        "dynamodb:DescribeTimeToLive",
        "dynamodb:UpdateTimeToLive",
        "dynamodb:DescribeContinuousBackups",
        "dynamodb:UpdateContinuousBackups",
    } <= dynamodb_actions

    sqs_actions = set(statements["ManageDailyAlphaStagingQueues"]["Action"])
    assert {
        "sqs:CreateQueue",
        "sqs:GetQueueAttributes",
        "sqs:SetQueueAttributes",
        "sqs:DeleteQueue",
        "sqs:TagQueue",
        "sqs:ListQueueTags",
    } <= sqs_actions

    logs_actions = set(statements["ManageDailyAlphaStagingDataPlaneLogGroup"]["Action"])
    assert {
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:PutRetentionPolicy",
        "logs:TagResource",
    } <= logs_actions


def test_execution_role_policy_preserves_inert_authority_boundary():
    actions = []
    for statement in _policy()["Statement"]:
        value = statement["Action"]
        actions.extend([value] if isinstance(value, str) else value)
    assert "iam:PassRole" not in actions
    assert all("PutObject" not in action for action in actions)
    assert all("SendMessage" not in action for action in actions)
    assert all("PutItem" not in action for action in actions)
