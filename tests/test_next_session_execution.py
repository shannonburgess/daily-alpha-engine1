import io
import json
from datetime import UTC, datetime

import pytest

from daily_alpha.execution_queue import RETRY_STATUS, build_pending_action
from daily_alpha.execution_universe import ScannerState
from daily_alpha.next_session_execution import (
    UnsafeExecutionError,
    run_next_session_execution,
)

NOW = datetime(2026, 8, 18, 13, 45, tzinfo=UTC)


class MissingObject(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.uploads = {}

    def download_file(self, bucket, key, path):
        del bucket
        if key not in self.objects:
            raise MissingObject()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.objects[key])

    def upload_file(self, path, bucket, key):
        del bucket
        with open(path, encoding="utf-8") as handle:
            self.uploads[key] = handle.read()


class FakeLambda:
    def __init__(self, body=None):
        self.body = body or {
            "ok": True,
            "live_trading_enabled": False,
            "execution": {
                "disposition": "EXECUTED_PAPER",
                "reason": "PAPER_STOCK_POSITION_OPENED",
            },
        }
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"Payload": io.BytesIO(json.dumps(self.body).encode("utf-8"))}


def _pending_doc(*, stock_price=101.0):
    state = ScannerState(
        symbol="MU",
        entry_date="2026-08-17",
        runner_base_entry=100.0,
        runner_base_atr=5.0,
        entry_breakout_level=98.0,
    )
    pending = build_pending_action(
        symbol="MU",
        action="ENTRY_LONG",
        reason="NORMAL_BREAKOUT",
        signal={
            "source": "DAILY_ALPHA_SCANNER",
            "signal_id": "DA-SCAN-MU-2026-08-17-ENTRY_LONG",
            "symbol": "MU",
            "action": "ENTRY_LONG",
            "strategy": "DA_TURTLE_ADAPTIVE_TREND",
            "strategy_version": "2.4",
            "timeframe": "D",
            "price": 100.0,
            "bar_time": "2026-08-17T20:20:00+00:00",
            "entry_type": "NORMAL_BREAKOUT",
            "stock_stop_price": 95.0,
            "average_daily_dollar_volume": 100_000_000.0,
        },
        market_date="2026-08-17",
        created_at=datetime(2026, 8, 17, 20, 20, tzinfo=UTC),
        state_before=None,
        state_after=state,
    )
    if stock_price is not None:
        pending["execution_stock_price"] = stock_price
    pending["human_approval"] = {
        "status": "APPROVED",
        "approval_id": "test-approval-1",
        "approved_risk_fraction": 0.005,
    }
    return {"schema_version": "2026-08-17-pending-v1", "actions": [pending]}


def _s3_with_pending(*, stock_price=101.0):
    return FakeS3(
        {
            "daily-alpha/execution-universe/latest/pending_actions.json": json.dumps(
                _pending_doc(stock_price=stock_price)
            ),
            "daily-alpha/execution-universe/latest/state.json": "{}",
            "daily-alpha/execution-universe/latest/active_watch.json": json.dumps(
                [{"rank": "1", "symbol": "MU", "position": "FLAT"}]
            ),
        }
    )


def test_valid_next_session_entry_routes_to_paper_processor(tmp_path):
    s3 = _s3_with_pending(stock_price=101.0)
    lamb = FakeLambda()

    audit = run_next_session_execution(
        mode="morning_primary",
        bucket="test",
        workdir=tmp_path,
        now=NOW,
        s3_client=s3,
        lambda_client=lamb,
        run_id="123",
    )

    assert audit["executed_paper"] == 1
    assert audit["instrument_policy"] == "STOCK_ONLY"
    assert audit["options_mode"] == "USER_DIRECTED_BROKER_CHAIN"
    assert audit["live_trading_enabled"] is False
    assert len(lamb.calls) == 1
    payload = json.loads(lamb.calls[0]["Payload"].decode("utf-8"))
    assert payload["operation"] == "EXECUTE_SCANNER_SIGNAL"
    assert payload["signal"]["price"] == 101.0
    pending = json.loads(
        s3.uploads["daily-alpha/execution-universe/latest/pending_actions.json"]
    )
    assert pending["actions"] == []
    state = json.loads(s3.uploads["daily-alpha/execution-universe/latest/state.json"])
    assert state["MU"]["runner_stage"] == "STARTER"


def test_missing_current_stock_price_is_deferred_not_filled(tmp_path):
    s3 = _s3_with_pending(stock_price=None)
    lamb = FakeLambda()

    audit = run_next_session_execution(
        mode="morning_primary",
        bucket="test",
        workdir=tmp_path,
        now=NOW,
        s3_client=s3,
        lambda_client=lamb,
    )

    assert audit["executed_paper"] == 0
    assert audit["deferred_data_error"] == 1
    assert lamb.calls == []
    pending = json.loads(
        s3.uploads["daily-alpha/execution-universe/latest/pending_actions.json"]
    )
    assert pending["actions"][0]["status"] == RETRY_STATUS
    assert "CURRENT_STOCK_PRICE_REQUIRED" in pending["actions"][0]["last_error"]


def test_unsafe_live_enabled_processor_response_fails_hard(tmp_path):
    s3 = _s3_with_pending()
    lamb = FakeLambda(
        {
            "ok": True,
            "live_trading_enabled": True,
            "execution": {"disposition": "EXECUTED_PAPER"},
        }
    )

    with pytest.raises(UnsafeExecutionError):
        run_next_session_execution(
            mode="morning_primary",
            bucket="test",
            workdir=tmp_path,
            now=NOW,
            s3_client=s3,
            lambda_client=lamb,
        )


def test_unapproved_entry_remains_pending_without_price_or_processor_use(tmp_path):
    doc = _pending_doc()
    doc["actions"][0].pop("human_approval")
    doc["actions"][0].pop("execution_stock_price")
    s3 = FakeS3(
        {
            "daily-alpha/execution-universe/latest/pending_actions.json": json.dumps(doc),
            "daily-alpha/execution-universe/latest/state.json": "{}",
            "daily-alpha/execution-universe/latest/active_watch.json": "[]",
        }
    )
    lamb = FakeLambda()

    audit = run_next_session_execution(
        mode="morning_primary",
        bucket="test",
        workdir=tmp_path,
        now=NOW,
        s3_client=s3,
        lambda_client=lamb,
    )

    assert audit["executed_paper"] == 0
    assert lamb.calls == []
    pending = json.loads(
        s3.uploads["daily-alpha/execution-universe/latest/pending_actions.json"]
    )
    assert pending["actions"][0]["status"] == "PENDING_HUMAN_APPROVAL"
