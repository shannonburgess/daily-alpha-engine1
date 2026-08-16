import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.pine_ingress import (
    PineIngressAuthError,
    build_pine_ingress_record,
)
from daily_alpha.signals import SignalError
from lambda_handlers import pine_webhook

NOW = datetime(2026, 8, 16, 11, 30, tzinfo=UTC)
SECRET = "super-secret-webhook-token"
SECRET_ID = "daily-alpha/pine-webhook/staging"


def payload(*, bar_time=None, secret=SECRET):
    return {
        "webhook_secret": secret,
        "signal_id": "signal-123",
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "strategy": "daily-alpha-pine",
        "strategy_version": "v6",
        "timeframe": "15",
        "price": 225.5,
        "bar_time": (bar_time or (NOW - timedelta(minutes=2))).isoformat(),
    }


def test_valid_webhook_is_authenticated_normalized_and_secret_removed():
    record = build_pine_ingress_record(
        {"body": json.dumps(payload())},
        expected_secret=SECRET,
        received_at=NOW,
    )
    data = record.to_dict()
    assert data["signal_id"] == "signal-123"
    assert data["symbol"] == "AAPL"
    assert data["action"] == "ENTRY_LONG"
    assert data["source"] == "TRADINGVIEW_PINE"
    assert "webhook_secret" not in data
    assert SECRET not in json.dumps(data)
    assert data["trading_authorized"] is False
    assert data["live_trading_enabled"] is False


def test_wrong_webhook_secret_fails_closed():
    with pytest.raises(PineIngressAuthError, match="WEBHOOK_AUTH_FAILED"):
        build_pine_ingress_record(
            {"body": json.dumps(payload(secret="wrong"))},
            expected_secret=SECRET,
            received_at=NOW,
        )


def test_base64_api_gateway_body_is_supported():
    encoded = base64.b64encode(json.dumps(payload()).encode()).decode()
    record = build_pine_ingress_record(
        {"body": encoded, "isBase64Encoded": True},
        expected_secret=SECRET,
        received_at=NOW,
    )
    assert record.symbol == "AAPL"


def test_stale_signal_is_rejected_before_queueing():
    with pytest.raises(SignalError, match="Signal is stale"):
        build_pine_ingress_record(
            {"body": json.dumps(payload(bar_time=NOW - timedelta(minutes=45)))},
            expected_secret=SECRET,
            received_at=NOW,
            max_age_minutes=30,
        )


def _configure_secret(monkeypatch):
    monkeypatch.setenv("PINE_WEBHOOK_SECRET_ID", SECRET_ID)
    monkeypatch.setattr(pine_webhook, "_load_webhook_secret", lambda _: SECRET)


def test_lambda_refuses_false_success_when_queue_is_not_configured(monkeypatch):
    _configure_secret(monkeypatch)
    monkeypatch.delenv("PINE_INGRESS_QUEUE_URL", raising=False)
    current_payload = payload(bar_time=datetime.now(UTC) - timedelta(minutes=1))
    response = pine_webhook.lambda_handler({"body": json.dumps(current_payload)}, None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 503
    assert body["status"] == "INGRESS_QUEUE_NOT_CONFIGURED"
    assert body["trading_authorized"] is False
    assert body["live_trading_enabled"] is False


def test_lambda_rejects_bad_secret_without_echoing_it(monkeypatch):
    _configure_secret(monkeypatch)
    monkeypatch.setenv("PINE_INGRESS_QUEUE_URL", "https://example.invalid/queue")
    current_payload = payload(
        bar_time=datetime.now(UTC) - timedelta(minutes=1),
        secret="attacker-secret",
    )
    response = pine_webhook.lambda_handler({"body": json.dumps(current_payload)}, None)
    assert response["statusCode"] == 401
    assert "attacker-secret" not in response["body"]
    assert SECRET not in response["body"]


def test_lambda_fails_closed_when_secret_id_is_missing(monkeypatch):
    monkeypatch.delenv("PINE_WEBHOOK_SECRET_ID", raising=False)
    monkeypatch.setenv("PINE_INGRESS_QUEUE_URL", "https://example.invalid/queue")
    response = pine_webhook.lambda_handler({"body": json.dumps(payload())}, None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 503
    assert body["status"] == "INGRESS_SECRET_NOT_CONFIGURED"


def test_lambda_fails_closed_when_secret_retrieval_fails(monkeypatch):
    monkeypatch.setenv("PINE_WEBHOOK_SECRET_ID", SECRET_ID)
    monkeypatch.setenv("PINE_INGRESS_QUEUE_URL", "https://example.invalid/queue")

    def fail(_):
        raise RuntimeError("provider detail must not escape")

    monkeypatch.setattr(pine_webhook, "_load_webhook_secret", fail)
    response = pine_webhook.lambda_handler({"body": json.dumps(payload())}, None)
    body = json.loads(response["body"])
    assert response["statusCode"] == 503
    assert body["status"] == "INGRESS_SECRET_ERROR"
    assert "provider detail" not in response["body"]


def test_secret_parser_requires_expected_json_key(monkeypatch):
    class FakeSecretsClient:
        def get_secret_value(self, *, SecretId):
            assert SecretId == SECRET_ID
            return {"SecretString": json.dumps({"wrong_key": "value"})}

    class FakeBoto3:
        @staticmethod
        def client(service):
            assert service == "secretsmanager"
            return FakeSecretsClient()

    monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto3())
    with pytest.raises(ValueError, match="PINE_WEBHOOK_SECRET_KEY_MISSING"):
        pine_webhook._load_webhook_secret(SECRET_ID)
