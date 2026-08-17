from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.dynamo_ledger import DynamoPaperLedger, LedgerStorageError
from daily_alpha.models import InstrumentSelected

NOW = datetime(2026, 8, 16, 6, 30, tzinfo=UTC)


class FakeAwsError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeDynamo:
    def __init__(self):
        self.items = {}
        self.fail_get = None

    @staticmethod
    def _key(values):
        return values["pk"]["S"], values["sk"]["S"]

    def get_item(self, *, TableName, Key, ConsistentRead):
        assert TableName
        assert ConsistentRead is True
        if self.fail_get:
            raise FakeAwsError(self.fail_get)
        item = self.items.get(self._key(Key))
        return {} if item is None else {"Item": item}

    def transact_write_items(self, *, TransactItems):
        pending = dict(self.items)
        for operation in TransactItems:
            if "Put" in operation:
                request = operation["Put"]
                key = self._key(request["Item"])
                condition = request.get("ConditionExpression")
                if condition == "attribute_not_exists(pk)" and key in pending:
                    raise FakeAwsError("TransactionCanceledException")
                if condition == "trade_id = :trade_id":
                    existing = pending.get(key)
                    expected = request["ExpressionAttributeValues"][":trade_id"]["S"]
                    if existing is None or existing["trade_id"]["S"] != expected:
                        raise FakeAwsError("TransactionCanceledException")
                pending[key] = request["Item"]
            elif "Delete" in operation:
                request = operation["Delete"]
                key = self._key(request["Key"])
                existing = pending.get(key)
                expected = request["ExpressionAttributeValues"][":trade_id"]["S"]
                if existing is None or existing["trade_id"]["S"] != expected:
                    raise FakeAwsError("TransactionCanceledException")
                del pending[key]
            else:
                raise AssertionError("unexpected transaction operation")
        self.items = pending


def ledger(client=None):
    return DynamoPaperLedger(
        table_name="unit-test-ledger",
        account_id="paper-unit",
        client=client or FakeDynamo(),
    )


def test_open_is_durable_idempotent_and_append_only():
    client = FakeDynamo()
    store = ledger(client)
    opened = store.open_trade(
        signal_id="signal-1",
        symbol="AAPL",
        instrument=InstrumentSelected.OPTION,
        quantity=4,
        target_quantity=8,
        entry_price=2.0,
        entry_time=NOW,
        fallback_reason="QUALIFIED_OPTION_SELECTED",
        option_expiration="2026-10-16",
        option_strike=220,
        option_type="CALL",
    )
    repeated = store.open_trade(
        signal_id="signal-1",
        symbol="AAPL",
        instrument=InstrumentSelected.OPTION,
        quantity=4,
        target_quantity=8,
        entry_price=2.0,
        entry_time=NOW,
        fallback_reason="QUALIFIED_OPTION_SELECTED",
        option_expiration="2026-10-16",
        option_strike=220,
        option_type="CALL",
    )

    assert repeated.trade_id == opened.trade_id
    assert store.find_open("AAPL", InstrumentSelected.OPTION) == [opened]
    assert len(client.items) == 2

    with pytest.raises(ValueError, match="already exists"):
        store.open_trade(
            signal_id="different-signal",
            symbol="AAPL",
            instrument=InstrumentSelected.OPTION,
            quantity=1,
            entry_price=2.0,
            entry_time=NOW,
            fallback_reason="QUALIFIED_OPTION_SELECTED",
        )


