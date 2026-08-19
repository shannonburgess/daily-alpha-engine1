from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V24_SHADOW = REPO_ROOT / "tradingview" / "da_turtle_20_10_v2_4_shadow_control.pine"


def _source() -> str:
    return V24_SHADOW.read_text(encoding="utf-8")


def test_v24_shadow_source_is_versioned_and_fail_closed_by_default() -> None:
    source = _source()

    assert 'shorttitle="DA-T20/10-SH24"' in source
    assert 'modelId = "PAPER_SHADOW_V24"' in source
    assert 'enableShadowForwardTest = input.bool(false' in source
    assert 'enableWebhookOrders = input.bool(false' in source
    assert 'webhookSecret = input.string("", "Webhook Secret"' in source
    assert 'strategy_version\\\":\\\"2.4' in source


def test_v24_shadow_source_emits_common_start_on_every_lifecycle_message() -> None:
    source = _source()

    assert 'shadowForwardStartIso = str.format_time(' in source
    assert '"America/New_York"' in source
    assert '\\\"forward_test_start\\\":\\\"' in source
    assert source.count("shadowCommon") >= 6
    assert 'time >= shadowForwardStart' in source


def test_v24_shadow_entry_emits_explicit_deterministic_replay_ceiling() -> None:
    source = _source()

    assert 'replayMaxDistanceAtr = input.float(1.0' in source
    assert 'entryReplayMaxPrice = math.max(close, upper20 + atr * replayMaxDistanceAtr)' in source
    assert '\\\"replay_max_price\\\":' in source
    assert 'str.tostring(entryReplayMaxPrice)' in source


def test_v24_shadow_source_preserves_audited_control_defaults() -> None:
    source = _source()

    expected_fragments = (
        'entryLen = input.int(20',
        'exitLen = input.int(10',
        'breakoutMode = input.string("Close"',
        'atrLen = input.int(10',
        'minFactor = input.float(2.0',
        'maxFactor = input.float(4.0',
        'efficiencyLen = input.int(20',
        'minPriorBullBars = input.int(2',
        'maxEntryRsi = input.float(80.0',
        'failedBreakoutBars = input.int(3',
        'minAdx = input.float(25.0',
        'minTrendEfficiency = input.float(0.20',
        'minUnderlyingPrice = input.float(25.0',
        'minEarningsGapPct = input.float(5.0',
        'minEarningsGapAtr = input.float(1.5',
        'minGapCloseLocation = input.float(0.70',
        'minEarlyGapCloseLocation = input.float(0.60',
        'minGapRetention = input.float(0.70',
        'minGapRelativeVolume = input.float(1.5',
        'maxEarningsRsi = input.float(85.0',
        'add1Atr = input.float(1.0',
        'add2Atr = input.float(2.0',
        'harvestAtr = input.float(3.0',
        'useBreakEvenAfterHarvest = input.bool(true',
    )

    for fragment in expected_fragments:
        assert fragment in source
