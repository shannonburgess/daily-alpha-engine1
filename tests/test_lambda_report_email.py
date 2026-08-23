from types import SimpleNamespace
from typing import ClassVar

import lambda_handlers.report as report_handler
from daily_alpha.newsletter_delivery import NewsletterEmailDeliveryError
from daily_alpha.prospect_staging_runtime import ProspectStagingRuntimeError


class _Publisher:
    def __init__(self, result=None):
        self.s3 = object()
        self.bucket = "unit-bucket"
        self.result = result or {
            "ok": True,
            "status": "PUBLISHED",
            "report_date": "2026-08-18",
            "session": "MORNING",
            "history_prefix": "daily-alpha/outputs/history/2026-08-18/morning-run",
            "outputs": {
                "newsletter.html": "daily-alpha/outputs/latest/newsletter.html"
            },
            "live_trading_enabled": False,
        }

    def publish(self, **kwargs):
        assert kwargs["session"] == "MORNING"
        assert kwargs["run_id"] == "run-123"
        return dict(self.result)


class _Prepared:
    def summary(self):
        return {
            "board_id": "board-1",
            "total_qualifying": 50,
            "top_pick_symbols": ["AAA", "BBB", "CCC"],
            "additional_qualifying_count": 47,
            "filtered_count": 2,
            "verified_channels": ["NEWSLETTER", "DASHBOARD", "API"],
            "trading_authorized": False,
            "live_trading_enabled": False,
        }


class _Gate:
    def __init__(self, validated: bool):
        self.delivery_contract_validated = validated
        self.reasons = () if validated else ("NEWSLETTER_DELIVERY_CONTRACT_NOT_VALIDATED",)
        self.trading_authorized = False
        self.live_trading_enabled = False

    @property
    def ready(self):
        return not self.reasons


class _ProspectRuntime:
    instances: ClassVar[list["_ProspectRuntime"]] = []

    def __init__(self, *, s3_client, bucket):
        assert s3_client is not None
        assert bucket == "unit-bucket"
        self.prepare_calls = []
        self.finalize_calls = []
        self.__class__.instances.append(self)

    def prepare(self, **kwargs):
        assert kwargs["history_prefix"] == (
            "daily-alpha/outputs/history/2026-08-18/morning-run"
        )
        assert kwargs["as_of"].tzinfo is not None
        self.prepare_calls.append(kwargs)
        return _Prepared()

    def finalize_delivery(self, prepared, *, delivery_contract_validated):
        assert isinstance(prepared, _Prepared)
        self.finalize_calls.append(delivery_contract_validated)
        return _Gate(delivery_contract_validated)


