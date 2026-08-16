from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.webhook import SignalWebhook, WebhookError

NOW = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)


def payload(**overrides):
    values = {
        "webhook_secret": "correct-secret",
        "signal_id": "pine-123",
        "symbol": "AAPL",
        "action": "ENTRY_LONG",
        "strategy": "DAILY_ALPHA_PINE",
        "strategy_version": "v2",
        "timeframe": "1D",
        "price": 250.0,
        "bar_time": (NOW - timedelta(minutes=1)).isoformat(),
    }
    values.update(overrides)
    return values


def test_authenticated_fresh_signal_is_accepted_without_execution():
    claimed = set()
    receipt = SignalWebhook(
        secret="correct-secret", claimed_signal_ids=claimed
    ).receive(payload(), received_at=NOW)
    assert receipt.accepted is True
    assert receipt.signal.symbol == "AAPL"
    assert claimed == {"pine-123"}


def test_wrong_or_missing_secret_is_rejected():
    webhook = SignalWebhook(secret="correct-secret", claimed_signal_ids=set())
    with pytest.raises(WebhookError, match="UNAUTHORIZED"):
        webhook.receive(payload(webhook_secret="wrong"), received_at=NOW)
    with pytest.raises(WebhookError, match="UNAUTHORIZED"):
        webhook.receive(payload(webhook_secret=""), received_at=NOW)


def test_duplicate_signal_is_idempotent_and_not_reprocessed():
    webhook = SignalWebhook(secret="correct-secret", claimed_signal_ids=set())
    webhook.receive(payload(), received_at=NOW)
    duplicate = webhook.receive(payload(), received_at=NOW)
    assert duplicate.accepted is False
    assert duplicate.duplicate is True
    assert duplicate.signal is None


def test_signal_id_is_required_for_durable_deduplication():
    with pytest.raises(WebhookError, match="SIGNAL_ID_REQUIRED"):
        SignalWebhook(secret="correct-secret", claimed_signal_ids=set()).receive(
            payload(signal_id=""), received_at=NOW
        )


def test_stale_signal_is_rejected_before_claiming_id():
    claimed = set()
    with pytest.raises(WebhookError, match="stale"):
        SignalWebhook(secret="correct-secret", claimed_signal_ids=claimed).receive(
            payload(bar_time=(NOW - timedelta(hours=2)).isoformat()), received_at=NOW
        )
    assert claimed == set()


def test_invalid_json_is_rejected():
    with pytest.raises(WebhookError, match="INVALID_JSON"):
        SignalWebhook(secret="correct-secret", claimed_signal_ids=set()).receive(
            "not-json"
        )
