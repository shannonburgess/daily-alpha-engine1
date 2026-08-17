"""Earnings-gap classification for Daily Alpha event-driven entries.

The core Turtle strategy remains the baseline. This module classifies confirmed
earnings-linked upside gaps into GAP_GO, GAP_CRAP, or WAIT so the event sleeve can
be measured separately from normal breakouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EarningsGapClass(StrEnum):
    NONE = "NONE"
    EARNINGS_GAP_GO = "EARNINGS_GAP_GO"
    EARNINGS_GAP_CRAP = "EARNINGS_GAP_CRAP"
    EARNINGS_WAIT = "EARNINGS_WAIT"


@dataclass(frozen=True)
class EarningsGapConfig:
    min_gap_pct: float = 5.0
    min_gap_atr: float = 1.5
    min_close_location: float = 0.75
    min_gap_retention: float = 0.70
    min_relative_volume: float = 1.5
    max_rsi: float = 85.0
    crap_close_location: float = 0.50
    crap_gap_retention: float = 0.50


@dataclass(frozen=True)
class EarningsGapObservation:
    earnings_event: bool
    previous_close: float
    open: float
    high: float
    low: float
    close: float
    previous_atr: float
    volume: float
    average_volume_20: float
    prior_20_day_high: float
    rsi: float
    bullish_trend_state: bool


@dataclass(frozen=True)
class EarningsGapResult:
    classification: EarningsGapClass
    gap_pct: float
    gap_atr: float
    close_location: float
    gap_retention: float
    relative_volume: float
    breakout: bool
    eligible_entry: bool


def classify_earnings_gap(
    observation: EarningsGapObservation,
    config: EarningsGapConfig | None = None,
) -> EarningsGapResult:
    """Classify one daily earnings-linked upside gap.

    GAP_GO is an event-driven entry candidate and intentionally does not require
    the normal ADX/trend-efficiency gates. It does require a bullish trend state
    by the close, a 20-day breakout, strong close location, gap retention, and
    volume confirmation. GAP_CRAP is an explicit rejection. Intermediate cases
    are WAIT and can be studied for next-day confirmation separately.
    """
    cfg = config or EarningsGapConfig()
    _validate_observation(observation)

    previous_close = observation.previous_close
    gap_dollars = observation.open - previous_close
    gap_pct = gap_dollars / previous_close * 100.0
    gap_atr = gap_dollars / observation.previous_atr
    day_range = observation.high - observation.low
    close_location = (
        (observation.close - observation.low) / day_range if day_range > 0 else 0.0
    )
    gap_retention = (
        (observation.close - previous_close) / gap_dollars if gap_dollars > 0 else 0.0
    )
    relative_volume = (
        observation.volume / observation.average_volume_20
        if observation.average_volume_20 > 0
        else 0.0
    )
    breakout = observation.close > observation.prior_20_day_high

    qualifies_as_gap = observation.earnings_event and gap_dollars > 0 and (
        gap_pct >= cfg.min_gap_pct or gap_atr >= cfg.min_gap_atr
    )
    if not qualifies_as_gap:
        return EarningsGapResult(
            classification=EarningsGapClass.NONE,
            gap_pct=gap_pct,
            gap_atr=gap_atr,
            close_location=close_location,
            gap_retention=gap_retention,
            relative_volume=relative_volume,
            breakout=breakout,
            eligible_entry=False,
        )

    gap_go = (
        observation.close >= observation.open
        and close_location >= cfg.min_close_location
        and gap_retention >= cfg.min_gap_retention
        and relative_volume >= cfg.min_relative_volume
        and observation.rsi <= cfg.max_rsi
        and observation.bullish_trend_state
        and breakout
    )
    if gap_go:
        classification = EarningsGapClass.EARNINGS_GAP_GO
    else:
        obvious_failure = (
            observation.close < previous_close
            or gap_retention < cfg.crap_gap_retention
            or (
                observation.close < observation.open
                and close_location < cfg.crap_close_location
            )
        )
        classification = (
            EarningsGapClass.EARNINGS_GAP_CRAP
            if obvious_failure
            else EarningsGapClass.EARNINGS_WAIT
        )

    return EarningsGapResult(
        classification=classification,
        gap_pct=gap_pct,
        gap_atr=gap_atr,
        close_location=close_location,
        gap_retention=gap_retention,
        relative_volume=relative_volume,
        breakout=breakout,
        eligible_entry=classification == EarningsGapClass.EARNINGS_GAP_GO,
    )


def _validate_observation(observation: EarningsGapObservation) -> None:
    positive_fields = {
        "previous_close": observation.previous_close,
        "open": observation.open,
        "high": observation.high,
        "low": observation.low,
        "close": observation.close,
        "previous_atr": observation.previous_atr,
        "prior_20_day_high": observation.prior_20_day_high,
    }
    for name, value in positive_fields.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if observation.high < observation.low:
        raise ValueError("high must be greater than or equal to low")
    if observation.volume < 0 or observation.average_volume_20 < 0:
        raise ValueError("volume fields must be non-negative")
