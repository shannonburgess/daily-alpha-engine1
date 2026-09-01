"""Persistent research-only manual watchlist support.

Manual watch symbols are visibility requests, never trade authorizations. The
builder joins a pinned watchlist to the full OVTLYR classification universe and,
when available, the ORATS-enriched shortlist. A missing classification or an
explicit ORATS data failure stays visible as DATA_ERROR rather than being
silently dropped or converted into an executable setup.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any


class ManualWatchlistError(ValueError):
    """Raised when manual-watch configuration or source data is invalid."""


@dataclass(frozen=True)
class ManualWatchSpec:
    symbol: str
    label: str = ""
    reason: str = "USER_PINNED"
    enabled: bool = True

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
            raise ManualWatchlistError("MANUAL_WATCH_SYMBOL_INVALID")
        if not self.reason.strip():
            raise ManualWatchlistError("MANUAL_WATCH_REASON_REQUIRED")
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True)
class ManualWatchSnapshot:
    symbol: str
    label: str
    watch_reason: str
    current_daily_alpha_status: str
    signal: str
    signal_date: str
    trend: str
    momentum: str
    sector: str
    industry: str
    optionable: bool | None
    orats_status: str
    orats_reason: str
    selected_option_contract: str
    data_status: str
    status_reason: str
    paper_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_manual_watchlist(path: str | Path) -> tuple[ManualWatchSpec, ...]:
    """Load a versioned watchlist and fail closed on malformed/duplicate entries."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualWatchlistError("MANUAL_WATCHLIST_READ_FAILED") from exc
    if not isinstance(payload, Mapping):
        raise ManualWatchlistError("MANUAL_WATCHLIST_MUST_BE_OBJECT")
    if not str(payload.get("schema_version", "")).strip():
        raise ManualWatchlistError("MANUAL_WATCHLIST_SCHEMA_REQUIRED")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ManualWatchlistError("MANUAL_WATCHLIST_ENTRIES_REQUIRED")

    specs: list[ManualWatchSpec] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise ManualWatchlistError("MANUAL_WATCH_ENTRY_MUST_BE_OBJECT")
        spec = ManualWatchSpec(
            symbol=str(raw.get("symbol", "")),
            label=str(raw.get("label", "")),
            reason=str(raw.get("reason", "USER_PINNED")),
            enabled=_bool_value(raw.get("enabled", True)),
        )
        if spec.symbol in seen:
            raise ManualWatchlistError("MANUAL_WATCH_DUPLICATE_SYMBOL")
        seen.add(spec.symbol)
        if spec.enabled:
            specs.append(spec)
    return tuple(specs)