class _Delivery:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "status": "SENT",
            "reason": "SES_ACCEPTED",
            "message_id": "message-1",
            "recipient_count": 1,
            "run_id": "run-123",
        }
        self.error = error
        self.calls = []

    def send_latest(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return dict(self.result)


def _context():
    return SimpleNamespace(aws_request_id="request-1")


def _patch_publish_path(monkeypatch, delivery, *, prospect_enabled: bool = True):
    _ProspectRuntime.instances.clear()
    if prospect_enabled:
        monkeypatch.setenv("DAILY_ALPHA_PROSPECT_V1_RUNTIME_ENABLED", "true")
    else:
        monkeypatch.delenv("DAILY_ALPHA_PROSPECT_V1_RUNTIME_ENABLED", raising=False)
    monkeypatch.setattr(report_handler, "AwsStagingReportPublisher", _Publisher)
    monkeypatch.setattr(
        report_handler,
        "AwsProspectStagingRuntimePublisher",
        _ProspectRuntime,
    )
    monkeypatch.setattr(
        report_handler,
        "AwsNewsletterEmailDelivery",
        lambda: delivery,
    )


def test_publish_keeps_prospect_runtime_disabled_by_default(monkeypatch):
    delivery = _Delivery()
    _patch_publish_path(monkeypatch, delivery, prospect_enabled=False)

    result = report_handler.lambda_handler(
        {
            "operation": "PUBLISH_STAGING_REPORT",
            "session": "MORNING",
            "run_id": "run-123",
        },
        _context(),
    )

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["email_delivery"]["status"] == "SENT"
    assert result["prospect_v1_runtime_enabled"] is False
    assert result["prospect_initial_rollout"]["ready"] is False
    assert result["prospect_initial_rollout"]["reasons"] == [
        "PROSPECT_V1_RUNTIME_DISABLED"
    ]
    assert result["prospect_initial_rollout"]["trading_authorized"] is False
    assert result["prospect_initial_rollout"]["live_trading_enabled"] is False
    assert _ProspectRuntime.instances == []
    assert len(delivery.calls) == 1


def test_publish_automatically_emails_full_newsletter_after_prospect_gate_prepare(
    monkeypatch,
):
    delivery = _Delivery()
    _patch_publish_path(monkeypatch, delivery)

    result = report_handler.lambda_handler(
        {
            "operation": "PUBLISH_STAGING_REPORT",
            "session": "MORNING",
            "run_id": "run-123",
        },
        _context(),
    )

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["email_delivery"]["status"] == "SENT"
    assert result["prospect_v1_runtime_enabled"] is True
    assert result["prospect_initial_rollout"]["ready"] is True
    assert result["prospect_initial_rollout"]["total_qualifying"] == 50
    assert result["prospect_initial_rollout"]["additional_qualifying_count"] == 47
    assert _ProspectRuntime.instances[0].finalize_calls == [True]
    assert delivery.calls == [
        {
            "report_date": "2026-08-18",
            "session": "MORNING",
            "run_id": "run-123",
        }
    ]
    assert result["live_trading_enabled"] is False


def test_publish_remains_valid_but_v1_gate_closed_when_email_config_not_set(monkeypatch):
    delivery = _Delivery(
        result={
            "status": "DISABLED",
            "reason": "NEWSLETTER_EMAIL_CONFIG_NOT_SET",
            "message_id": None,
            "recipient_count": 0,
            "run_id": "run-123",
        }
    )
    _patch_publish_path(monkeypatch, delivery)

    result = report_handler.lambda_handler(
        {
            "operation": "PUBLISH_STAGING_REPORT",
            "session": "MORNING",
            "run_id": "run-123",
        },
        _context(),
    )

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["email_delivery"]["status"] == "DISABLED"
    assert result["prospect_initial_rollout"]["ready"] is False
    assert "NEWSLETTER_DELIVERY_CONTRACT_NOT_VALIDATED" in result[
        "prospect_initial_rollout"
    ]["reasons"]
    assert _ProspectRuntime.instances[0].finalize_calls == [False]


def test_configured_email_failure_is_visible_and_keeps_v1_gate_closed(monkeypatch):
    delivery = _Delivery(
        error=NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_SES_SEND_FAILED")
    )
    _patch_publish_path(monkeypatch, delivery)

    result = report_handler.lambda_handler(
        {
            "operation": "PUBLISH_STAGING_REPORT",
            "session": "MORNING",
            "run_id": "run-123",
        },
        _context(),
    )

    assert result["ok"] is False
    assert result["status"] == "PUBLISHED_EMAIL_FAILED"
    assert result["error_code"] == "NEWSLETTER_EMAIL_SES_SEND_FAILED"
    assert result["publication"]["status"] == "PUBLISHED"
    assert result["prospect_initial_rollout"]["ready"] is False
    assert _ProspectRuntime.instances[0].finalize_calls == [False]
    assert result["live_trading_enabled"] is False


def test_prospect_prepare_failure_prevents_initial_rollout_email(monkeypatch):
    delivery = _Delivery()

    class _BrokenProspectRuntime(_ProspectRuntime):
        def prepare(self, **kwargs):
            raise ProspectStagingRuntimeError("PROSPECT_SHORTLIST_JSON_INVALID")

    monkeypatch.setenv("DAILY_ALPHA_PROSPECT_V1_RUNTIME_ENABLED", "true")
    monkeypatch.setattr(report_handler, "AwsStagingReportPublisher", _Publisher)
    monkeypatch.setattr(
        report_handler,
        "AwsProspectStagingRuntimePublisher",
        _BrokenProspectRuntime,
    )
    monkeypatch.setattr(
        report_handler,
        "AwsNewsletterEmailDelivery",
        lambda: delivery,
    )

    result = report_handler.lambda_handler(
        {
            "operation": "PUBLISH_STAGING_REPORT",
            "session": "MORNING",
            "run_id": "run-123",
        },
        _context(),
    )

    assert result["ok"] is False
    assert result["status"] == "PUBLISHED_PROSPECT_FAILED"
    assert result["error_code"] == "PROSPECT_SHORTLIST_JSON_INVALID"
    assert result["prospect_initial_rollout"]["ready"] is False
    assert delivery.calls == []


def test_send_latest_newsletter_resends_without_republishing(monkeypatch):
    delivery = _Delivery()

    class _PublisherMustNotRun:
        def __init__(self):
            raise AssertionError("publisher must not run for resend")

    monkeypatch.setattr(
        report_handler,
        "AwsStagingReportPublisher",
        _PublisherMustNotRun,
    )
    monkeypatch.setattr(
        report_handler,
        "AwsNewsletterEmailDelivery",
        lambda: delivery,
    )

    result = report_handler.lambda_handler(
        {
            "operation": "SEND_LATEST_NEWSLETTER",
            "report_date": "2026-08-18",
            "session": "MORNING",
            "run_id": "run-123",
        },
        _context(),
    )

    assert result["ok"] is True
    assert result["status"] == "EMAIL_SENT"
    assert result["email_delivery"]["message_id"] == "message-1"


def test_send_latest_reports_disabled_configuration_as_failure(monkeypatch):
    delivery = _Delivery(
        result={
            "status": "DISABLED",
            "reason": "NEWSLETTER_EMAIL_CONFIG_NOT_SET",
            "message_id": None,
            "recipient_count": 0,
            "run_id": "run-123",
        }
    )
    monkeypatch.setattr(
        report_handler,
        "AwsNewsletterEmailDelivery",
        lambda: delivery,
    )

    result = report_handler.lambda_handler(
        {"operation": "SEND_LATEST_NEWSLETTER", "run_id": "run-123"},
        _context(),
    )

    assert result["ok"] is False
    assert result["status"] == "EMAIL_DISABLED"
    assert result["error_code"] == "NEWSLETTER_EMAIL_CONFIG_NOT_SET"
