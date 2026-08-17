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
                    bid=2.0,
                    ask=2.2,
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
