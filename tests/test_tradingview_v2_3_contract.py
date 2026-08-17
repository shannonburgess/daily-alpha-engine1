from pathlib import Path


def test_v2_3_pine_emits_full_runner_and_fallback_metadata():
    pine = Path("tradingview/da_turtle_20_10_v2_3.pine").read_text()

    assert 'strategy_version\\\":\\\"2.3' in pine
    assert '\\\"action\\\":\\\"ENTRY_LONG\\\"' in pine
    assert '\\\"action\\\":\\\"ADD\\\"' in pine
    assert '\\\"runner_stage\\\":\\\"ADD_1_ATR\\\"' in pine
    assert '\\\"runner_stage\\\":\\\"ADD_2_ATR\\\"' in pine
    assert '\\\"action\\\":\\\"PARTIAL\\\"' in pine
    assert '\\\"runner_stage\\\":\\\"HARVEST_3_ATR\\\"' in pine
    assert '\\\"action\\\":\\\"EXIT\\\"' in pine
    assert '\\\"position_fraction\\\":0.25' in pine
    assert '\\\"stock_stop_price\\\":' in pine
    assert '\\\"average_daily_dollar_volume\\\":' in pine
    assert 'alert_message=enableWebhookOrders ? add1Message : ""' in pine
    assert 'alert_message=enableWebhookOrders ? add2Message : ""' in pine
    assert 'alert_message=enableWebhookOrders ? partialMessage : ""' in pine
