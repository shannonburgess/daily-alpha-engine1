import json
from pathlib import Path

from scripts.render_data_feed_ingestion_template import render


TEMPLATE = Path("infra/aws/staging/data-feed-ingestion.template.json")
SOURCE = Path("lambda_handlers/data_feed_ingest.py")


def _template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_template_is_research_only_and_has_exact_phase1_schedules():
    template = _template()
    resources = template["Resources"]
    function = resources["DataFeedIngestionFunction"]["Properties"]
    assert function["FunctionName"] == "daily-alpha-staging-data-feed-ingestion"
    assert function["Environment"]["Variables"]["TRADING_AUTHORIZED"] == "false"
    assert function["Environment"]["Variables"]["LIVE_TRADING_ENABLED"] == "false"
    assert function["ReservedConcurrentExecutions"] == 2
    assert resources["MassiveSchedule"]["Properties"]["State"] == "ENABLED"
    assert resources["TiingoSchedule"]["Properties"]["State"] == "ENABLED"
    assert resources["FredSchedule"]["Properties"]["State"] == "ENABLED"
    assert "massive" in resources["MassiveSchedule"]["Properties"]["Targets"][0]["Input"]
    assert "tiingo" in resources["TiingoSchedule"]["Properties"]["Targets"][0]["Input"]
    assert "fred" in resources["FredSchedule"]["Properties"]["Targets"][0]["Input"]


def test_runtime_role_cannot_read_s3_or_touch_execution_services():
    template = _template()
    policies = template["Resources"]["DataFeedIngestionRole"]["Properties"]["Policies"]
    statements = policies[0]["PolicyDocument"]["Statement"]
    actions = {
        action
        for statement in statements
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    }
    assert actions == {
        "secretsmanager:GetSecretValue",
        "s3:PutObject",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
    }
    forbidden_prefixes = (
        "dynamodb:",
        "sqs:",
        "lambda:InvokeFunction",
        "events:",
        "states:",
        "iam:PassRole",
    )
    assert not any(action.startswith(forbidden_prefixes) for action in actions)
    resources = json.dumps(statements, sort_keys=True)
    for provider in ("massive", "tiingo", "fred"):
        assert f"daily-alpha/data-feeds/staging/{provider}-*" in resources
        assert f"data-feeds/staging/{provider}/*" in resources


def test_template_has_cloudwatch_success_failure_and_runtime_alarms():
    resources = _template()["Resources"]
    assert resources["IngestionSuccessMetric"]["Type"] == "AWS::Logs::MetricFilter"
    assert resources["IngestionFailureMetric"]["Type"] == "AWS::Logs::MetricFilter"
    assert resources["IngestionFailureAlarm"]["Type"] == "AWS::CloudWatch::Alarm"
    assert resources["IngestionLambdaErrorAlarm"]["Type"] == "AWS::CloudWatch::Alarm"
    assert resources["IngestionThrottleAlarm"]["Type"] == "AWS::CloudWatch::Alarm"


def test_renderer_injects_exact_repo_source(tmp_path):
    output = tmp_path / "rendered.json"
    render(template_path=TEMPLATE, source_path=SOURCE, output_path=output)
    rendered = json.loads(output.read_text(encoding="utf-8"))
    inline = rendered["Resources"]["DataFeedIngestionFunction"]["Properties"]["Code"]["ZipFile"]
    assert inline == SOURCE.read_text(encoding="utf-8")
    assert "__DATA_FEED_INGESTION_INLINE_CODE__" not in output.read_text(encoding="utf-8")
