from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENSOR_DIR = ROOT / "tradingview" / "agentic_intraday_mu_v1"


def read(name: str) -> str:
    return (SENSOR_DIR / name).read_text()


def test_agentic_intraday_sensor_files_are_indicators_and_paper_only():
    files = (
        "mu_agentic_15m_context_v1.pine",
        "mu_agentic_2m_opening_v1.pine",
        "mu_agentic_5m_continuation_v1.pine",
    )
    for name in files:
        source = read(name)
        assert "//@version=6" in source
        assert "indicator(" in source
        assert "strategy(" not in source
        assert "strategy.entry" not in source
        assert "strategy.close" not in source
        assert "PAPER_AGENTIC_INTRADAY_V1" in source
        assert '\\"trading_authorized\\":false' in source
        assert '\\"live_trading_enabled\\":false' in source
        assert '\\"requires_server_enrichment\\":true' in source
        assert "enableAlerts = input.bool(false" in source
        assert "alert.freq_once_per_bar_close" in source


def test_15m_context_sensor_emits_context_and_sector_evidence_only():
    source = read("mu_agentic_15m_context_v1.pine")
    assert 'timeframe.multiplier == 15' in source
    assert '\\"sensor_type\\":\\"CONTEXT_15M\\"' in source
    assert '\\"context_15m_approved\\"' in source
    assert '\\"sector_context_approved\\"' in source
    assert 'input.symbol("AMEX:SOXX"' in source


def test_2m_opening_sensor_preserves_frozen_opening_window_and_liquidity_evidence():
    source = read("mu_agentic_2m_opening_v1.pine")
    assert 'timeframe.multiplier == 2' in source
    assert '"0930-0936"' in source
    assert '"0936-1000"' in source
    assert '\\"sensor_type\\":\\"OPENING_2M\\"' in source
    assert '\\"opening_range_established\\"' in source
    assert '\\"opening_range_high\\"' in source
    assert '\\"average_daily_share_volume\\"' in source
    assert 'ta.sma(volume, 30)[1]' in source


def test_5m_continuation_sensor_emits_required_momentum_inputs():
    source = read("mu_agentic_5m_continuation_v1.pine")
    assert 'timeframe.multiplier == 5' in source
    assert '"1000-1530"' in source
    assert '\\"sensor_type\\":\\"STANDARD_5M\\"' in source
    assert '\\"continuation_high\\"' in source
    assert '\\"ema9\\"' in source
    assert '\\"ema20\\"' in source
    assert '\\"relative_volume\\"' in source
    assert '\\"relative_strength_pct\\"' in source


def test_sensor_docs_forbid_alert_installation_before_stage6_ingress():
    readme = read("README.md")
    assert "Do not create TradingView alerts until the Stage-6 intraday ingress" in readme
    assert "No secret belongs in GitHub" in readme
    assert "SH24/SH25" in readme
