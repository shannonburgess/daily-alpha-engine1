from pathlib import Path


def test_canonical_pine_emits_runner_webhook_actions():
    pine = Path("tradingview/da_turtle_20_10_v1_9.pine").read_text()

    assert '\\"action\\":\\"ENTRY_LONG\\"' in pine
    assert '\\"action\\":\\"ADD\\"' in pine
    assert '\\"runner_stage\\":\\"ADD_1_ATR\\"' in pine
    assert '\\"runner_stage\\":\\"ADD_2_ATR\\"' in pine
    assert '\\"action\\":\\"PARTIAL\\"' in pine
    assert '\\"runner_stage\\":\\"HARVEST_3_ATR\\"' in pine
    assert '\\"action\\":\\"EXIT\\"' in pine
    assert '\\"position_fraction\\":0.25' in pine
    assert 'alert_message=enableWebhookOrders ? add1Message : ""' in pine
    assert 'alert_message=enableWebhookOrders ? add2Message : ""' in pine
    assert 'alert_message=enableWebhookOrders ? partialMessage : ""' in pine
