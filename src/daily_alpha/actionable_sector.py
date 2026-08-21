"""Server-authoritative sector context for stock-primary PAPER entries.

TradingView/Pine ingress intentionally carries only signal facts and must not be
trusted as the authority for portfolio-control metadata.  This module binds an
ENTRY_LONG to the same current server-published actionable shortlist and
liquidity source before the existing sector/portfolio-risk gates run.

The helper never authorizes a trade.  Missing, inconsistent, or unverified sector
evidence is represented as an empty sector so the downstream canonical executor
fails closed with ``SECTOR_DATA_UNVERIFIED``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .equity_liquidity import S3ActionableLiquidityStore
from .sectors import is_verified_sector, resolve_sector

SECTOR_AUTHORITY = "SERVER_ACTIONABLE_SHORTLIST"


class ActionableSectorError(RuntimeError):
    """Current server-side sector evidence could not be verified."""


@dataclass(frozen=True)
class ActionableSectorEvidence:
    symbol: str
    sector: str
    source_file: str
    authority: str = SECTOR_AUTHORITY

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class S3ActionableContextStore(S3ActionableLiquidityStore):
    """Canonical liquidity store with sector evidence from the same publication."""

    def sector_evidence(self, symbol: str) -> ActionableSectorEvidence:
        ticker = str(symbol or "").strip().upper()
        if not ticker:
            raise ActionableSectorError("SECTOR_SYMBOL_REQUIRED")

        snapshot = self._json("company_liquidity_eligibility.json")
        shortlist = self._json("shortlist.json")
        summary = self._json("summary.json")
        if not isinstance(snapshot, Mapping) or not isinstance(summary, Mapping):
            raise ActionableSectorError("SECTOR_PUBLICATION_METADATA_INVALID")
        if not isinstance(shortlist, list):
            raise ActionableSectorError("SECTOR_SHORTLIST_INVALID")
        if (
            snapshot.get("trading_authorized") is not False
            or snapshot.get("live_trading_enabled") is not False
            or summary.get("trading_authorized") is not False
            or summary.get("live_trading_enabled") is not False
        ):
            raise ActionableSectorError("SECTOR_PUBLICATION_SAFETY_FLAGS_INVALID")

        source_file = str(summary.get("current_file") or "").strip()
        if not source_file or source_file != str(snapshot.get("source_file") or "").strip():
            raise ActionableSectorError("SECTOR_PUBLICATION_SOURCE_MISMATCH")

        matches = [
            item
            for item in shortlist
            if isinstance(item, Mapping)
            and str(item.get("symbol") or "").strip().upper() == ticker
        ]
        if len(matches) != 1:
            raise ActionableSectorError("SECTOR_SYMBOL_EVIDENCE_MISSING_OR_DUPLICATE")

        sector = resolve_sector(ticker, str(matches[0].get("sector") or ""))
        if not is_verified_sector(sector):
            raise ActionableSectorError("SECTOR_DATA_UNVERIFIED")
        return ActionableSectorEvidence(
            symbol=ticker,
            sector=sector,
            source_file=source_file,
        )


def enrich_entry_sector(
    ingress: Mapping[str, Any],
    store: Any | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Override ENTRY_LONG sector with current server evidence when supported.

    Test/fake liquidity stores that do not expose ``sector_evidence`` retain the
    supplied ingress sector.  The production S3 store is
    :class:`S3ActionableContextStore`, so production entries are server-authoritative.
    """
    enriched = dict(ingress)
    if str(enriched.get("action", "")).upper() != "ENTRY_LONG" or store is None:
        return enriched, None

    resolver = getattr(store, "sector_evidence", None)
    if not callable(resolver):
        return enriched, None

    symbol = str(enriched.get("symbol") or "").strip().upper()
    try:
        evidence = resolver(symbol)
    except Exception as exc:  # noqa: BLE001 - execution context must fail closed
        enriched["sector"] = ""
        return enriched, {
            "authority": SECTOR_AUTHORITY,
            "status": "DATA_ERROR",
            "symbol": symbol,
            "error_code": str(exc) or type(exc).__name__,
        }

    enriched["sector"] = evidence.sector
    return enriched, {
        **evidence.to_dict(),
        "status": "VERIFIED",
    }


def attach_sector_evidence(
    execution: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Attach non-secret sector provenance to an execution/no-trade result."""
    result = dict(execution)
    if evidence is None:
        return result
    context = dict(result.get("context") or {})
    context["sector_evidence"] = dict(evidence)
    result["context"] = context
    return result
