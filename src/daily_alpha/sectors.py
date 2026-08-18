"""Canonical sector classification and controlled symbol corrections."""

from __future__ import annotations

CANONICAL_SECTORS = frozenset({
    "Communication Services", "Consumer Discretionary", "Consumer Staples",
    "Energy", "Financials", "Health Care", "Industrials",
    "Information Technology", "Materials", "Real Estate", "Utilities",
})

_SECTOR_ALIASES = {
    "basic materials": "Materials",
    "communication": "Communication Services",
    "communications": "Communication Services",
    "communication services": "Communication Services",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "staples": "Consumer Staples",
    "energy": "Energy",
    "financial": "Financials",
    "financial services": "Financials",
    "financials": "Financials",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "industrial": "Industrials",
    "industrials": "Industrials",
    "information technology": "Information Technology",
    "materials": "Materials",
    "real estate": "Real Estate",
    "tech": "Information Technology",
    "technology": "Information Technology",
    "utilities": "Utilities",
}

# Reviewed corrections take precedence over vendor-reported sector.
SYMBOL_SECTOR_OVERRIDES = {
    "AMZN": "Consumer Discretionary",
    "GOOG": "Communication Services",
    "GOOGL": "Communication Services",
    "META": "Communication Services",
    "NFLX": "Communication Services",
    "PYPL": "Financials",
    "TSLA": "Consumer Discretionary",
}

def normalize_sector(value: str | None) -> str:
    """Return one of the 11 canonical sector names, or Unknown."""
    normalized = " ".join(str(value or "").strip().lower().replace("&", "and").split())
    return _SECTOR_ALIASES.get(normalized, "Unknown")

def resolve_sector(symbol: str, reported_sector: str | None) -> str:
    """Apply a reviewed symbol override, otherwise normalize the vendor value."""
    ticker = str(symbol or "").strip().upper()
    return SYMBOL_SECTOR_OVERRIDES.get(ticker, normalize_sector(reported_sector))

def is_verified_sector(value: str | None) -> bool:
    return str(value or "").strip() in CANONICAL_SECTORS
