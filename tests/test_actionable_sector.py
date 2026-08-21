import json
from datetime import UTC, datetime

from daily_alpha.actionable_sector import (
    S3ActionableContextStore,
    enrich_entry_sector,
)
from daily_alpha.ledger import PaperLedger
from daily_alpha.shadow_routing import PAPER_SHADOW_V24, ShadowRoutedPinePaperExecutor

NOW = datetime(2026, 8, 21, 20, 1, tzinfo=UTC)
SHADOW_START = "2026-08-19"


class Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeS3:
    def __init__(self, *, sector="Energy"):
        self.payloads = {
            "company_liquidity_eligibility.json": {
                "schema_version": "2026-08-19-v1",
                "source": "OVTLYR_30_DAY_AVG_VOLUME",
                "source_file": "OVTLYR_2026-08-21.csv",
                "source_date": "2026-08-21",
                "generated_at": "2026-08-21T13:39:44+00:00",
                "company_min_average_volume": 1_500_000.0,
                "company_threshold_semantics": "STRICTLY_GREATER_THAN",
                "rows": [
                    {
                        "symbol": "DINO",
                        "security_type": "COMPANY_EQUITY",
                        "status": "ELIGIBLE",
                        "detail": "STRICTLY_ABOVE_THRESHOLD",
                        "average_daily_share_volume_30d": 2_500_000.0,
                        "actionable_liquidity": True,
                    }
                ],
                "trading_authorized": False,
                "live_trading_enabled": False,
            },
            "shortlist.json": [
                {
                    "symbol": "DINO",
                    "sector": sector,
                }
            ],
            "summary.json": {
                "current_file": "OVTLYR_2026-08-21.csv",
                "trading_authorized": False,
                "live_trading_enabled": False,
            },
        }

    def get_object(self, *, Bucket, Key):
        name = Key.rsplit("/", 1)[-1]
        return {"Body": Body(self.payloads[name])}


class AccountPaperLedger(PaperLedger):
    def __init__(self, root, account_id):
        super().__init__(root)
        self.account_id = account_id


def store(*, sector="Energy"):
    return S3ActionableContextStore(
        s3_client=FakeS3(sector=sector),
        bucket="test-bucket",
        prefix="ovtlyr/shortlist/latest",
    )


def ingress(**overrides):
    payload = {
        "schema_version": "2026-08-18-v5",
        "source": "TRADINGVIEW_PINE",
        "signal_id": "DINO-1787342400000-ENTRY_LONG",
        "symbol": "DINO",
        "action": "ENTRY_LONG",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.4",
        "timeframe": "1D",
        "price": 31.0,
        "bar_time": "2026-08-21T20:00:00+00:00",
        "received_at": "2026-08-21T20:01:00+00:00",
        "model_id": PAPER_SHADOW_V24,
        "forward_test_start": SHADOW_START,
        "replay_max_price": 32.0,
        "entry_type": "NORMAL_BREAKOUT",
        "stock_stop_price": 29.0,
        "average_daily_dollar_volume": 75_000_000.0,
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
    }
    payload.update(overrides)
    return payload


def test_server_shortlist_sector_overrides_missing_or_untrusted_ingress_sector():
    canonical = store()

    enriched, evidence = enrich_entry_sector(
        ingress(sector="Technology"),
        canonical,
    )

    assert enriched["sector"] == "Energy"
    assert evidence == {
        "symbol": "DINO",
        "sector": "Energy",
        "source_file": "OVTLYR_2026-08-21.csv",
        "authority": "SERVER_ACTIONABLE_SHORTLIST",
        "status": "VERIFIED",
    }


def test_unverified_server_sector_fails_closed_before_portfolio_risk():
    canonical = store(sector="Unknown Vendor Sector")

    enriched, evidence = enrich_entry_sector(ingress(), canonical)

    assert enriched["sector"] == ""
    assert evidence["authority"] == "SERVER_ACTIONABLE_SHORTLIST"
    assert evidence["status"] == "DATA_ERROR"
    assert evidence["error_code"] == "SECTOR_DATA_UNVERIFIED"


def test_shadow_dino_entry_uses_server_sector_and_reaches_stock_paper_model_fill(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)
    ledgers = {}

    def ledger_factory(account_id):
        ledger = AccountPaperLedger(tmp_path / account_id, account_id)
        ledgers[account_id] = ledger
        return ledger

    executor = ShadowRoutedPinePaperExecutor(
        paper_nav=1_000_000.0,
        secrets_client=object(),
        ledger_factory=ledger_factory,
        liquidity_store=store(),
    )

    result = executor.execute(ingress(), now=NOW)

    assert result["disposition"] == "EXECUTED_PAPER"
    assert result["reason"] == "PAPER_STOCK_POSITION_OPENED"
    assert result["paper_account_id"] == PAPER_SHADOW_V24
    assert result["context"]["sector_evidence"]["sector"] == "Energy"
    assert result["context"]["sector_evidence"]["authority"] == (
        "SERVER_ACTIONABLE_SHORTLIST"
    )
    assert result["context"]["fill_model"] == (
        "CONFIRMED_SIGNAL_PRICE_PROCESS_ORDERS_ON_CLOSE"
    )
    trade = ledgers[PAPER_SHADOW_V24].find_open("DINO")[0]
    assert trade.instrument.value == "STOCK"
    assert trade.entry_price == 31.0
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_shadow_entry_with_bad_server_sector_keeps_exact_fail_closed_reason(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", SHADOW_START)

    executor = ShadowRoutedPinePaperExecutor(
        paper_nav=1_000_000.0,
        secrets_client=object(),
        ledger_factory=lambda account_id: AccountPaperLedger(
            tmp_path / account_id,
            account_id,
        ),
        liquidity_store=store(sector="Unknown Vendor Sector"),
    )

    result = executor.execute(ingress(), now=NOW)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "SECTOR_DATA_UNVERIFIED"
    assert result["context"]["sector_evidence"]["status"] == "DATA_ERROR"
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
