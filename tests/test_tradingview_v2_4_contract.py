from pathlib import Path


def test_v2_4_pine_separates_normal_and_earnings_entries():
    pine = Path("tradingview/da_turtle_20_10_v2_4.pine").read_text()

    assert 'strategy_version\\\":\\\"2.4' in pine
    assert "request.earnings(syminfo.tickerid" in pine
    assert 'entryType = earningsGapGoEntry ? "EARNINGS_GAP_GO"' in pine
    assert '"NORMAL_BREAKOUT"' in pine
    assert '"EARNINGS_GAP_GO_EARLY"' in pine
    assert '"EARNINGS_GAP_CRAP"' in pine
    assert '"EARNINGS_WAIT"' in pine
    assert "normalTrendMature" in pine
    assert "not isEarningsUpsideGap" in pine
    assert "earningsGapGoEntry" in pine
    assert '\\\"entry_type\\\":\\\"' in pine
    assert '\\\"earnings_gap_class\\\":\\\"' in pine
    assert '\\\"earnings_gap_pct\\\":' in pine
    assert '\\\"earnings_gap_atr\\\":' in pine
    assert '\\\"earnings_close_location\\\":' in pine
    assert '\\\"earnings_gap_retention\\\":' in pine
    assert '\\\"earnings_relative_volume\\\":' in pine


def test_gap_go_uses_70_percent_threshold_and_early_band_is_watch_only():
    pine = Path("tradingview/da_turtle_20_10_v2_4.pine").read_text()

    assert 'minGapCloseLocation = input.float(0.70' in pine
    assert 'minEarlyGapCloseLocation = input.float(0.60' in pine
    assert "earningsGapGoEarly =" in pine
    assert 'title="EARNINGS GAP GO EARLY"' in pine
    assert 'text="WATCH\\nGAP EARLY"' in pine
    assert 'entryType = earningsGapGoEntry ? "EARNINGS_GAP_GO"' in pine
    assert 'earningsGapGoEarly ? "EARNINGS_GAP_GO_EARLY"' in pine
    assert 'entryType = earningsGapGoEarly ? "EARNINGS_GAP_GO_EARLY"' not in pine
    assert "longEntry = normalLongEntry or earningsGapGoEntry" in pine


def test_gap_go_starts_half_size_and_runner_adds_still_require_adx():
    pine = Path("tradingview/da_turtle_20_10_v2_4.pine").read_text()

    assert 'strategy.entry("L", strategy.long, qty=2, comment=entryType' in pine
    assert "runnerTrendOK = trendState == 1 and (not useAdxFilter or adxEntry >= minAdx)" in pine
    assert 'strategy.entry("L", strategy.long, qty=1, comment=activeEntryType + " ADD1"' in pine
    assert 'strategy.entry("L", strategy.long, qty=1, comment=activeEntryType + " ADD2"' in pine
