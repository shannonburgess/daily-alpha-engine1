from daily_alpha.ovtlyr import (
    OvtlyrRecord,
    OvtlyrStatus,
    compare_universes,
    summarize_sector_rotation,
)


def record(symbol, signal="BUY", **values):
    return OvtlyrRecord(symbol=symbol, signal=signal, **values)


def status_map(previous, current):
    return {item.symbol: item.status for item in compare_universes(previous, current)}


def test_status_classification_precedence():
    previous = [
        record("NEW"),
        record("LEAD", trend="UP", momentum="STRONG"),
        record("DROP"),
        record("RE"),
        record("WATCH"),
        record("WEAK"),
    ]
    current = [
        record("NEW"),
        record("LEAD", trend="UP", momentum="STRONG"),
        record("EMERGE", trend="UP", momentum="ACCELERATING"),
        record("FRESH"),
        record("RE", setup="RE-ENTRY"),
        record("WATCH", entry_watch=True),
        record("WEAK", momentum="DETERIORATING"),
    ]

    statuses = status_map(previous, current)

    assert statuses["EMERGE"] == OvtlyrStatus.EMERGING
    assert statuses["FRESH"] == OvtlyrStatus.NEW_BUY
    assert statuses["LEAD"] == OvtlyrStatus.LEADER
    assert statuses["RE"] == OvtlyrStatus.RE_ENTRY
    assert statuses["WATCH"] == OvtlyrStatus.ENTRY_WATCH
    assert statuses["WEAK"] == OvtlyrStatus.DETERIORATING
    assert statuses["DROP"] == OvtlyrStatus.REMOVED


def test_sector_rotation_penalizes_deterioration_and_removals():
    previous = [
        record("A", sector="Tech"),
        record("B", sector="Energy"),
    ]
    current = [
        record("A", sector="Tech", trend="UP", momentum="STRONG"),
        record("C", sector="Tech", trend="UP", momentum="ACCELERATING"),
    ]

    classified = compare_universes(previous, current)
    sectors = summarize_sector_rotation(classified)

    assert sectors[0].sector == "Tech"
    assert sectors[0].net_score > 0
    energy = next(item for item in sectors if item.sector == "Energy")
    assert energy.removed == 1
    assert energy.net_score < 0


def test_optionability_is_reported_separately():
    classified = compare_universes(
        [],
        [record("A", optionable=False), record("B", optionable=True)],
    )

    by_symbol = {item.symbol: item for item in classified}
    assert by_symbol["A"].optionable is False
    assert by_symbol["B"].optionable is True
