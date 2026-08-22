from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config" / "aws_staging_agent_domains.json"
TEMPLATE_PATH = ROOT / "infra" / "aws" / "staging" / "data-plane-foundation.template.json"

EXPECTED_SERVICES = {
    "reference-identity",
    "sec-intelligence",
    "macro",
    "market-structure-primary",
    "market-verification",
    "fundamental",
    "estimate-revision",
    "news-catalyst",
    "sector-rotation",
    "liquidity-capacity",
    "pine-signal-evidence",
    "earnings-event-risk",
    "behavioral-attention",
    "institutional-flow",
    "model-performance",
    "data-reliability-supervisor",
}

ALLOWED_LOGICAL_SECRETS = {
    None,
    "FRED_API_KEY",
    "MASSIVE_API_KEY",
    "DATABENTO_API_KEY",
    "FMP_API_KEY",
    "BENZINGA_API_KEY",
}

ACTIVATION_RESOURCE_TYPES = {
    "AWS::Lambda::Function",
    "AWS::Events::Rule",
    "AWS::Scheduler::Schedule",
    "AWS::StepFunctions::StateMachine",
    "AWS::ApiGateway::RestApi",
    "AWS::ApiGatewayV2::Api",
    "AWS::SecretsManager::Secret",
    "AWS::IAM::Role",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _tag_map(resource: dict) -> dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in resource["Properties"].get("Tags", [])}


def test_agent_domain_manifest_is_independent_research_only_and_secret_safe() -> None:
    manifest = _load(MANIFEST_PATH)

    assert manifest["schema_version"] == "1.0"
    assert manifest["environment"] == "staging"
    assert manifest["authority"] == {
        "research_only": True,
        "paper_ledger_mutation_authorized": False,
        "portfolio_construction_authorized": False,
        "execution_authorized": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }

    domains = manifest["domains"]
    assert {domain["service_name"] for domain in domains} == EXPECTED_SERVICES
    assert len({domain["agent_id"] for domain in domains}) == len(domains)
    assert len({domain["queue_name"] for domain in domains}) == len(domains)
    assert len({domain["dlq_name"] for domain in domains}) == len(domains)
    assert len({domain["raw_prefix"] for domain in domains}) == len(domains)

    for domain in domains:
        service = domain["service_name"]
        assert domain["queue_name"] == f"daily-alpha-staging-{service}"
        assert domain["dlq_name"] == f"daily-alpha-staging-{service}-dlq"
        assert domain["raw_prefix"] == f"raw/{service}/"
        assert domain["logical_secret_name"] in ALLOWED_LOGICAL_SECRETS
        assert domain["research_only"] is True
        assert domain["paper_ledger_mutation_authorized"] is False
        assert domain["execution_authorized"] is False
        assert domain["trading_authorized"] is False
        assert domain["live_trading_enabled"] is False


def test_iac_foundation_is_staging_only_inert_and_encrypted() -> None:
    template = _load(TEMPLATE_PATH)
    resources = template["Resources"]

    assert template["Parameters"]["Environment"]["AllowedValues"] == ["staging"]
    resource_types = {resource["Type"] for resource in resources.values()}
    assert not resource_types.intersection(ACTIVATION_RESOURCE_TYPES)
    assert resource_types <= {
        "AWS::S3::Bucket",
        "AWS::DynamoDB::Table",
        "AWS::Logs::LogGroup",
        "AWS::SQS::Queue",
    }

    bucket = resources["RawEvidenceBucket"]["Properties"]
    assert bucket["VersioningConfiguration"]["Status"] == "Enabled"
    assert bucket["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    encryption = bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"]
    assert encryption == [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
    assert bucket["OwnershipControls"]["Rules"] == [{"ObjectOwnership": "BucketOwnerEnforced"}]

    for table_name in ("IdempotencyTable", "CurrentStateTable"):
        table = resources[table_name]["Properties"]
        assert table["BillingMode"] == "PAY_PER_REQUEST"
        assert table["SSESpecification"]["SSEEnabled"] is True
        assert table["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
        assert table["TimeToLiveSpecification"]["Enabled"] is True
        assert _tag_map(resources[table_name])["Authority"] == "ResearchOnly"

    log_group = resources["DataPlaneLogGroup"]
    assert log_group["Properties"]["RetentionInDays"] == 30
    assert _tag_map(log_group)["Authority"] == "ResearchOnly"


def test_every_agent_has_one_encrypted_queue_and_dlq_with_redrive() -> None:
    manifest = _load(MANIFEST_PATH)
    resources = _load(TEMPLATE_PATH)["Resources"]
    queues = {
        resource["Properties"]["QueueName"]: (logical_id, resource)
        for logical_id, resource in resources.items()
        if resource["Type"] == "AWS::SQS::Queue"
    }

    assert len(queues) == len(manifest["domains"]) * 2

    for domain in manifest["domains"]:
        queue_name = domain["queue_name"]
        dlq_name = domain["dlq_name"]
        assert queue_name in queues
        assert dlq_name in queues

        dlq_logical_id, dlq = queues[dlq_name]
        queue_logical_id, queue = queues[queue_name]
        assert queue_logical_id != dlq_logical_id
        assert dlq["Properties"]["SqsManagedSseEnabled"] is True
        assert queue["Properties"]["SqsManagedSseEnabled"] is True
        assert "RedrivePolicy" not in dlq["Properties"]
        assert queue["Properties"]["RedrivePolicy"] == {
            "deadLetterTargetArn": {"Fn::GetAtt": [dlq_logical_id, "Arn"]},
            "maxReceiveCount": 5,
        }
        assert _tag_map(queue)["Agent"] == domain["service_name"]
        assert _tag_map(dlq)["Agent"] == domain["service_name"]
        assert _tag_map(queue)["Authority"] == "ResearchOnly"
        assert _tag_map(dlq)["Authority"] == "ResearchOnly"


def test_iac_does_not_contain_secret_values_or_trading_authority() -> None:
    combined = f"{MANIFEST_PATH.read_text(encoding='utf-8')}\n{TEMPLATE_PATH.read_text(encoding='utf-8')}"
    lowered = combined.lower()

    assert '"trading_authorized": true' not in lowered
    assert '"live_trading_enabled": true' not in lowered
    assert '"execution_authorized": true' not in lowered
    assert "broker" not in TEMPLATE_PATH.read_text(encoding="utf-8").lower()
    assert "authorization:" not in lowered
    assert "bearer " not in lowered
