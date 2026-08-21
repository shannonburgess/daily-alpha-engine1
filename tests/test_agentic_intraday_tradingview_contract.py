from pathlib import Path

SCRIPT = Path("tradingview/da_agentic_intraday_mu_v1_sensor.pine")


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_agentic_sensor_is_indicator_only_and_cannot_place_orders():
    text = source()

    assert 'indicator("Daily Alpha Agentic Intraday MU V1 Sensor"' in text
    assert "strategy(" not in text
    assert "strategy.entry" not in text
    assert "strategy.close" not in text
    assert "strategy.order" not in text
    assert "pyramiding=" not in text


def test_agentic_sensor_is_hard_isolated_to_mu_paper_account():
    text = source()

    assert 'string PILOT_SYMBOL = "MU"' in text
    assert 'string PAPER_ACCOUNT = "PAPER_AGENTIC_INTRADAY_V1"' in text
    assert 'string SENSOR_SOURCE = "TRADINGVIEW_AGENTIC_INTRADAY"' in text
    assert '"instrument\\\":\\\"STOCK' in text
    assert '"paper_only\\\":true' in text
    assert '"trading_authorized\\\":false' in text
    assert '"live_trading_enabled\\\":false' in text
    assert "PAPER_SHADOW_V24" not in text
    assert "PAPER_SHADOW_V25" not in text
    assert '"instrument\\\":\\\"OPTION' not in text


def test_agentic_sensor_preserves_two_minute_then_five_minute_clock_contract():
    text = source()

    assert '"0930-1000"' in text
    assert '"1000-1530"' in text
    assert '"1530-1550"' in text
    assert '"1550-1600"' in text
    assert 'phase == "OPENING_2M"' in text
    assert 'phase == "STANDARD_5M"' in text
    assert 'phase == "MANAGEMENT_ONLY"' in text
    assert 'phase == "FLATTEN_ONLY"' in text
    assert "is2m ? inOpening2m" in text
    assert "is5m ? (inStandard5m or inManagementOnly or inFlattenOnly)" in text


def test_agentic_sensor_emits_raw_context_not_portfolio_authorization():
    text = source()

    assert 'eventType = is15m ? "CONTEXT_15M_BAR"' in text
    assert '"EXECUTION_2M_BAR"' in text
    assert '"EXECUTION_5M_BAR"' in text
    assert '"MANAGEMENT_5M_BAR"' in text
    assert '"FLATTEN_5M_BAR"' in text
    assert '"average_daily_share_volume_30\\\":' in text
    assert '"relative_strength_qqq_pct\\\":' in text
    assert '"relative_strength_smh_pct\\\":' in text
    assert '"session_high_prior\\\":' in text
    assert '"high_3_prior\\\":' in text
    assert "daily_context_approved" not in text
    assert "context_15m_approved" not in text
    assert "sector_context_approved" not in text


def test_agentic_sensor_requires_explicit_alert_enable_and_confirmed_bars():
    text = source()

    assert 'enableSensorAlerts = input.bool(false, "Enable PAPER Sensor Alerts"' in text
    assert "barstate.isconfirmed" in text
    assert "alert(sensorMessage, alert.freq_once_per_bar_close)" in text
    assert "webhookSecret = input.string" in text
