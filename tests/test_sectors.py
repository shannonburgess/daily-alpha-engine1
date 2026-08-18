from daily_alpha.sectors import (
    is_verified_sector,
    normalize_sector,
    resolve_sector,
)


def test_sector_aliases_are_canonicalized():
    assert normalize_sector("Tech") == "Information Technology"
    assert normalize_sector("Consumer Cyclical") == "Consumer Discretionary"
    assert normalize_sector("Basic Materials") == "Materials"
    assert normalize_sector("Discretionary") == "Consumer Discretionary"
    assert normalize_sector("Staples") == "Consumer Staples"
    assert normalize_sector("Communication") == "Communication Services"

def test_reviewed_symbol_override_wins_over_bad_vendor_sector():
    assert resolve_sector("META", "Information Technology") == "Communication Services"
    assert resolve_sector("TSLA", "Industrials") == "Consumer Discretionary"

def test_unknown_sector_is_not_verified():
    assert resolve_sector("XYZ", "Unmapped Vendor Group") == "Unknown"
    assert is_verified_sector("Unknown") is False
    assert is_verified_sector("Financials") is True
