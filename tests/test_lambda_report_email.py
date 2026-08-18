from types import SimpleNamespace

import lambda_handlers.report as report_handler
from daily_alpha.newsletter_delivery import NewsletterEmailDeliveryError


class _Publisher:
    def __init__(self, result=None):
        self.result = result or {
            "ok": True,
            "status": "PUBLISHED",
            "report_date": "2026-08-18",
            "session": "MORNING",
            "outputs": {
                "newsletter.html": "daily-alpha/outputs/latest/newsletter.html"
            },
            "live_trading_enabled": False,
        }

    def publish(self, **kwargs):
        assert kwargs["session"] == "MORNING"
        assert kwargs["run_id"] == "run-123"
        return dict(self.result)


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


def test_publish_automatically_emails_full_newsletter(monkeypatch):
    delivery = _Delivery()
    monkeypatch.setattr(report_handler, "AwsStagingReportPublisher", _Publisher)
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

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["email_delivery"]["status"] == "SENT"
    assert delivery.calls == [
        {
            "report_date": "2026-08-18",
            "session": "MORNING",
            "run_id": "run-123",
        }
    ]
    assert result["live_trading_enabled"] is False


def test_publish_remains_valid_while_email_configuration_is_not_set(monkeypatch):
    delivery = _Delivery(
        result={
            "status": "DISABLED",
            "reason": "NEWSLETTER_EMAIL_CONFIG_NOT_SET",
            "message_id": None,
            "recipient_count": 0,
            "run_id": "run-123",
        }
    )
    monkeypatch.setattr(report_handler, "AwsStagingReportPublisher", _Publisher)
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

    assert result["ok"] is True
    assert result["status"] == "PUBLISHED"
    assert result["email_delivery"]["status"] == "DISABLED"


def test_configured_email_failure_is_visible_after_publication(monkeypatch):
    delivery = _Delivery(
        error=NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_SES_SEND_FAILED")
    )
    monkeypatch.setattr(report_handler, "AwsStagingReportPublisher", _Publisher)
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
    assert result["status"] == "PUBLISHED_EMAIL_FAILED"
    assert result["error_code"] == "NEWSLETTER_EMAIL_SES_SEND_FAILED"
    assert result["publication"]["status"] == "PUBLISHED"
    assert result["live_trading_enabled"] is False


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
