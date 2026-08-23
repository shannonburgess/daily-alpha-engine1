import json
from pathlib import Path

POLICY_PATH = Path("infra/aws/staging/github-staging-proof-reader-policy.json")


def _policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_github_staging_proof_reader_is_read_only_and_bounded():
    policy = _policy()
    assert policy["Version"] == "2012-10-17"
    statements = policy["Statement"]
    assert len(statements) == 3

    allowed_prefixes = (
        "cloudformation:Describe",
        "cloudformation:List",
        "s3:Get",
        "dynamodb:Describe",
    )
    for statement in statements:
        actions = statement["Action"]
        if isinstance(actions, str):
            actions = [actions]
        assert all(action.startswith(allowed_prefixes) for action in actions)
        resources = statement["Resource"]
        if isinstance(resources, str):
            resources = [resources]
        assert "*" not in resources
        assert all(
            "daily-alpha-staging-" in resource
            or "daily-alpha-staging-data-plane-foundation" in resource
            for resource in resources
        )


def test_github_staging_proof_reader_covers_workflow_postdeploy_reads():
    statements = {statement["Sid"]: statement for statement in _policy()["Statement"]}

    cfn_actions = set(statements["ReadDailyAlphaStagingStackProof"]["Action"])
    assert {
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:ListStackResources",
    } <= cfn_actions

    s3_actions = set(statements["ReadDailyAlphaStagingRawEvidenceControls"]["Action"])
    assert {
        "s3:GetEncryptionConfiguration",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketVersioning",
        "s3:GetBucketPolicy",
    } <= s3_actions

    dynamodb_action = statements["ReadDailyAlphaStagingTableRecoveryControls"]["Action"]
    assert dynamodb_action == "dynamodb:DescribeContinuousBackups"


def test_github_staging_proof_reader_grants_no_mutation_authority():
    mutation_verbs = (
        "Create",
        "Put",
        "Update",
        "Delete",
        "Set",
        "Tag",
        "Untag",
        "Send",
        "Write",
        "PassRole",
        "AssumeRole",
    )
    actions = []
    for statement in _policy()["Statement"]:
        value = statement["Action"]
        actions.extend([value] if isinstance(value, str) else value)

    assert all(not any(verb in action for verb in mutation_verbs) for action in actions)
    assert all(not action.startswith("iam:") for action in actions)
    assert all(not action.startswith("sts:") for action in actions)
