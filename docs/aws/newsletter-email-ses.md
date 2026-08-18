# Daily Alpha automatic newsletter email — Amazon SES

The `daily-alpha-report` Lambda can automatically email the exact HTML object published at:

`daily-alpha/outputs/latest/newsletter.html`

It also supports `SEND_LATEST_NEWSLETTER` to resend that exact S3 object without rebuilding OVTLYR/ORATS research.

## Runtime configuration

The report Lambda reads these environment variables:

- `DAILY_ALPHA_NEWSLETTER_EMAIL_FROM` — verified Amazon SES sender identity.
- `DAILY_ALPHA_NEWSLETTER_EMAIL_TO` — comma-separated recipients.
- `DAILY_ALPHA_SES_REGION` — SES region; staging default is `us-east-2`.

When both FROM and TO are absent, publication continues with `email_delivery.status=DISABLED`. A partial configuration is rejected. If SES is configured but sending fails, the report returns `PUBLISHED_EMAIL_FAILED` so GitHub Actions does not silently claim the email was sent.

## Fastest staging activation

For the initial private staging workflow, the same verified email address can be used as both sender and recipient. This is particularly useful while the SES account is still in the sandbox because sandbox recipients must also be verified. For commercial delivery, move to a verified Daily Alpha domain and request SES production access.

Set shell variables:

```bash
export AWS_REGION=us-east-2
export AWS_ACCOUNT_ID=490809405132
export NEWSLETTER_EMAIL="shannon.burgess@gmail.com"
```

Create/check the SES email identity:

```bash
aws sesv2 create-email-identity \
  --region "$AWS_REGION" \
  --email-identity "$NEWSLETTER_EMAIL" || true

aws sesv2 get-email-identity \
  --region "$AWS_REGION" \
  --email-identity "$NEWSLETTER_EMAIL" \
  --query '{IdentityType:IdentityType,VerifiedForSendingStatus:VerifiedForSendingStatus}'
```

Amazon SES sends a verification message to that mailbox. Click the verification link before testing delivery.

## Grant the report Lambda permission to send

Resolve the report Lambda execution role instead of guessing its name:

```bash
REPORT_ROLE_ARN="$(aws lambda get-function-configuration \
  --region "$AWS_REGION" \
  --function-name daily-alpha-report \
  --query Role \
  --output text)"
REPORT_ROLE_NAME="${REPORT_ROLE_ARN##*/}"
echo "$REPORT_ROLE_NAME"
```

Grant only `ses:SendEmail` for the verified staging identity:

```bash
aws iam put-role-policy \
  --role-name "$REPORT_ROLE_NAME" \
  --policy-name DailyAlphaNewsletterSesSend \
  --policy-document "$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SendDailyAlphaNewsletter",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "arn:aws:ses:${AWS_REGION}:${AWS_ACCOUNT_ID}:identity/${NEWSLETTER_EMAIL}"
    }
  ]
}
JSON
)"
```

## Merge the Lambda environment safely

Do **not** replace the Lambda environment with only the new email values. Preserve existing variables and merge these three values:

```bash
aws lambda get-function-configuration \
  --region "$AWS_REGION" \
  --function-name daily-alpha-report \
  --query 'Environment.Variables' \
  --output json > /tmp/daily-alpha-report-env.json

python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path('/tmp/daily-alpha-report-env.json')
raw = path.read_text().strip()
current = json.loads(raw) if raw and raw != 'null' else {}
current.update(
    {
        'DAILY_ALPHA_NEWSLETTER_EMAIL_FROM': os.environ['NEWSLETTER_EMAIL'],
        'DAILY_ALPHA_NEWSLETTER_EMAIL_TO': os.environ['NEWSLETTER_EMAIL'],
        'DAILY_ALPHA_SES_REGION': os.environ['AWS_REGION'],
    }
)
Path('/tmp/daily-alpha-report-env-update.json').write_text(
    json.dumps({'Variables': current})
)
PY

aws lambda update-function-configuration \
  --region "$AWS_REGION" \
  --function-name daily-alpha-report \
  --environment file:///tmp/daily-alpha-report-env-update.json

aws lambda wait function-updated \
  --region "$AWS_REGION" \
  --function-name daily-alpha-report
```

## Send the current newsletter immediately

After the feature has deployed and the SES identity is verified, resend the already-published current newsletter without rebuilding research:

```bash
aws lambda invoke \
  --region "$AWS_REGION" \
  --function-name daily-alpha-report \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation":"SEND_LATEST_NEWSLETTER","report_date":"2026-08-18","session":"MORNING","run_id":"manual-resend"}' \
  /tmp/daily-alpha-newsletter-email.json

cat /tmp/daily-alpha-newsletter-email.json
```

Success requires:

```json
{
  "ok": true,
  "status": "EMAIL_SENT"
}
```

and `email_delivery.status` must be `SENT` with a non-empty SES `message_id`.

## Automatic behavior

The existing ranked-shortlist workflow already invokes `daily-alpha-report` after the shortlist is uploaded. Once SES configuration is active, that same invocation automatically sends the complete validated HTML newsletter after S3 publication. The email feature does not alter trading signals, sizing, paper execution, or live-trading authorization.
