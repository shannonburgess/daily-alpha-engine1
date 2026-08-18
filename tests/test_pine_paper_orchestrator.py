from datetime import UTC, datetime

from daily_alpha.ledger import PaperLedger
from daily_alpha.models import OptionCandidate
from daily_alpha.orats import OratsChain
from daily_alpha.pine_paper_orchestrator import AwsPinePaperExecutor

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


class FakeSecrets:
    def get_secret_value(self, *, SecretId):
        assert SecretId == "daily-alpha/orats/staging"
        return {"SecretString": '{"token":"hidden-test-token"}'}


class FakeOrats:
    def __init__(self):
        self.calls = []
        self.bid = 2.0
        self.ask = 2.2

    def fetch_chain(self, ticker, *, as_of=None, dte_min=45, dte_max=75):
        self.calls.append((ticker, as_of, dte_min, dte_max))
        return OratsChain(
            ticker=ticker,
            candidates=(
                OptionCandidate(
                    symbol=ticker,
                    expiration="2026-10-16",
                    strike=100.0,
                    option_type="CALL",
                    dte=60,
                    bid=self.bid,
                    ask=self.ask,
                    open_interest=500,
                    volume=100,
                    delta=0.50,
                ),
            ),
            observed_at=NOW,
            source_mode="delayed",
        )


