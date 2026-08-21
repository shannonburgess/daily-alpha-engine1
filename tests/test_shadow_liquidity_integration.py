from datetime import UTC, datetime

from daily_alpha.equity_liquidity import LiquidityDecision
from daily_alpha.shadow_routing import PAPER_SHADOW_V25, ShadowRoutedPinePaperExecutor


class BlockedLiquidityStore:
    def evaluate(self, symbol, *, as_of):
        assert symbol == "ILLIQ"
        assert as_of.tzinfo is not None
        return LiquidityDecision(
            symbol=symbol,
            allowed=False,
            security_type="COMPANY_EQUITY",
            reason="LIQUIDITY_FILTERED",
            detail="AT_OR_BELOW_THRESHOLD",
            average_daily_share_volume_30d=1_500_000.0,
            source_date="2026-08-19",
        )


class FakeLedger:
    def find_open(self, symbol):
        return []


def _ingress():
    return {
        "signal_id": "V25-LIQUIDITY-BLOCK-1",
        "symbol": "ILLIQ",
        "action": "ENTRY_LONG",
        "source": "TRADINGVIEW_PINE",
        "strategy_version": "2.5",
        "model_id": PAPER_SHADOW_V25,
        "forward_test_start": "2026-08-19",
        "replay_max_price": 25.0,
    }


def _executor(monkeypatch):
    monkeypatch.setenv("DAILY_ALPHA_SHADOW_FORWARD_START", "2026-08-19")
    return ShadowRoutedPinePaperExecutor(
        paper_nav=100_000.0,
        secrets_client=object(),
        ledger_factory=lambda account_id: FakeLedger(),
        liquidity_store=BlockedLiquidityStore(),
    )


def test_shadow_entry_at_exact_threshold_fails_closed_and_keeps_model_identity(monkeypatch):
    now = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    result = _executor(monkeypatch).execute(_ingress(), now=now)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "LIQUIDITY_FILTERED"
    assert result["paper_execution_triggered"] is False
    assert result["paper_ledger_updated"] is False
    assert result["paper_account_id"] == PAPER_SHADOW_V25
    assert result["model_id"] == PAPER_SHADOW_V25
    assert result["forward_test_start"] == "2026-08-19"
    assert result["context"]["liquidity_gate"]["average_daily_share_volume_30d"] == 1_500_000.0
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False


def test_shadow_armed_replay_rechecks_liquidity_before_execution(monkeypatch):
    now = datetime(2026, 8, 19, 20, 5, tzinfo=UTC)
    result = _executor(monkeypatch).replay_armed(_ingress(), now=now)

    assert result["disposition"] == "NO_TRADE"
    assert result["reason"] == "LIQUIDITY_FILTERED"
    assert result["paper_account_id"] == PAPER_SHADOW_V25
    assert result["model_id"] == PAPER_SHADOW_V25
    assert result["trading_authorized"] is False
    assert result["live_trading_enabled"] is False
