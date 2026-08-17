from daily_alpha.scenario_backtest import throttle_multiplier


def test_throttle_bands():
    assert throttle_multiplier(0.00) == (1.0, True)
    assert throttle_multiplier(0.06) == (0.75, True)
    assert throttle_multiplier(0.09) == (0.50, False)
    assert throttle_multiplier(0.13) == (0.25, False)
    assert throttle_multiplier(0.16) == (0.0, False)