def ingress(action="ENTRY_LONG", **overrides):
    payload = {
        "schema_version": "2026-08-16-v3",
        "source": "TRADINGVIEW_PINE",
        "signal_id": f"AAPL-{action}",
        "symbol": "AAPL",
        "sector": "Technology",
        "lifecycle": "CONFIRMED_LEADER",
        "action": action,
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "1.9",
        "timeframe": "1D",
        "price": 110.0,
        "bar_time": NOW.isoformat(),
        "received_at": NOW.isoformat(),
        "position_fraction": None,
        "runner_stage": None,
        "stock_stop_price": None,
        "average_daily_dollar_volume": None,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def executor(tmp_path, fake_orats):
    return AwsPinePaperExecutor(
        ledger=PaperLedger(tmp_path),
        secrets_client=FakeSecrets(),
        paper_nav=1_000_000.0,
        orats_factory=lambda token: fake_orats,
    )


def test_entry_opens_option_starter_with_fresh_orats(tmp_path):
    fake_orats = FakeOrats()
    service = executor(tmp_path, fake_orats)

    result = service.execute(ingress(), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    assert result["paper_execution_triggered"] is True
    assert result["live_trading_enabled"] is False
    open_trade = service.ledger.find_open("AAPL")[0]
    assert open_trade.instrument.value == "OPTION"
    assert open_trade.runner_stage == "STARTER"
    assert open_trade.target_quantity % 4 == 0
    assert open_trade.quantity == open_trade.target_quantity // 2


def test_option_runner_add_uses_same_contract_orats_ask(tmp_path):
    fake_orats = FakeOrats()
    service = executor(tmp_path, fake_orats)
    service.execute(ingress(), now=NOW)
    before = service.ledger.find_open("AAPL")[0]
    fake_orats.bid = 2.4
    fake_orats.ask = 2.5

    result = service.execute(
        ingress(
            "ADD",
            signal_id="AAPL-ADD-1",
            position_fraction=0.25,
            runner_stage="ADD_1_ATR",
        ),
        now=NOW,
    )

    after = service.ledger.find_open("AAPL")[0]
    assert result["reason"] == "PAPER_ADD_APPLIED"
    assert after.quantity > before.quantity
    assert after.runner_stage == "ADD_1_ATR"
    assert fake_orats.calls[-1][2:] == (59, 61)


def test_stock_fallback_requires_stop_and_50m_liquidity(tmp_path):
    class NoOptions(FakeOrats):
        def fetch_chain(self, ticker, *, as_of=None, dte_min=45, dte_max=75):
            return OratsChain(
                ticker=ticker,
                candidates=(),
                observed_at=NOW,
                source_mode="delayed",
            )

    service = executor(tmp_path, NoOptions())
    result = service.execute(
        ingress(
            stock_stop_price=100.0,
            average_daily_dollar_volume=60_000_000.0,
        ),
        now=NOW,
    )

    assert result["disposition"] == "EXECUTED_PAPER"
    trade = service.ledger.find_open("AAPL")[0]
    assert trade.instrument.value == "STOCK"


def test_stock_fallback_below_50m_is_no_trade(tmp_path):
    class NoOptions(FakeOrats):
        def fetch_chain(self, ticker, *, as_of=None, dte_min=45, dte_max=75):
            return OratsChain(
                ticker=ticker,
                candidates=(),
                observed_at=NOW,
                source_mode="delayed",
            )

    service = executor(tmp_path, NoOptions())
    result = service.execute(
        ingress(
            stock_stop_price=100.0,
            average_daily_dollar_volume=40_000_000.0,
        ),
        now=NOW,
    )

    assert result["disposition"] == "NO_TRADE"
    assert service.ledger.find_open("AAPL") == []


def test_after_close_signal_cannot_mutate_paper_ledger(tmp_path):
    fake_orats = FakeOrats()
    service = executor(tmp_path, fake_orats)
    after_close = datetime(2026, 8, 17, 20, 5, tzinfo=UTC)

    result = service.execute(ingress(), now=after_close)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "OUTSIDE_REGULAR_EXECUTION_WINDOW"
    assert result["paper_execution_triggered"] is False
    assert result["live_trading_enabled"] is False
    assert service.ledger.find_open("AAPL") == []
    assert fake_orats.calls == []


def test_entry_with_unverified_sector_is_blocked(tmp_path):
    fake_orats = FakeOrats()
    service = executor(tmp_path, fake_orats)

    result = service.execute(ingress(sector="Unknown"), now=NOW)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "SECTOR_DATA_UNVERIFIED"
    assert service.ledger.find_open("AAPL") == []
    assert fake_orats.calls == []


def test_paper_entry_is_automatic_without_human_approval(tmp_path):
    fake_orats = FakeOrats()
    service = executor(tmp_path, fake_orats)

    result = service.execute(ingress(), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    assert result["paper_execution_triggered"] is True
    assert result["live_trading_enabled"] is False
    assert service.ledger.find_open("AAPL")



def test_extended_leader_gets_small_momentum_starter(tmp_path):
    extended_orats = FakeOrats()
    extended = executor(tmp_path / "extended", extended_orats)
    leader_orats = FakeOrats()
    leader = executor(tmp_path / "leader", leader_orats)

    result = extended.execute(ingress(lifecycle="EXTENDED_LEADER"), now=NOW)
    leader.execute(ingress(lifecycle="CONFIRMED_LEADER"), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    extended_trade = extended.ledger.find_open("AAPL")[0]
    leader_trade = leader.ledger.find_open("AAPL")[0]
    assert extended_trade.target_quantity < leader_trade.target_quantity


def test_missing_lifecycle_uses_smallest_paper_starter(tmp_path):
    unknown_orats = FakeOrats()
    unknown = executor(tmp_path / "unknown", unknown_orats)
    early_orats = FakeOrats()
    early = executor(tmp_path / "early", early_orats)

    result = unknown.execute(ingress(lifecycle=""), now=NOW)
    early.execute(ingress(lifecycle="EARLY_EMERGING"), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    unknown_trade = unknown.ledger.find_open("AAPL")[0]
    early_trade = early.ledger.find_open("AAPL")[0]
    assert unknown_trade.target_quantity == early_trade.target_quantity


def test_early_emerging_sizes_below_confirmed_leader(tmp_path):
    early_orats = FakeOrats()
    early = executor(tmp_path / "early", early_orats)
    leader_orats = FakeOrats()
    leader = executor(tmp_path / "leader", leader_orats)

    early.execute(ingress(lifecycle="EARLY_EMERGING"), now=NOW)
    leader.execute(ingress(lifecycle="CONFIRMED_LEADER"), now=NOW)

    early_trade = early.ledger.find_open("AAPL")[0]
    leader_trade = leader.ledger.find_open("AAPL")[0]
    assert early_trade.target_quantity < leader_trade.target_quantity
    assert early_trade.quantity < leader_trade.quantity


def test_option_add_rejected_when_position_is_not_profitable(tmp_path):
    fake_orats = FakeOrats()
    service = executor(tmp_path, fake_orats)
    service.execute(ingress(), now=NOW)

    result = service.execute(
        ingress(
            "ADD",
            signal_id="AAPL-ADD-LOSER",
            position_fraction=0.25,
            runner_stage="ADD_1_ATR",
        ),
        now=NOW,
    )

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "ADD_REJECTED_POSITION_NOT_PROFITABLE"
    assert service.ledger.find_open("AAPL")[0].runner_stage == "STARTER"
