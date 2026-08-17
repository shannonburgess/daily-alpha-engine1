"""Server-side Daily Alpha v2.4 execution-universe evaluation.

This module mirrors the confirmed-daily-bar v2.4 Pine entry/runner/exit rules across
an entire ranked universe. It produces canonical paper-only scanner signals; it
never talks to a live broker and never bypasses the downstream portfolio-risk or
fresh-ORATS execution gates.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping

from .backtest import Bar, indicators
from .signals import SignalAction, parse_pine_signal

SCANNER_SOURCE = "DAILY_ALPHA_SCANNER"
CANONICAL_STRATEGY = "DA_TURTLE_ADAPTIVE_TREND"
CANONICAL_VERSION = "2.4"
CANONICAL_TIMEFRAME = "D"
UNIVERSE_LIMIT_DEFAULT = 20


@dataclass(frozen=True)
class ScannerState:
    symbol: str
    entry_date: str
    runner_base_entry: float
    runner_base_atr: float
    entry_breakout_level: float
    runner_stage: str = "STARTER"
    add1_price: float | None = None
    add2_price: float | None = None
    break_even_level: float | None = None
    last_signal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScannerState":
        return cls(
            symbol=str(payload["symbol"]).upper(),
            entry_date=str(payload["entry_date"]),
            runner_base_entry=float(payload["runner_base_entry"]),
            runner_base_atr=float(payload["runner_base_atr"]),
            entry_breakout_level=float(payload["entry_breakout_level"]),
            runner_stage=str(payload.get("runner_stage", "STARTER")).upper(),
            add1_price=_optional_float(payload.get("add1_price")),
            add2_price=_optional_float(payload.get("add2_price")),
            break_even_level=_optional_float(payload.get("break_even_level")),
            last_signal_id=(
                None if payload.get("last_signal_id") in (None, "") else str(payload["last_signal_id"])
            ),
        )


@dataclass(frozen=True)
class ScannerDecision:
    symbol: str
    market_bar_date: str
    action: str | None
    reason: str
    signal: dict[str, Any] | None
    proposed_state: ScannerState | None
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.proposed_state is not None:
            payload["proposed_state"] = self.proposed_state.to_dict()
        return payload


def load_state(path: str | Path) -> dict[str, ScannerState]:
    target = Path(path)
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Execution-universe state must be an object")
    return {
        str(symbol).upper(): ScannerState.from_dict(value)
        for symbol, value in payload.items()
        if isinstance(value, Mapping)
    }


def write_state(path: str | Path, state: Mapping[str, ScannerState]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {symbol: item.to_dict() for symbol, item in sorted(state.items())}
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def select_execution_universe(
    shortlist_csv: str | Path,
    state: Mapping[str, ScannerState],
    *,
    open_symbols: list[str] | tuple[str, ...] = (),
    limit: int = UNIVERSE_LIMIT_DEFAULT,
) -> list[str]:
    if limit <= 0:
        raise ValueError("Execution universe limit must be positive")
    selected: list[str] = []
    seen: set[str] = set()
    with Path(shortlist_csv).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda row: _rank_value(row.get("rank")))
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not _valid_symbol(symbol) or symbol in seen:
            continue
        selected.append(symbol)
        seen.add(symbol)
        if len(selected) >= limit:
            break
    for symbol in [*state.keys(), *open_symbols]:
        value = str(symbol).strip().upper()
        if _valid_symbol(value) and value not in seen:
            selected.append(value)
            seen.add(value)
    return selected


def evaluate_latest_v24(
    symbol: str,
    bars: list[Bar],
    *,
    state: ScannerState | None,
    now: datetime,
    require_trade_date: date | None = None,
) -> ScannerDecision:
    if len(bars) < 80:
        raise ValueError(f"Insufficient bars for {symbol}: {len(bars)}")
    reference = _aware(now)
    ind = indicators(bars)
    bar = bars[-1]
    row = ind[-1]
    market_date = bar.trade_date
    if require_trade_date is not None and market_date != require_trade_date:
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action=None,
            reason="NO_CURRENT_CONFIRMED_DAILY_BAR",
            signal=None,
            proposed_state=state,
            metrics=_metrics(bar, row),
        )

    price_ok = bar.close >= 25.0
    eff_ok = row["efficiency"] is not None and float(row["efficiency"]) >= 0.20
    rsi_ok = row["rsi"] is not None and float(row["rsi"]) <= 80.0
    adx_ok = row["adx"] is not None and float(row["adx"]) >= 25.0
    avg_dollar_volume = _average_dollar_volume(bars)

    if state is None:
        normal_setup = (
            bool(row["fresh_breakout"])
            and not bool(row["is_earnings_up_gap"])
            and int(row["trend_state"]) == 1
            and bool(row["normal_trend_mature"])
        )
        normal_entry = normal_setup and price_ok and eff_ok and rsi_ok and adx_ok
        gap_entry = (
            bool(row["gap_go"])
            and bool(row["fresh_breakout"])
            and price_ok
        )
        if not (normal_entry or gap_entry):
            return ScannerDecision(
                symbol=symbol.upper(),
                market_bar_date=market_date.isoformat(),
                action=None,
                reason=_entry_wait_reason(row, price_ok, eff_ok, rsi_ok, adx_ok),
                signal=None,
                proposed_state=None,
                metrics=_metrics(bar, row),
            )
        if row["atr"] is None or row["upper20"] is None or row["lower10"] is None:
            return ScannerDecision(
                symbol=symbol.upper(),
                market_bar_date=market_date.isoformat(),
                action=None,
                reason="ENTRY_INDICATOR_CONTEXT_INCOMPLETE",
                signal=None,
                proposed_state=None,
                metrics=_metrics(bar, row),
            )
        entry_type = "EARNINGS_GAP_GO" if gap_entry else "NORMAL_BREAKOUT"
        gap_class = (
            "EARNINGS_GAP_GO"
            if bool(row["gap_go"])
            else "EARNINGS_GAP_GO_EARLY"
            if bool(row.get("gap_go_early"))
            else "EARNINGS_GAP_CRAP"
            if bool(row["gap_crap"])
            else "EARNINGS_WAIT"
            if bool(row["gap_wait"])
            else "NONE"
        )
        signal = _base_signal(symbol, market_date, "ENTRY_LONG", bar.close, reference)
        signal.update(
            {
                "entry_type": entry_type,
                "earnings_gap_class": gap_class,
                "earnings_gap_pct": float(row["gap_pct"]),
                "earnings_gap_atr": float(row["gap_atr"]),
                "earnings_close_location": float(row["close_location"]),
                "earnings_gap_retention": float(row["gap_retention"]),
                "earnings_relative_volume": float(row["relative_volume"]),
                "stock_stop_price": float(row["lower10"]),
                "average_daily_dollar_volume": avg_dollar_volume,
            }
        )
        next_state = ScannerState(
            symbol=symbol.upper(),
            entry_date=market_date.isoformat(),
            runner_base_entry=bar.close,
            runner_base_atr=float(row["atr"]),
            entry_breakout_level=float(row["upper20"]),
            last_signal_id=signal["signal_id"],
        )
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action="ENTRY_LONG",
            reason=entry_type,
            signal=signal,
            proposed_state=next_state,
            metrics=_metrics(bar, row),
        )

    entry_index = _date_index(bars, state.entry_date)
    if entry_index is None:
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action=None,
            reason="SCANNER_STATE_ENTRY_DATE_NOT_IN_HISTORY",
            signal=None,
            proposed_state=state,
            metrics=_metrics(bar, row),
        )
    bars_since_entry = len(bars) - 1 - entry_index
    failed_exit = (
        1 <= bars_since_entry <= 3 and bar.close < state.entry_breakout_level
    )
    turtle_exit = row["lower10"] is not None and bar.close < float(row["lower10"])
    trend_exit = bool(row["bear_flip"])
    break_even_exit = (
        state.runner_stage == "HARVEST_3_ATR"
        and state.break_even_level is not None
        and bar.close <= state.break_even_level
    )
    if break_even_exit or failed_exit or turtle_exit or trend_exit:
        reason = (
            "BREAK_EVEN_EXIT"
            if break_even_exit
            else "FAILED_BREAKOUT_EXIT"
            if failed_exit
            else "TURTLE_EXIT"
            if turtle_exit
            else "TREND_EXIT"
        )
        signal = _base_signal(symbol, market_date, "EXIT", bar.close, reference)
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action="EXIT",
            reason=reason,
            signal=signal,
            proposed_state=None,
            metrics=_metrics(bar, row),
        )

    runner_trend_ok = int(row["trend_state"]) == 1 and adx_ok
    if (
        state.runner_stage == "STARTER"
        and runner_trend_ok
        and bar.close >= state.runner_base_entry + state.runner_base_atr
    ):
        signal = _runner_signal(symbol, market_date, "ADD", "ADD_1_ATR", bar.close, reference)
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action="ADD",
            reason="ADD_1_ATR",
            signal=signal,
            proposed_state=ScannerState(
                **{
                    **state.to_dict(),
                    "runner_stage": "ADD_1_ATR",
                    "add1_price": bar.close,
                    "last_signal_id": signal["signal_id"],
                }
            ),
            metrics=_metrics(bar, row),
        )
    if (
        state.runner_stage == "ADD_1_ATR"
        and runner_trend_ok
        and bar.close >= state.runner_base_entry + 2.0 * state.runner_base_atr
    ):
        signal = _runner_signal(symbol, market_date, "ADD", "ADD_2_ATR", bar.close, reference)
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action="ADD",
            reason="ADD_2_ATR",
            signal=signal,
            proposed_state=ScannerState(
                **{
                    **state.to_dict(),
                    "runner_stage": "ADD_2_ATR",
                    "add2_price": bar.close,
                    "last_signal_id": signal["signal_id"],
                }
            ),
            metrics=_metrics(bar, row),
        )
    if (
        state.runner_stage == "ADD_2_ATR"
        and bar.close >= state.runner_base_entry + 3.0 * state.runner_base_atr
        and state.add1_price is not None
        and state.add2_price is not None
    ):
        break_even = (
            2.0 * state.runner_base_entry + state.add1_price + state.add2_price
        ) / 4.0
        signal = _runner_signal(
            symbol, market_date, "PARTIAL", "HARVEST_3_ATR", bar.close, reference
        )
        return ScannerDecision(
            symbol=symbol.upper(),
            market_bar_date=market_date.isoformat(),
            action="PARTIAL",
            reason="HARVEST_3_ATR",
            signal=signal,
            proposed_state=ScannerState(
                **{
                    **state.to_dict(),
                    "runner_stage": "HARVEST_3_ATR",
                    "break_even_level": break_even,
                    "last_signal_id": signal["signal_id"],
                }
            ),
            metrics=_metrics(bar, row),
        )

    return ScannerDecision(
        symbol=symbol.upper(),
        market_bar_date=market_date.isoformat(),
        action=None,
        reason="OPEN_POSITION_NO_NEW_V24_ACTION",
        signal=None,
        proposed_state=state,
        metrics=_metrics(bar, row),
    )


def build_scanner_ingress(signal: Mapping[str, Any], *, received_at: datetime) -> dict[str, Any]:
    """Validate and normalize a server scanner signal for the paper processor."""
    now = _aware(received_at)
    payload = dict(signal)
    if payload.get("source") not in (None, SCANNER_SOURCE):
        raise ValueError("Scanner signal source is invalid")
    if payload.get("webhook_secret") not in (None, ""):
        raise ValueError("Scanner signal must never contain a webhook secret")
    parsed = parse_pine_signal(payload, received_at=now, max_age_minutes=30)
    if parsed.strategy != CANONICAL_STRATEGY or parsed.strategy_version != CANONICAL_VERSION:
        raise ValueError("Scanner signal strategy/version is not canonical v2.4")
    if parsed.timeframe.upper() not in {"D", "1D"}:
        raise ValueError("Scanner signal timeframe must be daily")
    if parsed.action == SignalAction.ENTRY_LONG:
        entry_type = str(payload.get("entry_type", "")).upper()
        if entry_type not in {"NORMAL_BREAKOUT", "EARNINGS_GAP_GO"}:
            raise ValueError("Scanner v2.4 entry_type is invalid")
        stop = float(payload.get("stock_stop_price", 0))
        adv = float(payload.get("average_daily_dollar_volume", -1))
        if stop <= 0 or stop >= parsed.price or adv < 0:
            raise ValueError("Scanner entry execution metadata is invalid")
        if entry_type == "EARNINGS_GAP_GO":
            if str(payload.get("earnings_gap_class", "")).upper() != "EARNINGS_GAP_GO":
                raise ValueError("Gap & Go scanner entry classification mismatch")
            for key in (
                "earnings_gap_pct",
                "earnings_gap_atr",
                "earnings_close_location",
                "earnings_gap_retention",
                "earnings_relative_volume",
            ):
                float(payload[key])
    if parsed.action == SignalAction.ADD:
        if parsed.runner_stage not in {"ADD_1_ATR", "ADD_2_ATR"} or parsed.position_fraction != 0.25:
            raise ValueError("Scanner ADD runner contract is invalid")
    if parsed.action == SignalAction.PARTIAL:
        if parsed.runner_stage != "HARVEST_3_ATR" or parsed.position_fraction != 0.25:
            raise ValueError("Scanner PARTIAL runner contract is invalid")

    return {
        "schema_version": "2026-08-17-scanner-v1",
        "source": SCANNER_SOURCE,
        "received_at": now.isoformat(),
        "trading_authorized": False,
        "paper_execution_triggered": False,
        "live_trading_enabled": False,
        **payload,
    }


def execution_succeeded(execution: Mapping[str, Any]) -> bool:
    return str(execution.get("disposition", "")).upper() == "EXECUTED_PAPER"


def _base_signal(symbol: str, market_date: date, action: str, price: float, now: datetime) -> dict[str, Any]:
    return {
        "source": SCANNER_SOURCE,
        "signal_id": f"DA-SCAN-{symbol.upper()}-{market_date.isoformat()}-{action}",
        "symbol": symbol.upper(),
        "action": action,
        "strategy": CANONICAL_STRATEGY,
        "strategy_version": CANONICAL_VERSION,
        "timeframe": CANONICAL_TIMEFRAME,
        "price": float(price),
        "bar_time": _aware(now).isoformat(),
    }


def _runner_signal(symbol: str, market_date: date, action: str, stage: str, price: float, now: datetime) -> dict[str, Any]:
    payload = _base_signal(symbol, market_date, action, price, now)
    payload["signal_id"] = f"DA-SCAN-{symbol.upper()}-{market_date.isoformat()}-{stage}"
    payload["position_fraction"] = 0.25
    payload["runner_stage"] = stage
    return payload


def _entry_wait_reason(row: Mapping[str, Any], price_ok: bool, eff_ok: bool, rsi_ok: bool, adx_ok: bool) -> str:
    if not bool(row["fresh_breakout"]):
        return "WAIT_NO_FRESH_20D_BREAKOUT"
    if int(row["trend_state"]) != 1:
        return "WAIT_TREND_NOT_BULLISH"
    if bool(row["is_earnings_up_gap"]):
        if bool(row.get("gap_go_early")):
            return "WATCH_EARNINGS_GAP_GO_EARLY"
        if bool(row["gap_crap"]):
            return "PASS_EARNINGS_GAP_CRAP"
        if not bool(row["gap_go"]):
            return "WAIT_EARNINGS_GAP_QUALITY"
    if not bool(row["normal_trend_mature"]):
        return "WAIT_TREND_NOT_MATURE"
    if not price_ok:
        return "WAIT_PRICE_BELOW_25"
    if not eff_ok:
        return "WAIT_LOW_TREND_EFFICIENCY"
    if not rsi_ok:
        return "WAIT_RSI_EXTENDED"
    if not adx_ok:
        return "WAIT_ADX_BELOW_25"
    return "WAIT_V24_ENTRY_NOT_CONFIRMED"


def _metrics(bar: Bar, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "close": bar.close,
        "atr": row.get("atr"),
        "rsi": row.get("rsi"),
        "adx": row.get("adx"),
        "efficiency": row.get("efficiency"),
        "upper20": row.get("upper20"),
        "lower10": row.get("lower10"),
        "trend_state": row.get("trend_state"),
        "fresh_breakout": row.get("fresh_breakout"),
        "earnings_gap_go": row.get("gap_go"),
        "earnings_gap_go_early": row.get("gap_go_early"),
    }


def _average_dollar_volume(bars: list[Bar]) -> float:
    window = bars[-20:]
    if len(window) < 20:
        return 0.0
    return sum(bar.close * bar.volume for bar in window) / len(window)


def _date_index(bars: list[Bar], value: str) -> int | None:
    try:
        target = date.fromisoformat(value)
    except ValueError:
        return None
    for index, bar in enumerate(bars):
        if bar.trade_date == target:
            return index
    return None


def _rank_value(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 10**9


def _optional_float(value: Any) -> float | None:
    return None if value in (None, "") else float(value)


def _valid_symbol(value: str) -> bool:
    return bool(value) and value.replace(".", "").replace("-", "").isalnum()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
