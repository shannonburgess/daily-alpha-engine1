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
from daily_alpha.orats import OratsChain, OratsDataError

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
                "reason": "PAPER_POSITION_OPENED",
            },
        }
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"Payload": io.BytesIO(json.dumps(self.body).encode("utf-8"))}


class FakeOrats:
    def __init__(self, stock_price=101.0, error=None):
        self.stock_price = stock_price
        self.error = error
        self.calls = []

    def fetch_chain(self, ticker, *, as_of=None, dte_min=45, dte_max=75):
        self.calls.append((ticker, as_of, dte_min, dte_max))
        if self.error:
            raise self.error
        return OratsChain(
            ticker=ticker,
            candidates=(),
            observed_at=NOW,
            source_mode="delayed",
            stock_price=self.stock_price,
        )


def _pending_doc():
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
            "lifecycle": "ENTRY_WATCH",
            "sector": "Technology",
            "stock_stop_price": 95.0,
            "average_daily_dollar_volume": 100_000_000.0,
        },
        market_date="2026-08-17",
        created_at=datetime(2026, 8, 17, 20, 20, tzinfo=UTC),
        state_before=None,
        state_after=state,
    )
    return {"schema_version": "2026-08-17-pending-v1", "actions": [pending]}


def _s3_with_pending():
    return FakeS3(
        {
            "daily-alpha/execution-universe/latest/pending_actions.json": json.dumps(
                _pending_doc()
            ),
            "daily-alpha/execution-universe/latest/state.json": "{}",
            "daily-alpha/execution-universe/latest/active_watch.json": json.dumps(
                [{"rank": "1", "symbol": "MU", "position": "FLAT"}]
            ),
        }
    )


def test_valid_next_session_entry_routes_to_paper_processor_without_human_approval(tmp_path):
    s3 = _s3_with_pending()
    lamb = FakeLambda()
    orats = FakeOrats(stock_price=101.0)

    audit = run_next_session_execution(
        mode="morning_primary",
        bucket="test",
        token="token",
        workdir=tmp_path,
        now=NOW,
        s3_client=s3,
        lambda_client=lamb,
        orats_client=orats,
        run_id="123",
    )

    assert audit["executed_paper"] == 1
    assert audit["paper_execution_mode"] == "AUTONOMOUS_LIFECYCLE_SIZED"
    assert audit["live_trading_enabled"] is False
    assert len(lamb.calls) == 1
    payload = json.loads(lamb.calls[0]["Payload"].decode("utf-8"))
    assert payload["operation"] == "EXECUTE_SCANNER_SIGNAL"
    assert payload["signal"]["price"] == 101.0
    assert "human_approval" not in payload["signal"]
    pending = json.loads(
        s3.uploads["daily-alpha/execution-universe/latest/pending_actions.json"]
    )
    assert pending["actions"] == []
    state = json.loads(s3.uploads["daily-alpha/execution-universe/latest/state.json"])
    assert state["MU"]["runner_stage"] == "STARTER"


def test_orats_data_error_is_deferred_not_filled(tmp_path):
    s3 = _s3_with_pending()
    lamb = FakeLambda()
    orats = FakeOrats(error=OratsDataError("stale"))

    audit = run_next_session_execution(
        mode="morning_primary",
        bucket="test",
        token="token",
        workdir=tmp_path,
        now=NOW,
        s3_client=s3,
        lambda_client=lamb,
        orats_client=orats,
    )

    assert audit["executed_paper"] == 0
    assert audit["deferred_data_error"] == 1
    assert lamb.calls == []
    pending = json.loads(
        s3.uploads["daily-alpha/execution-universe/latest/pending_actions.json"]
    )
    assert pending["actions"][0]["status"] == RETRY_STATUS


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
            token="token",
            workdir=tmp_path,
            now=NOW,
            s3_client=s3,
            lambda_client=lamb,
            orats_client=FakeOrats(stock_price=101.0),
        )
