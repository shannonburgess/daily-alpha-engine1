"""Lifecycle-aware sizing and no-chase policy for paper entries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleSizingPolicy:
    lifecycle: str
    risk_multiplier: float
    entry_allowed: bool


_ALIASES = {
    "EMERGING": "EARLY_EMERGING",
    "EARLY_EMERGING": "EARLY_EMERGING",
    "NEW_BUY": "FRESH_CROSS",
    "RE_ENTRY": "FRESH_CROSS",
    "FRESH_CROSS": "FRESH_CROSS",
    "ENTRY_WATCH": "ENTRY_WATCH",
    "ACTIVE_BUY": "CONFIRMED_LEADER",
    "LEADER": "CONFIRMED_LEADER",
    "CONFIRMED_LEADER": "CONFIRMED_LEADER",
    "EXTENDED": "EXTENDED_LEADER",
    "EXTENDED_BUY": "EXTENDED_LEADER",
    "EXTENDED_LEADER": "EXTENDED_LEADER",
}

_POLICIES = {
    "EARLY_EMERGING": LifecycleSizingPolicy("EARLY_EMERGING", 0.25, True),
    "FRESH_CROSS": LifecycleSizingPolicy("FRESH_CROSS", 0.50, True),
    "ENTRY_WATCH": LifecycleSizingPolicy("ENTRY_WATCH", 0.50, True),
    "CONFIRMED_LEADER": LifecycleSizingPolicy("CONFIRMED_LEADER", 1.00, True),
    "EXTENDED_LEADER": LifecycleSizingPolicy("EXTENDED_LEADER", 0.25, True),
}


def resolve_lifecycle_sizing(value: object) -> LifecycleSizingPolicy | None:
    """Return the canonical sizing policy, or None for missing/unknown data."""
    text = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    canonical = _ALIASES.get(text)
    return _POLICIES.get(canonical) if canonical else None


def lifecycle_risk_fraction(value: object, approved_risk_fraction: float) -> float:
    """Apply lifecycle sizing without ever exceeding the human-approved risk."""
    policy = resolve_lifecycle_sizing(value)
    # Missing classification must not suppress a valid paper signal. Use the
    # smallest starter allocation until lifecycle data becomes available.
    if policy is None:
        return approved_risk_fraction * 0.25
    if not policy.entry_allowed:
        return 0.0
    return approved_risk_fraction * policy.risk_multiplier
