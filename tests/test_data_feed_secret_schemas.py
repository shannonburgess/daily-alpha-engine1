import json
from types import SimpleNamespace

import staging_lambda_handlers.data_feed_ingest as ingest


class _Secrets:
    def __init__(self, value):
        self.value = value

    def get_secret_value(self, **kwargs):
        assert kwargs["VersionStage"] == "AWSCURRENT"
        return {"SecretString": self.value}


def test_provider_specific_secret_keys_match_deployed_aws_schema():
    cases = {
        "massive": ("MASSIVE_API_KEY", "massive-secret"),
        "tiingo": ("TIINGO_API_TOKEN", "tiingo-secret"),
        "fred": ("FRED_API_KEY", "fred-secret"),
    }
    for provider, (key, value) in cases.items():
        payload = json.dumps({key: value})
        assert ingest._load_secret(provider, client=_Secrets(payload)) == value


def test_provider_specific_secret_keys_are_not_cross_accepted():
    wrong = {
        "massive": {"FRED_API_KEY": "secret"},
        "tiingo": {"MASSIVE_API_KEY": "secret"},
        "fred": {"TIINGO_API_TOKEN": "secret"},
    }
    for provider, payload in wrong.items():
        try:
            ingest._load_secret(provider, client=_Secrets(json.dumps(payload)))
        except ingest.DataFeedIngestionError as exc:
            assert str(exc) == "SECRET_JSON_KEY_AMBIGUOUS_OR_MISSING"
        else:
            raise AssertionError("provider-specific secret schema must fail closed")


def test_secret_loading_failure_is_logged_with_safe_provider_code(monkeypatch, capsys):
    monkeypatch.setenv("RAW_EVIDENCE_BUCKET", "unit-bucket")
    monkeypatch.setattr(
        ingest,
        "_load_secret",
        lambda provider: (_ for _ in ()).throw(
            ingest.DataFeedIngestionError("SECRET_JSON_KEY_AMBIGUOUS_OR_MISSING")
        ),
    )

    try:
        ingest.lambda_handler(
            {"provider": "massive", "targets": ["SPY"]},
            SimpleNamespace(aws_request_id="req-secret-schema"),
        )
    except ingest.DataFeedIngestionError as exc:
        assert str(exc) == "SECRET_JSON_KEY_AMBIGUOUS_OR_MISSING"
    else:
        raise AssertionError("secret failure must fail closed")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event"] == "DATA_FEED_INGEST_FAILURE"
    assert event["provider"] == "MASSIVE"
    assert event["error_code"] == "SECRET_JSON_KEY_AMBIGUOUS_OR_MISSING"
    assert event["trading_authorized"] is False
    assert event["live_trading_enabled"] is False
