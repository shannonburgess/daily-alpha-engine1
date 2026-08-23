from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

PINE_V25_MODEL_ID = "PAPER_SHADOW_V25"
PINE_V25_STRATEGY_VERSION = "2.5"
PINE_V25_SOURCE_PR = 207
PINE_V25_SOURCE_COMMIT = "b2a214c6b7a689453df5de7bb870c352456ebe8c"
PINE_V25_SOURCE_SHA256 = "77d7d3491cad0f74c273d9c8995bcaf54683bcc72927c844f243a43cf8b93718"
PROCESS_ORDERS_ON_CLOSE = True


@dataclass(frozen=True, slots=True)
class V25ArmedParameters:
    use_persistent_armed_entry: bool = True
    armed_max_bars: int = 10
    max_chase_atr: float = 1.0
    arm_invalidation_atr: float = 0.50

    def __post_init__(self) -> None:
        if self.armed_max_bars < 1:
            raise ValueError("armed_max_bars must be positive")
        if self.max_chase_atr < 0:
            raise ValueError("max_chase_atr cannot be negative")
        if self.arm_invalidation_atr < 0:
            raise ValueError("arm_invalidation_atr cannot be negative")


@dataclass(frozen=True, slots=True)
class V25ArmedInputs:
    bar_index: int
    close: float
    upper20: float | None
    atr: float | None
    position_is_flat: bool
    normal_breakout_candidate: bool
    same_bar_normal_entry: bool
    trend_state: int
    normal_trend_mature: bool
    fresh_trend_ok: bool
    quality_entry_ok: bool
    bar_confirmed: bool = True

    def __post_init__(self) -> None:
        if self.bar_index < 0:
            raise ValueError("bar_index cannot be negative")
        if not isfinite(float(self.close)):
            raise ValueError("close must be finite")
        if self.upper20 is not None and not isfinite(float(self.upper20)):
            raise ValueError("upper20 must be finite")
        if self.atr is not None and (not isfinite(float(self.atr)) or self.atr < 0):
            raise ValueError("atr must be finite and non-negative")
        if self.trend_state not in {-1, 1}:
            raise ValueError("trend_state must be -1 or 1")


@dataclass(frozen=True, slots=True)
class V25ArmedSnapshot:
    breakout_armed: bool
    armed_breakout_level: float | None
    armed_atr: float | None
    armed_bar: int | None
    armed_age: int | None
    armed_max_price: float | None
    armed_invalidation_level: float | None
    new_arm: bool
    arm_expired_event: bool
    arm_invalidated_event: bool
    armed_active: bool
    armed_above_breakout: bool
    armed_within_chase: bool
    armed_trend_ready: bool
    armed_confirmed_entry: bool


class V25ArmedBreakoutMachine:
    """Exact persistent-arm sub-state from the audited SH25 Pine challenger.

    This intentionally models only the v2.5 differentiator. The caller owns the common
    v2.4/v2.5 indicator calculations and passes their already-evaluated booleans in. This keeps
    the source-specific arm lifecycle testable without silently substituting SH24 entry rules.
    """

    def __init__(self, parameters: V25ArmedParameters | None = None) -> None:
        self.parameters = parameters or V25ArmedParameters()
        self._breakout_armed = False
        self._armed_breakout_level: float | None = None
        self._armed_atr: float | None = None
        self._armed_bar: int | None = None

    def reset(self) -> None:
        self._breakout_armed = False
        self._armed_breakout_level = None
        self._armed_atr = None
        self._armed_bar = None

    def step(self, inputs: V25ArmedInputs) -> V25ArmedSnapshot:
        params = self.parameters
        new_arm = False
        arm_expired_event = False
        arm_invalidated_event = False

        # Audited Pine: price breakout creates the opportunity even when trend/quality is not
        # ready. Same-bar entries do not create a redundant arm.
        if (
            params.use_persistent_armed_entry
            and inputs.position_is_flat
            and inputs.normal_breakout_candidate
            and not inputs.same_bar_normal_entry
        ):
            if inputs.upper20 is None or inputs.atr is None:
                raise ValueError("arming requires upper20 and ATR")
            self._breakout_armed = True
            self._armed_breakout_level = inputs.upper20
            self._armed_atr = inputs.atr
            self._armed_bar = inputs.bar_index
            new_arm = True

        armed_age = (
            inputs.bar_index - self._armed_bar
            if self._breakout_armed and self._armed_bar is not None
            else None
        )
        armed_max_price = (
            self._armed_breakout_level + self._armed_atr * params.max_chase_atr
            if self._breakout_armed
            and self._armed_breakout_level is not None
            and self._armed_atr is not None
            else None
        )
        armed_invalidation_level = (
            self._armed_breakout_level - self._armed_atr * params.arm_invalidation_atr
            if self._breakout_armed
            and self._armed_breakout_level is not None
            and self._armed_atr is not None
            else None
        )
        arm_timed_out = (
            self._breakout_armed
            and armed_age is not None
            and armed_age > params.armed_max_bars
        )
        arm_structurally_invalid = (
            self._breakout_armed
            and armed_invalidation_level is not None
            and inputs.close < armed_invalidation_level
        )

        # Pine clears expiry/invalidation before computing armedActive.
        if inputs.position_is_flat and arm_timed_out:
            self._breakout_armed = False
            arm_expired_event = True
        if inputs.position_is_flat and self._breakout_armed and arm_structurally_invalid:
            self._breakout_armed = False
            arm_invalidated_event = True

        armed_active = (
            params.use_persistent_armed_entry
            and inputs.position_is_flat
            and self._breakout_armed
            and armed_age is not None
            and armed_age <= params.armed_max_bars
        )
        armed_above_breakout = (
            armed_active
            and self._armed_breakout_level is not None
            and inputs.close >= self._armed_breakout_level
        )
        armed_within_chase = (
            armed_active
            and armed_max_price is not None
            and inputs.close <= armed_max_price
        )
        armed_trend_ready = (
            armed_active
            and inputs.trend_state == 1
            and inputs.normal_trend_mature
            and inputs.fresh_trend_ok
        )
        armed_confirmed_entry = (
            inputs.bar_confirmed
            and armed_trend_ready
            and armed_above_breakout
            and armed_within_chase
            and inputs.quality_entry_ok
        )

        snapshot = V25ArmedSnapshot(
            breakout_armed=self._breakout_armed,
            armed_breakout_level=self._armed_breakout_level,
            armed_atr=self._armed_atr,
            armed_bar=self._armed_bar,
            armed_age=armed_age,
            armed_max_price=armed_max_price,
            armed_invalidation_level=armed_invalidation_level,
            new_arm=new_arm,
            arm_expired_event=arm_expired_event,
            arm_invalidated_event=arm_invalidated_event,
            armed_active=armed_active,
            armed_above_breakout=armed_above_breakout,
            armed_within_chase=armed_within_chase,
            armed_trend_ready=armed_trend_ready,
            armed_confirmed_entry=armed_confirmed_entry,
        )

        # The full Pine longEntry block clears the arm after an armed confirmation. Performing
        # the clear after capturing the source-state snapshot preserves that bar's diagnostics.
        if armed_confirmed_entry:
            self.reset()

        return snapshot
