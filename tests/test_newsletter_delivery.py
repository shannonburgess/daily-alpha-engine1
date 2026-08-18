import pytest

from daily_alpha.newsletter_delivery import (
    AwsNewsletterEmailDelivery,
    NewsletterEmailConfig,
    NewsletterEmailDeliveryError,
)


class _Body:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class _FakeS3:
    def __init__(self, html):
        self.html = html
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"Body": _Body(self.html.encode("utf-8"))}


class _FakeSesV2:
    def __init__(self, *, fail=False, response=None):
        self.fail = fail
        self.response = response or {"MessageId": "ses-message-123"}
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("SES unavailable")
        return self.response


def _config():
    return NewsletterEmailConfig(
        sender="sender@example.com",
        recipients=("reader@example.com",),
        region="us-east-2",
    )


def test_send_latest_uses_exact_published_html_as_email_body():
    html = "<!doctype html><html><body><h1>Daily Alpha &amp; Risk</h1><p>FULL</p></body></html>"
    s3 = _FakeS3(html)
    ses = _FakeSesV2()
    delivery = AwsNewsletterEmailDelivery(
        config=_config(),
        s3_client=s3,
        sesv2_client=ses,
        bucket="unit-bucket",
    )

    result = delivery.send_latest(
        report_date="2026-08-18",
        session="MORNING",
        run_id="run-1",
    )

    assert result["status"] == "SENT"
    assert result["message_id"] == "ses-message-123"
    assert result["recipient_count"] == 1
    assert s3.calls == [
        {
            "Bucket": "unit-bucket",
            "Key": "daily-alpha/outputs/latest/newsletter.html",
        }
    ]
    sent = ses.calls[0]
    assert sent["FromEmailAddress"] == "sender@example.com"
    assert sent["Destination"] == {"ToAddresses": ["reader@example.com"]}
    assert sent["Content"]["Simple"]["Body"]["Html"]["Data"] == html
    assert sent["Content"]["Simple"]["Subject"]["Data"] == (
        "Daily Alpha & Risk — 2026-08-18 — Morning"
    )


def test_delivery_is_explicitly_disabled_when_email_config_is_absent():
    delivery = AwsNewsletterEmailDelivery(
        config=NewsletterEmailConfig(),
        bucket="unit-bucket",
    )

    result = delivery.send_latest(
        report_date="2026-08-18",
        session="MORNING",
        run_id="run-2",
    )

    assert result["status"] == "DISABLED"
    assert result["reason"] == "NEWSLETTER_EMAIL_CONFIG_NOT_SET"
    assert result["recipient_count"] == 0


def test_environment_rejects_partial_email_configuration(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_NEWSLETTER_EMAIL_TO", "reader@example.com")
    monkeypatch.delenv("DAILY_ALPHA_NEWSLETTER_EMAIL_FROM", raising=False)

    with pytest.raises(NewsletterEmailDeliveryError) as error:
        NewsletterEmailConfig.from_environment()

    assert error.value.code == "NEWSLETTER_EMAIL_CONFIG_INCOMPLETE"


def test_invalid_html_is_never_sent():
    delivery = AwsNewsletterEmailDelivery(
        config=_config(),
        s3_client=_FakeS3("not html"),
        sesv2_client=_FakeSesV2(),
        bucket="unit-bucket",
    )

    with pytest.raises(NewsletterEmailDeliveryError) as error:
        delivery.send_latest(
            report_date="2026-08-18",
            session="MORNING",
            run_id="run-3",
        )

    assert error.value.code == "NEWSLETTER_EMAIL_HTML_VALIDATION_FAILED"


def test_ses_failure_is_not_reported_as_success():
    html = "<!doctype html><html><body>Daily Alpha newsletter</body></html>"
    delivery = AwsNewsletterEmailDelivery(
        config=_config(),
        s3_client=_FakeS3(html),
        sesv2_client=_FakeSesV2(fail=True),
        bucket="unit-bucket",
    )

    with pytest.raises(NewsletterEmailDeliveryError) as error:
        delivery.send_latest(
            report_date="2026-08-18",
            session="POST_MARKET",
            run_id="run-4",
        )

    assert error.value.code == "NEWSLETTER_EMAIL_SES_SEND_FAILED"


def test_missing_ses_message_id_is_not_reported_as_success():
    html = "<!doctype html><html><body>Daily Alpha newsletter</body></html>"
    delivery = AwsNewsletterEmailDelivery(
        config=_config(),
        s3_client=_FakeS3(html),
        sesv2_client=_FakeSesV2(response={"MessageId": ""}),
        bucket="unit-bucket",
    )

    with pytest.raises(NewsletterEmailDeliveryError) as error:
        delivery.send_latest(
            report_date="2026-08-18",
            session="POST_MARKET",
            run_id="run-5",
        )

    assert error.value.code == "NEWSLETTER_EMAIL_MESSAGE_ID_MISSING"