def test_runner_add_partial_close_is_durable_and_idempotent():
    client = FakeDynamo()
    store = ledger(client)
    opened = store.open_trade(
        signal_id="entry",
        symbol="MU",
        instrument=InstrumentSelected.OPTION,
        quantity=4,
        target_quantity=8,
        entry_price=2.0,
        entry_time=NOW,
        fallback_reason="QUALIFIED_OPTION_SELECTED",
        option_expiration="2026-10-16",
        option_strike=500,
        option_type="CALL",
    )

    add1 = store.add_trade(
        opened,
        signal_id="add-1",
        quantity=2,
        fill_price=2.5,
        fill_time=NOW + timedelta(minutes=1),
        runner_stage="ADD_1_ATR",
    )
    assert add1.quantity == 6
    assert add1.entry_price == pytest.approx(2.16666667)
    assert add1.runner_stage == "ADD_1_ATR"

    duplicate = store.add_trade(
        add1,
        signal_id="add-1",
        quantity=2,
        fill_price=2.5,
        fill_time=NOW + timedelta(minutes=1),
        runner_stage="ADD_1_ATR",
    )
    assert duplicate.quantity == 6

    add2 = store.add_trade(
        add1,
        signal_id="add-2",
        quantity=2,
        fill_price=3.0,
        fill_time=NOW + timedelta(minutes=2),
        runner_stage="ADD_2_ATR",
    )
    assert add2.quantity == 8
    assert add2.entry_price == pytest.approx(2.375)

    partial = store.partial_trade(
        add2,
        signal_id="harvest",
        quantity=2,
        fill_price=4.0,
        fill_time=NOW + timedelta(minutes=3),
        runner_stage="HARVEST_3_ATR",
    )
    assert partial.quantity == 6
    assert partial.realized_pnl == pytest.approx(325.0)
    assert partial.runner_stage == "HARVEST_3_ATR"

    closed = store.close_trade(
        partial,
        exit_price=3.5,
        exit_time=NOW + timedelta(minutes=4),
        signal_id="exit",
    )
    assert closed.realized_pnl == pytest.approx(1000.0)
    assert store.find_open("MU") == []

    events = [item for item in client.items.values() if item.get("event")]
    assert [item["event"]["S"] for item in events].count("OPEN") == 1
    assert [item["event"]["S"] for item in events].count("ADD") == 2
    assert [item["event"]["S"] for item in events].count("PARTIAL") == 1
    assert [item["event"]["S"] for item in events].count("CLOSE") == 1


def test_close_removes_current_position_and_keeps_audit_history():
    client = FakeDynamo()
    store = ledger(client)
    opened = store.open_trade(
        signal_id="signal-1",
        symbol="RDW",
        instrument=InstrumentSelected.OPTION,
        quantity=5,
        entry_price=2.0,
        entry_time=NOW,
        fallback_reason="QUALIFIED_OPTION_SELECTED",
        option_expiration="2026-10-16",
        option_strike=15,
        option_type="CALL",
    )
    closed = store.close_trade(
        opened,
        exit_price=2.5,
        exit_time=datetime(2026, 8, 16, 7, 0, tzinfo=UTC),
    )

    assert closed.realized_pnl == 250.0
    assert store.find_open("RDW") == []
    events = [item for item in client.items.values() if item.get("event")]
    assert {item["event"]["S"] for item in events} == {"OPEN", "CLOSE"}
    assert len(client.items) == 2


def test_stock_and_option_positions_are_separate_keys():
    store = ledger()
    for instrument, signal_id in (
        (InstrumentSelected.OPTION, "option-signal"),
        (InstrumentSelected.STOCK, "stock-signal"),
    ):
        store.open_trade(
            signal_id=signal_id,
            symbol="NVDA",
            instrument=instrument,
            quantity=1,
            entry_price=100.0,
            entry_time=NOW,
            fallback_reason="TEST",
        )

    assert {trade.instrument for trade in store.find_open("NVDA")} == {
        InstrumentSelected.OPTION,
        InstrumentSelected.STOCK,
    }


def test_storage_failure_is_fail_closed():
    client = FakeDynamo()
    client.fail_get = "ResourceNotFoundException"
    store = ledger(client)
    with pytest.raises(LedgerStorageError, match="DYNAMODB_RESOURCENOTFOUNDEXCEPTION"):
        store.find_open("AAPL")