def build_manual_watch_snapshots(
    specs: Sequence[ManualWatchSpec],
    *,
    classifications: Sequence[Any],
    shortlist: Sequence[Any] = (),
) -> tuple[ManualWatchSnapshot, ...]:
    """Join pinned symbols to full classifications and optional ORATS enrichment."""
    classified = _rows_by_symbol(classifications)
    enriched = _rows_by_symbol(shortlist)
    snapshots: list[ManualWatchSnapshot] = []

    for spec in specs:
        row = classified.get(spec.symbol)
        short = enriched.get(spec.symbol)
        if row is None:
            snapshots.append(
                ManualWatchSnapshot(
                    symbol=spec.symbol,
                    label=spec.label,
                    watch_reason=spec.reason,
                    current_daily_alpha_status="UNKNOWN",
                    signal="UNKNOWN",
                    signal_date="",
                    trend="UNKNOWN",
                    momentum="UNKNOWN",
                    sector="UNKNOWN",
                    industry="",
                    optionable=None,
                    orats_status="NOT_EVALUATED",
                    orats_reason="CURRENT_CLASSIFICATION_MISSING",
                    selected_option_contract="",
                    data_status="DATA_ERROR",
                    status_reason="CURRENT_CLASSIFICATION_MISSING",
                )
            )
            continue

        orats_status = "NOT_ENRICHED_THIS_RUN"
        orats_reason = "NOT_IN_ORATS_REQUEST_SET"
        contract = ""
        data_status = "PASS"
        if short is not None:
            orats_status = str(short.get("orats_status", "UNKNOWN") or "UNKNOWN").upper()
            orats_reason = str(short.get("orats_reason", "") or "UNKNOWN")
            if orats_status == "DATA_ERROR":
                data_status = "DATA_ERROR"
            expiration = str(short.get("selected_expiration", "") or "").strip()
            if expiration:
                contract = " ".join(
                    value
                    for value in (
                        expiration,
                        str(short.get("selected_option_type", "") or "").strip(),
                        str(short.get("selected_strike", "") or "").strip(),
                    )
                    if value
                )

        snapshots.append(
            ManualWatchSnapshot(
                symbol=spec.symbol,
                label=spec.label,
                watch_reason=spec.reason,
                current_daily_alpha_status=str(row.get("status", "UNKNOWN") or "UNKNOWN"),
                signal=str(row.get("signal", "UNKNOWN") or "UNKNOWN"),
                signal_date=str(row.get("signal_date", "") or ""),
                trend=str(row.get("trend", "UNKNOWN") or "UNKNOWN"),
                momentum=str(row.get("momentum", "UNKNOWN") or "UNKNOWN"),
                sector=str(row.get("sector", "UNKNOWN") or "UNKNOWN"),
                industry=str(row.get("industry", "") or ""),
                optionable=_optional_bool(row.get("optionable")),
                orats_status=orats_status,
                orats_reason=orats_reason,
                selected_option_contract=contract,
                data_status=data_status,
                status_reason=str(row.get("reason", "") or "CLASSIFICATION_AVAILABLE"),
            )
        )
    return tuple(snapshots)


def render_manual_watch_section(items: Sequence[ManualWatchSnapshot]) -> str:
    """Render a standalone newsletter fragment without implying recommendation."""
    if not items:
        return ""
    rows = "".join(
        "<tr>"
        f"<td><strong>{escape(item.symbol)}</strong>"
        f"<br><small>{escape(item.label)}</small></td>"
        f"<td>MANUAL WATCH<br><small>{escape(item.watch_reason)}</small></td>"
        f"<td>{escape(item.current_daily_alpha_status)}"
        f"<br><small>Signal: {escape(item.signal)}</small></td>"
        f"<td>{escape(item.trend)} / {escape(item.momentum)}</td>"
        f"<td>{escape(item.sector)}<br><small>{escape(item.industry)}</small></td>"
        f"<td>{escape(item.orats_status)}"
        f"<br><small>{escape(item.orats_reason)}</small>"
        + (
            f"<br><small>{escape(item.selected_option_contract)}</small>"
            if item.selected_option_contract
            else ""
        )
        + "</td>"
        f"<td>{escape(item.data_status)}<br><small>{escape(item.status_reason)}</small></td>"
        "</tr>"
        for item in items
    )
    return (
        '<section class="report-section manual-watch">'
        "<h2>Manual Watch — Research Only</h2>"
        '<p class="section-note">Pinned names remain visible until explicitly removed. '
        "Manual-watch status is not an entry signal and cannot bypass Pine, OVTLYR, "
        "ORATS, earnings, portfolio-risk, no-chase, or execution gates.</p>"
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Symbol</th><th>Watch status</th><th>Daily Alpha state</th>"
        "<th>Trend / Momentum</th><th>Sector / Industry</th><th>Options data</th>"
        "<th>Data status</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div></section>"
    )


def _rows_by_symbol(rows: Sequence[Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol", "")).strip().upper()
        if symbol and symbol not in result:
            result[symbol] = raw
    return result


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise ManualWatchlistError("MANUAL_WATCH_ENABLED_INVALID")


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None
