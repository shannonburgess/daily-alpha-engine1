"""Deliver the exact published Daily Alpha newsletter HTML through Amazon SES."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class NewsletterEmailDeliveryError(RuntimeError):
    """Raised when configured newsletter email delivery cannot complete safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class NewsletterEmailConfig:
    """Environment-backed SES delivery configuration.

    Email addresses are operational configuration, not strategy state. Delivery is
    disabled when both sender and recipient configuration are absent. A partial
    configuration is rejected so the platform cannot silently claim email delivery.
    """

    sender: str = ""
    recipients: tuple[str, ...] = ()
    region: str = "us-east-2"

    @property
    def enabled(self) -> bool:
        return bool(self.sender and self.recipients)

    @classmethod
    def from_environment(cls) -> NewsletterEmailConfig:
        sender = os.getenv("DAILY_ALPHA_NEWSLETTER_EMAIL_FROM", "").strip()
        recipients = _parse_recipients(
            os.getenv("DAILY_ALPHA_NEWSLETTER_EMAIL_TO", "")
        )
        region = (
            os.getenv("DAILY_ALPHA_SES_REGION")
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-east-2"
        ).strip()
        if bool(sender) != bool(recipients):
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_CONFIG_INCOMPLETE")
        if sender and not _looks_like_email(sender):
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_FROM_INVALID")
        if any(not _looks_like_email(item) for item in recipients):
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_TO_INVALID")
        return cls(sender=sender, recipients=recipients, region=region)


class AwsNewsletterEmailDelivery:
    """Read the published newsletter from S3 and send that exact HTML through SESv2."""

    DEFAULT_BUCKET = "daily-alpha-staging-490809405132-us-east-2"
    LATEST_NEWSLETTER_KEY = "daily-alpha/outputs/latest/newsletter.html"

    def __init__(
        self,
        *,
        config: NewsletterEmailConfig | None = None,
        s3_client: Any | None = None,
        sesv2_client: Any | None = None,
        bucket: str | None = None,
    ) -> None:
        self.config = config or NewsletterEmailConfig.from_environment()
        self.bucket = (
            bucket
            or os.getenv("DAILY_ALPHA_STAGING_BUCKET")
            or self.DEFAULT_BUCKET
        ).strip()
        self.s3 = s3_client
        self.sesv2 = sesv2_client
        if not self.bucket:
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_BUCKET_INVALID")

    def send_latest(
        self,
        *,
        report_date: str,
        session: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Email the exact latest newsletter object already published to staging S3."""
        if not self.config.enabled:
            return {
                "status": "DISABLED",
                "reason": "NEWSLETTER_EMAIL_CONFIG_NOT_SET",
                "message_id": None,
                "recipient_count": 0,
                "run_id": run_id,
            }
        self._ensure_clients()
        try:
            response = self.s3.get_object(
                Bucket=self.bucket,
                Key=self.LATEST_NEWSLETTER_KEY,
            )
            raw = response["Body"].read()
        except Exception as exc:
            raise NewsletterEmailDeliveryError(
                "NEWSLETTER_EMAIL_S3_READ_FAILED"
            ) from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_S3_BODY_INVALID")
        try:
            html = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NewsletterEmailDeliveryError(
                "NEWSLETTER_EMAIL_HTML_INVALID_UTF8"
            ) from exc
        return self.send_html(
            html=html,
            report_date=report_date,
            session=session,
            run_id=run_id,
            source_key=self.LATEST_NEWSLETTER_KEY,
        )

    def send_html(
        self,
        *,
        html: str,
        report_date: str,
        session: str,
        run_id: str,
        source_key: str = LATEST_NEWSLETTER_KEY,
    ) -> dict[str, Any]:
        """Send a complete rendered Daily Alpha newsletter as the HTML email body."""
        if not self.config.enabled:
            return {
                "status": "DISABLED",
                "reason": "NEWSLETTER_EMAIL_CONFIG_NOT_SET",
                "message_id": None,
                "recipient_count": 0,
                "run_id": run_id,
            }
        if "<html" not in html.lower() or "Daily Alpha" not in html:
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_HTML_VALIDATION_FAILED")
        self._ensure_clients()
        normalized_session = str(session or "MANUAL").strip().upper().replace("_", " ")
        session_label = normalized_session.title()
        subject = f"Daily Alpha & Risk — {report_date} — {session_label}"
        text = (
            "Daily Alpha & Risk\n"
            f"{report_date} — {session_label}\n\n"
            "This message contains the complete Daily Alpha HTML newsletter. "
            "Use an HTML-capable email client to view the full edition.\n\n"
            "Research and paper-trading output only; not investment advice. "
            "No live order execution is authorized."
        )
        try:
            response = self.sesv2.send_email(
                FromEmailAddress=self.config.sender,
                Destination={"ToAddresses": list(self.config.recipients)},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Html": {"Data": html, "Charset": "UTF-8"},
                            "Text": {"Data": text, "Charset": "UTF-8"},
                        },
                    }
                },
            )
        except Exception as exc:
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_SES_SEND_FAILED") from exc
        message_id = str(response.get("MessageId") or "").strip()
        if not message_id:
            raise NewsletterEmailDeliveryError("NEWSLETTER_EMAIL_MESSAGE_ID_MISSING")
        return {
            "status": "SENT",
            "reason": "SES_ACCEPTED",
            "message_id": message_id,
            "recipient_count": len(self.config.recipients),
            "subject": subject,
            "source_key": source_key,
            "run_id": run_id,
        }

    def _ensure_clients(self) -> None:
        if self.s3 is not None and self.sesv2 is not None:
            return
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - Lambda runtime includes boto3
            raise NewsletterEmailDeliveryError("BOTO3_UNAVAILABLE") from exc
        if self.s3 is None:
            self.s3 = boto3.client("s3", region_name=self.config.region)
        if self.sesv2 is None:
            self.sesv2 = boto3.client("sesv2", region_name=self.config.region)


def _parse_recipients(value: str) -> tuple[str, ...]:
    normalized = value.replace(";", ",")
    recipients = tuple(
        item.strip() for item in normalized.split(",") if item.strip()
    )
    return tuple(dict.fromkeys(recipients))


def _looks_like_email(value: str) -> bool:
    local, separator, domain = value.rpartition("@")
    return bool(separator and local and domain and "." in domain)
