"""Research-only SH24 source-side diagnostics for exact zero-trade reconciliation.

The AWS PAPER-shadow monitor can prove whether a strategy-origin event reached the
backend, but TradingView does not expose private per-alert symbol/evaluation coverage
through a supported API. This module adds an independent, point-in-time SH24 control
evaluation from approved daily bars so a post-close zero-event day can be separated
without pretending that full-universe source expectations prove alert coverage.

It never authorizes a trade, never mutates TradingView, and does not diagnose SH25.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from daily_alpha.backtest import Bar, indicators
from daily_alpha.orats_historical_transport import HistoricalOratsAuthError
from daily_alpha.orats_history_fetch import fetch_daily_earnings_rows

PINE_SOURCE_PATH = "tradingview/da_turtle_20_10_v2_4.pine"
PINE_CONTRACT_MARKERS = (
    'breakoutMode = input.string("Close"',
    'maxEntryRsi = input.float(80.0',
    'minAdx = input.float(25.0',
    'minTrendEfficiency = input.float(0.20',
    'minUnderlyingPrice = input.float(25.0',
    "freshLongBreakout = barstate.isconfirmed",
    "normalTrendMature = nz(bullishTrendBars[1]) >= minPriorBullBars",
    "longEntry = normalLongEntry or earningsGapGoEntry",
)


class TargetBarUnavailable(RuntimeError):
    """Raised when ORATS history is valid but has not published the target close yet."""

    def __init__(self, symbol: str, target_date: date, latest_date: date | None) -> None:
        self.symbol = symbol.upper()
        self.target_date = target_date
        self.latest_date = latest_date
        latest = latest_date.isoformat() if latest_date is not None else "NONE"
        super().__init__(
            f"ORATS_TARGET_BAR_NOT_YET_AVAILABLE:{self.symbol}:"
            f"target={target_date.isoformat()}:latest={latest}"
        )


@dataclass(frozen=True)
class Sh24EntryConfig:
    """Frozen SH24 control defaults mirrored from the reviewed v2.4 Pine source."""

    min_price: float = 25.0
    min_efficiency: float = 0.20
    max_rsi: float = 80.0
    min_adx: float = 25.0
    strategy_version: str = "2.4"
    model_id: str = "PAPER_SHADOW_V24"


DEFAULT_SH24_CONFIG = Sh24EntryConfig()


@dataclass(frozen=True)
class Sh24PointDiagnostic:
    symbol: str
    trade_date: str
    status: str
    entry_type: str
    primary_reason: str
    blockers: tuple[str, ...]
    close: float
    fresh_breakout: bool
    trend_state: int
    normal_trend_mature: bool
    earnings_up_gap: bool
    earnings_gap_go: bool
    efficiency: float | None
    rsi: float | None
    adx: float | None
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def validate_pine_contract(pine_text: str) -> tuple[str, ...]:
    """Return missing source markers that would make the diagnostic unsafe to use."""

    return tuple(marker for marker in PINE_CONTRACT_MARKERS if marker not in pine_text)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def diagnose_sh24_point(
    *,
    symbol: str,
    bar: Bar,
    indicator_row: Mapping[str, Any],
    flat_at_start: bool = True,
    config: Sh24EntryConfig = DEFAULT_SH24_CONFIG,
) -> Sh24PointDiagnostic:
    """Evaluate the frozen SH24 ENTRY gates for one completed daily bar."""

    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    fresh_breakout = indicator_row.get("fresh_breakout") is True
    trend_state = int(indicator_row.get("trend_state") or 0)
    normal_trend_mature = indicator_row.get("normal_trend_mature") is True
    earnings_up_gap = indicator_row.get("is_earnings_up_gap") is True
    earnings_gap_go = indicator_row.get("gap_go") is True
    efficiency = _number(indicator_row.get("efficiency"))
    rsi = _number(indicator_row.get("rsi"))
    adx = _number(indicator_row.get("adx"))

    blockers: list[str] = []
    if not flat_at_start:
        blockers.append("POSITION_NOT_FLAT")
    if not fresh_breakout:
        blockers.append("NO_FRESH_20D_BREAKOUT")

    price_ok = bar.close >= config.min_price
    if not price_ok:
        blockers.append("PRICE_BELOW_SH24_FLOOR")

    if earnings_up_gap:
        if not earnings_gap_go:
            blockers.append("EARNINGS_GAP_NOT_FULL_GO")
        entry_expected = flat_at_start and fresh_breakout and price_ok and earnings_gap_go
        entry_type = "EARNINGS_GAP_GO" if entry_expected else "NONE"
    else:
        if trend_state != 1:
            blockers.append("TREND_NOT_BULLISH")
        if not normal_trend_mature:
            blockers.append("BULL_TREND_NOT_MATURE")
        if efficiency is None:
            blockers.append("EFFICIENCY_UNAVAILABLE")
        elif efficiency < config.min_efficiency:
            blockers.append("TREND_EFFICIENCY_BELOW_MIN")
        if rsi is None:
            blockers.append("RSI_UNAVAILABLE")
        elif rsi > config.max_rsi:
            blockers.append("RSI_ABOVE_ENTRY_CAP")
        if adx is None:
            blockers.append("ADX_UNAVAILABLE")
        elif adx < config.min_adx:
            blockers.append("ADX_BELOW_SH24_MIN")

        entry_expected = (
            flat_at_start
            and fresh_breakout
            and price_ok
            and trend_state == 1
            and normal_trend_mature
            and efficiency is not None
            and efficiency >= config.min_efficiency
            and rsi is not None
            and rsi <= config.max_rsi
            and adx is not None
            and adx >= config.min_adx
        )
        entry_type = "NORMAL_BREAKOUT" if entry_expected else "NONE"

    if entry_expected:
        status = "ENTRY_EXPECTED"
        primary_reason = "SH24_ENTRY_GATES_PASSED"
        blockers = []
    else:
        status = "NO_ENTRY_EXPECTED"
        primary_reason = blockers[0] if blockers else "SH24_ENTRY_GATES_NOT_PASSED"

    return Sh24PointDiagnostic(
        symbol=symbol,
        trade_date=bar.trade_date.isoformat(),
        status=status,
        entry_type=entry_type,
        primary_reason=primary_reason,
        blockers=tuple(blockers),
        close=bar.close,
        fresh_breakout=fresh_breakout,
        trend_state=trend_state,
        normal_trend_mature=normal_trend_mature,
        earnings_up_gap=earnings_up_gap,
        earnings_gap_go=earnings_gap_go,
        efficiency=efficiency,
        rsi=rsi,
        adx=adx,
    )


def diagnose_sh24_history(
    symbol: str,
    bars: list[Bar],
    *,
    target_date: date,
    flat_at_start: bool = True,
) -> Sh24PointDiagnostic:
    """Evaluate SH24 against exactly one completed target daily bar."""

    matches = [index for index, bar in enumerate(bars) if bar.trade_date == target_date]
    if not matches:
        latest_date = max((bar.trade_date for bar in bars), default=None)
        if latest_date is None or latest_date < target_date:
            raise TargetBarUnavailable(symbol, target_date, latest_date)
        raise ValueError(f"expected exactly one {target_date.isoformat()} bar for {symbol}")
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {target_date.isoformat()} bar for {symbol}")
    rows = indicators(bars)
    index = matches[0]
    return diagnose_sh24_point(
        symbol=symbol,
        bar=bars[index],
        indicator_row=rows[index],
        flat_at_start=flat_at_start,
    )


def reconcile_universe(
    diagnostics: Iterable[Sh24PointDiagnostic],
    *,
    received_strategy_symbols: Iterable[str] = (),
    covered_symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Reconcile source expectations without fabricating TradingView alert coverage.

    ``covered_symbols`` must come from durable alert-coverage evidence. When it is
    unavailable, full-universe SH24 expectations are still useful research evidence,
    but absence at AWS cannot be called a missed alert because Pine v2.4 evaluates
    ``syminfo.tickerid`` for the chart/alert instance and TradingView does not expose
    private alert membership through a supported API.
    """

    rows = tuple(sorted(diagnostics, key=lambda row: row.symbol))
    if len({row.symbol for row in rows}) != len(rows):
        raise ValueError("duplicate symbol diagnostics")

    received = {
        str(symbol).strip().upper()
        for symbol in received_strategy_symbols
        if str(symbol).strip()
    }
    expected = {row.symbol for row in rows if row.status == "ENTRY_EXPECTED"}
    data_errors = {row.symbol for row in rows if row.status == "DATA_ERROR"}
    coverage_known = covered_symbols is not None
    covered = (
        {
            str(symbol).strip().upper()
            for symbol in covered_symbols or ()
            if str(symbol).strip()
        }
        if coverage_known
        else set()
    )
    expected_on_covered = expected & covered if coverage_known else set()
    missing_at_aws = expected_on_covered - received
    coverage_unverified = expected - received if not coverage_known else expected - covered
    unexpected_at_aws = received - expected
    blocker_counts: Counter[str] = Counter()
    for row in rows:
        if row.status == "NO_ENTRY_EXPECTED":
            blocker_counts.update(row.blockers)

    if data_errors:
        interpretation = "INCOMPLETE_SH24_SOURCE_DIAGNOSTIC"
    elif missing_at_aws:
        interpretation = "EXPECTED_SH24_ENTRY_NOT_OBSERVED_AT_AWS_BOUNDARY"
    elif coverage_unverified:
        interpretation = "SH24_SOURCE_EXPECTATIONS_FOUND_TRADINGVIEW_COVERAGE_UNVERIFIABLE"
    elif expected:
        interpretation = "SH24_EXPECTED_ENTRIES_RECONCILED_WITH_AWS"
    else:
        interpretation = "NO_SH24_ENTRY_EXPECTED_FROM_APPROVED_DAILY_BARS"

    return {
        "ok": not data_errors,
        "model_id": "PAPER_SHADOW_V24",
        "strategy_version": "2.4",
        "interpretation": interpretation,
        "symbols_evaluated": len(rows),
        "expected_entry_count": len(expected),
        "expected_entry_symbols": sorted(expected),
        "tradingview_coverage_known": coverage_known,
        "covered_symbols": sorted(covered),
        "received_strategy_symbols": sorted(received),
        "expected_but_not_received": sorted(missing_at_aws),
        "expected_without_verifiable_coverage": sorted(coverage_unverified),
        "received_without_sh24_expectation": sorted(unexpected_at_aws),
        "data_error_symbols": sorted(data_errors),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "diagnostics": [asdict(row) for row in rows],
        "coverage_limitations": [
            "SH24_CONTROL_ONLY; SH25 is not inferred from SH24 logic.",
            (
                "Pine v2.4 evaluates syminfo.tickerid for each chart/alert instance; it is not a "
                "multi-symbol universe scanner."
            ),
            (
                "TradingView private per-alert symbol/evaluation coverage is not readable through "
                "a supported API; full-universe source expectations cannot prove a missed alert."
            ),
        ],
        "research_only": True,
        "promotion_authorized": False,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _received_symbols(
    shadow_status: Mapping[str, Any] | None,
    *,
    model_id: str = "PAPER_SHADOW_V24",
) -> set[str]:
    """Read only genuine strategy symbols from the requested isolated shadow book."""

    if not shadow_status:
        return set()
    accounts = shadow_status.get("accounts")
    if not isinstance(accounts, dict):
        return set()
    account = accounts.get(model_id)
    if not isinstance(account, dict):
        return set()
    events = account.get("session_strategy_events")
    if not isinstance(events, list):
        return set()
    return {
        str(event.get("symbol") or "").strip().upper()
        for event in events
        if isinstance(event, dict) and str(event.get("symbol") or "").strip()
    }


def _history_date(value: Any, *, field: str, symbol: str) -> date | None:
    """Parse one ORATS history date while tolerating only an explicit year-zero sentinel.

    ORATS historical endpoints can emit ``0000-00-00``-style rows for unavailable
    event dates. Those are not real observations and cannot represent the target
    session, so the diagnostic records and skips them. Every other malformed date
    remains a hard data-quality error.
    """

    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    if text.startswith("0000-"):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid ORATS {field} for {symbol}: {text!r}") from exc


def _fetch_sh24_history(
    ticker: str,
    *,
    start: date,
    end: date,
    token: str,
) -> tuple[list[Bar], dict[str, int]]:
    """Fetch SH24 history with explicit audit of ORATS year-zero sentinel rows."""

    symbol = ticker.strip().upper()
    warm_start = start - timedelta(days=730)
    history = fetch_daily_earnings_rows(
        symbol,
        warm_start=warm_start,
        end=end,
        token=token,
    )

    sentinel_earnings = 0
    earnings_dates: set[date] = set()
    for row in history.earnings_rows:
        raw = row.get("earnDate")
        parsed = _history_date(raw, field="earnDate", symbol=symbol)
        if raw not in (None, "") and parsed is None and str(raw).strip().startswith("0000-"):
            sentinel_earnings += 1
            continue
        if parsed is not None:
            earnings_dates.add(parsed)

    sentinel_dailies = 0
    bars: list[Bar] = []
    for row in history.daily_rows:
        raw = row.get("tradeDate")
        parsed = _history_date(raw, field="tradeDate", symbol=symbol)
        if raw not in (None, "") and parsed is None and str(raw).strip().startswith("0000-"):
            sentinel_dailies += 1
            continue
        if parsed is None or parsed < warm_start or parsed > end:
            continue
        try:
            opn = float(row.get("open") or 0.0)
            high = float(row.get("hiPx") or 0.0)
            low = float(row.get("loPx") or 0.0)
            close = float(row.get("clsPx") or 0.0)
            volume = float(row.get("stockVolume") or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid ORATS daily numeric row for {symbol}") from exc
        if min(opn, high, low, close) <= 0:
            continue
        bars.append(
            Bar(
                trade_date=parsed,
                open=opn,
                high=high,
                low=low,
                close=close,
                volume=volume,
                earnings_event=parsed in earnings_dates,
            )
        )

    bars.sort(key=lambda bar: bar.trade_date)
    if len(bars) < 80:
        raise RuntimeError(f"Insufficient ORATS bars for {symbol}: {len(bars)}")
    return bars, {
        "ignored_zero_date_earnings_rows": sentinel_earnings,
        "ignored_zero_date_daily_rows": sentinel_dailies,
    }


def run_orats_diagnostic(
    symbols: Iterable[str],
    *,
    target_date: date,
    token: str,
    shadow_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch approved ORATS history and build one bounded research diagnostic."""

    pine_path = Path(PINE_SOURCE_PATH)
    missing_markers = validate_pine_contract(pine_path.read_text())
    if missing_markers:
        return {
            "ok": False,
            "source_diagnostic_complete": False,
            "source_data_status": "CONTRACT_DRIFT",
            "interpretation": "SH24_PINE_CONTRACT_DRIFT",
            "missing_pine_contract_markers": list(missing_markers),
            "research_only": True,
            "promotion_authorized": False,
            "trading_authorized": False,
            "live_trading_enabled": False,
        }

    requested = tuple(
        dict.fromkeys(str(raw).strip().upper() for raw in symbols if str(raw).strip())
    )
    diagnostics: list[Sh24PointDiagnostic] = []
    errors: dict[str, str] = {}
    provider_unsupported: dict[str, dict[str, str]] = {}
    target_unavailable: dict[str, str | None] = {}
    sentinel_audit: dict[str, dict[str, int]] = {}
    for symbol in requested:
        try:
            bars, audit = _fetch_sh24_history(
                symbol,
                start=target_date,
                end=target_date,
                token=token,
            )
            if any(audit.values()):
                sentinel_audit[symbol] = audit
            diagnostics.append(
                diagnose_sh24_history(symbol, bars, target_date=target_date, flat_at_start=True)
            )
        except TargetBarUnavailable as exc:
            target_unavailable[symbol] = (
                exc.latest_date.isoformat() if exc.latest_date is not None else None
            )
        except Exception as exc:  # noqa: BLE001 - per-symbol research boundary fails closed
            if "/" in symbol and isinstance(exc, HistoricalOratsAuthError):
                # ORATS rejects slash-delimited class shares even after the approved
                # provider-boundary alias normalization. Keep the security ineligible
                # for an expectation claim and expose the exclusion in the audit output.
                provider_unsupported[symbol] = {
                    "reason": "ORATS_UNSUPPORTED_CLASS_SHARE_SYMBOL",
                    "attempted_provider_symbol": symbol.replace("/", "."),
                    "error": f"{type(exc).__name__}:{exc}",
                }
            else:
                errors[symbol] = f"{type(exc).__name__}:{exc}"

    result = reconcile_universe(
        diagnostics,
        received_strategy_symbols=_received_symbols(shadow_status),
        covered_symbols=None,
    )
    result["source_diagnostic_complete"] = True
    result["source_data_status"] = "COMPLETE"

    if provider_unsupported:
        result["source_data_status"] = "COMPLETE_WITH_PROVIDER_EXCLUSIONS"
        result["provider_unsupported_count"] = len(provider_unsupported)
        result["provider_unsupported_symbols"] = sorted(provider_unsupported)
        result["provider_unsupported_details"] = dict(sorted(provider_unsupported.items()))
        result["coverage_limitations"].append(
            "Provider-unsupported securities were excluded from SH24 expectation claims; "
            "they remain ineligible for promotion or trading authorization."
        )

    if errors:
        result["ok"] = False
        result["source_diagnostic_complete"] = False
        result["source_data_status"] = "DATA_ERROR"
        result["interpretation"] = "INCOMPLETE_SH24_SOURCE_DIAGNOSTIC"
        result["fetch_errors"] = dict(sorted(errors.items()))
    elif target_unavailable:
        result["source_diagnostic_complete"] = False
        result["target_bar_unavailable_count"] = len(target_unavailable)
        result["target_bar_unavailable_symbols"] = sorted(target_unavailable)
        result["latest_available_trade_dates"] = dict(sorted(target_unavailable.items()))
        if not diagnostics and len(target_unavailable) == len(requested):
            # A uniform one-session provider publication delay is not malformed market
            # data and must not turn a healthy PAPER system red. The current AWS-boundary
            # result remains authoritative while source expectation is explicitly pending.
            result["ok"] = True
            result["source_data_status"] = "PENDING_PROVIDER_PUBLICATION"
            result["interpretation"] = "SH24_SOURCE_DATA_NOT_YET_PUBLISHED"
        else:
            # Partial publication can bias a universe-level zero-trade conclusion.
            result["ok"] = False
            result["source_data_status"] = "PARTIAL_PROVIDER_PUBLICATION"
            result["interpretation"] = "INCOMPLETE_SH24_SOURCE_DIAGNOSTIC"

    if sentinel_audit:
        result["orats_zero_date_sentinel_audit"] = dict(sorted(sentinel_audit.items()))
    result["target_date"] = target_date.isoformat()
    result["requested_symbol_count"] = len(requested)
    result["pine_source_path"] = PINE_SOURCE_PATH
    return result


def render_markdown(result: Mapping[str, Any]) -> str:
    """Render the source-side diagnostic without overstating TradingView coverage."""

    source_status = str(result.get("source_data_status") or "UNKNOWN")
    if source_status == "PENDING_PROVIDER_PUBLICATION":
        status_label = "PENDING PROVIDER DATA"
    elif result.get("ok") is True:
        status_label = "PASS"
    else:
        status_label = "FAIL-CLOSED"
    lines = [
        "### SH24 independent source-side signal diagnostic",
        f"Status: **{status_label}**  ",
        f"Interpretation: `{result.get('interpretation', 'UNKNOWN')}`  ",
        f"Source data: `{source_status}`; complete={result.get('source_diagnostic_complete')}  ",
        f"Target date: `{result.get('target_date', 'not supplied')}`  ",
        f"Symbols evaluated: **{result.get('symbols_evaluated', 0)}**  ",
        f"Full-universe SH24 entries expected: **{result.get('expected_entry_count', 0)}**  ",
        "Safety: `promotion_authorized=false`, `trading_authorized=false`, `live_trading_enabled=false`",
    ]
    if source_status == "PENDING_PROVIDER_PUBLICATION":
        latest_dates = {
            value
            for value in (result.get("latest_available_trade_dates") or {}).values()
            if value
        }
        latest_label = ", ".join(sorted(latest_dates)) if latest_dates else "none"
        lines.append(
            "ORATS historical target bars pending: "
            f"{result.get('target_bar_unavailable_count', 0)} symbols; "
            f"latest available trade date(s): `{latest_label}`"
        )
    unsupported = result.get("provider_unsupported_symbols") or []
    if unsupported:
        lines.append(
            "ORATS provider-unsupported securities excluded from expectation claims: "
            + ", ".join(f"`{s}`" for s in unsupported)
        )
    expected = result.get("expected_entry_symbols") or []
    missing = result.get("expected_but_not_received") or []
    unverified = result.get("expected_without_verifiable_coverage") or []
    if expected:
        lines.append("Full-universe source expectations: " + ", ".join(f"`{s}`" for s in expected))
    if missing:
        lines.append(
            "Expected on verified alert coverage but absent at AWS: "
            + ", ".join(f"`{s}`" for s in missing)
        )
    if unverified:
        lines.append(
            "Source expectations without verifiable TradingView alert coverage: "
            + ", ".join(f"`{s}`" for s in unverified)
        )
    sentinel_audit = result.get("orats_zero_date_sentinel_audit") or {}
    if sentinel_audit:
        earnings_count = sum(
            int(item.get("ignored_zero_date_earnings_rows", 0))
            for item in sentinel_audit.values()
            if isinstance(item, dict)
        )
        daily_count = sum(
            int(item.get("ignored_zero_date_daily_rows", 0))
            for item in sentinel_audit.values()
            if isinstance(item, dict)
        )
        lines.append(
            "ORATS unavailable-date sentinels ignored/audited: "
            f"earnings={earnings_count}, daily={daily_count}"
        )
    blockers = result.get("blocker_counts") or {}
    if blockers:
        lines.append(
            "Source-side blocker counts: "
            + ", ".join(f"`{reason}`={count}" for reason, count in blockers.items())
        )
    lines.extend(
        [
            "",
            (
                "This is an independent SH24 daily-bar expectation diagnostic. Pine v2.4 is "
                "single-chart, and TradingView private alert coverage is not readable through a "
                "supported API, so full-universe source expectations do not by themselves prove "
                "missed TradingView alerts. SH25 is not inferred."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _load_symbols(path: str) -> list[str]:
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, list):
        if all(isinstance(item, str) for item in payload):
            return [item for item in payload if item.strip()]
        if all(isinstance(item, dict) for item in payload):
            return [str(item.get("symbol") or "") for item in payload]
    raise TypeError("symbols input must be a JSON string list or object list with symbol")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="JSON list or shortlist object list")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--shadow-status")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    token = os.getenv("ORATS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ORATS_TOKEN is required")
    shadow_status = None
    if args.shadow_status:
        loaded = json.loads(Path(args.shadow_status).read_text())
        if not isinstance(loaded, dict):
            raise TypeError("shadow status must be a JSON object")
        shadow_status = loaded

    result = run_orats_diagnostic(
        _load_symbols(args.symbols),
        target_date=date.fromisoformat(args.target_date),
        token=token,
        shadow_status=shadow_status,
    )
    Path(args.output_json).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    Path(args.output_md).write_text(render_markdown(result))
    return 0 if result.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())