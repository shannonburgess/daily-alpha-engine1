"""Sentiment and attention intelligence for the Daily Alpha investment platform.

Behavioral data is useful evidence, not authoritative market truth. This module normalizes
social, search, news, forum, web, and vendor-composite observations; rejects future/stale
or low-integrity inputs; prevents false redundancy from shared upstream sources; and emits
a deterministic point-in-time behavioral state for research agents.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus
from .research_council import CouncilInputKind, CouncilInputRef


class BehavioralIntelligenceError(ValueError):
    """Behavioral intelligence contract or reconciliation invariant failed."""


class BehavioralSourceClass(StrEnum):
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"
    FORUM = "FORUM"
    SEARCH = "SEARCH"
    WEB = "WEB"
    VENDOR_COMPOSITE = "VENDOR_COMPOSITE"
    ALTERNATIVE = "ALTERNATIVE"


class AttentionRegime(StrEnum):
    UNKNOWN = "UNKNOWN"
    FALLING = "FALLING"
    QUIET = "QUIET"
    RISING = "RISING"
    SURGING = "SURGING"


class SentimentRegime(StrEnum):
    STRONGLY_BEARISH = "STRONGLY_BEARISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"
    STRONGLY_BULLISH = "STRONGLY_BULLISH"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BehavioralIntelligenceError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BehavioralIntelligenceError("BEHAVIORAL_VALUE_NOT_CANONICAL_JSON") from exc


def _normalize_pairs(
    pairs: tuple[tuple[str, str], ...] | dict[str, str],
) -> tuple[tuple[str, str], ...]:
    items = pairs.items() if isinstance(pairs, dict) else pairs
    normalized = tuple(sorted((str(key).strip(), str(value).strip()) for key, value in items))
    if any(not key for key, _ in normalized):
        raise BehavioralIntelligenceError("BEHAVIORAL_PROVENANCE_KEY_REQUIRED")
    if len({key for key, _ in normalized}) != len(normalized):
        raise BehavioralIntelligenceError("BEHAVIORAL_PROVENANCE_KEYS_MUST_BE_UNIQUE")
    return normalized


@dataclass(frozen=True)
class BehavioralObservation:
    security_id: str
    provider_id: str
    independence_group: str
    source_class: BehavioralSourceClass
    window_start: datetime
    window_end: datetime
    received_at: datetime
    mention_count: int
    positive_mentions: int
    negative_mentions: int
    unique_authors: int
    sentiment_score: float
    attention_score: float
    fear_score: float = 0.0
    uncertainty_score: float = 0.0
    novelty_score: float = 0.0
    relevance: float = 1.0
    confidence: float = 1.0
    spam_risk: float = 0.0
    bot_risk: float = 0.0
    source_version: str = "V1"
    provenance: tuple[tuple[str, str], ...] | dict[str, str] = field(default_factory=tuple)
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        provider_id = self.provider_id.strip().upper()
        group = self.independence_group.strip().upper()
        version = self.source_version.strip()
        start = _aware_utc(self.window_start, "BEHAVIORAL_WINDOW_START")
        end = _aware_utc(self.window_end, "BEHAVIORAL_WINDOW_END")
        received = _aware_utc(self.received_at, "BEHAVIORAL_RECEIVED_AT")
        if not security_id or not provider_id or not group or not version:
            raise BehavioralIntelligenceError("BEHAVIORAL_IDENTITY_REQUIRED")
        if end <= start:
            raise BehavioralIntelligenceError("BEHAVIORAL_WINDOW_END_MUST_FOLLOW_START")
        if received < end:
            raise BehavioralIntelligenceError("BEHAVIORAL_RECEIVED_BEFORE_WINDOW_END")
        counts = (self.mention_count, self.positive_mentions, self.negative_mentions, self.unique_authors)
        if any(not isinstance(value, int) or value < 0 for value in counts):
            raise BehavioralIntelligenceError("BEHAVIORAL_COUNTS_MUST_BE_NONNEGATIVE_INTEGERS")
        if self.positive_mentions + self.negative_mentions > self.mention_count:
            raise BehavioralIntelligenceError("BEHAVIORAL_DIRECTIONAL_MENTIONS_EXCEED_TOTAL")
        if self.unique_authors > self.mention_count and self.mention_count > 0:
            raise BehavioralIntelligenceError("BEHAVIORAL_UNIQUE_AUTHORS_EXCEED_MENTIONS")
        if not math.isfinite(self.sentiment_score) or not -1.0 <= self.sentiment_score <= 1.0:
            raise BehavioralIntelligenceError("BEHAVIORAL_SENTIMENT_OUT_OF_RANGE")
        for name, value in (
            ("ATTENTION", self.attention_score),
            ("FEAR", self.fear_score),
            ("UNCERTAINTY", self.uncertainty_score),
            ("NOVELTY", self.novelty_score),
            ("RELEVANCE", self.relevance),
            ("CONFIDENCE", self.confidence),
            ("SPAM_RISK", self.spam_risk),
            ("BOT_RISK", self.bot_risk),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise BehavioralIntelligenceError(f"BEHAVIORAL_{name}_OUT_OF_RANGE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise BehavioralIntelligenceError("BEHAVIORAL_OBSERVATION_MUST_REMAIN_RESEARCH_ONLY")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "independence_group", group)
        object.__setattr__(self, "source_version", version)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "received_at", received)
        object.__setattr__(self, "provenance", _normalize_pairs(self.provenance))

    @property
    def window_seconds(self) -> float:
        return (self.window_end - self.window_start).total_seconds()

    @property
    def mention_rate_per_minute(self) -> float:
        return self.mention_count / (self.window_seconds / 60.0)

    @property
    def integrity_weight(self) -> float:
        return self.relevance * self.confidence * (1.0 - self.spam_risk) * (1.0 - self.bot_risk)

    @property
    def observation_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "provider_id": self.provider_id,
            "independence_group": self.independence_group,
            "source_class": self.source_class.value,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "received_at": self.received_at.isoformat(),
            "mention_count": self.mention_count,
            "positive_mentions": self.positive_mentions,
            "negative_mentions": self.negative_mentions,
            "unique_authors": self.unique_authors,
            "sentiment_score": self.sentiment_score,
            "attention_score": self.attention_score,
            "fear_score": self.fear_score,
            "uncertainty_score": self.uncertainty_score,
            "novelty_score": self.novelty_score,
            "relevance": self.relevance,
            "confidence": self.confidence,
            "spam_risk": self.spam_risk,
            "bot_risk": self.bot_risk,
            "source_version": self.source_version,
            "provenance": list(self.provenance),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BehavioralIntelligencePolicy:
    version: str = "BEHAVIORAL_INTELLIGENCE_V1"
    max_freshness_seconds: int = 1800
    min_relevance: float = 0.50
    min_confidence: float = 0.50
    max_spam_risk: float = 0.50
    max_bot_risk: float = 0.50
    min_independent_groups_for_confirmation: int = 2
    min_source_classes_for_confirmation: int = 2
    rising_ratio: float = 1.25
    surge_ratio: float = 2.00
    falling_ratio: float = 0.80
    sentiment_dispersion_warning: float = 0.50

    def __post_init__(self) -> None:
        version = self.version.strip()
        if not version:
            raise BehavioralIntelligenceError("BEHAVIORAL_POLICY_VERSION_REQUIRED")
        if self.max_freshness_seconds <= 0:
            raise BehavioralIntelligenceError("BEHAVIORAL_POLICY_FRESHNESS_MUST_BE_POSITIVE")
        for name, value in (
            ("MIN_RELEVANCE", self.min_relevance),
            ("MIN_CONFIDENCE", self.min_confidence),
            ("MAX_SPAM_RISK", self.max_spam_risk),
            ("MAX_BOT_RISK", self.max_bot_risk),
            ("SENTIMENT_DISPERSION_WARNING", self.sentiment_dispersion_warning),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise BehavioralIntelligenceError(f"BEHAVIORAL_POLICY_{name}_INVALID")
        if self.min_independent_groups_for_confirmation <= 0:
            raise BehavioralIntelligenceError("BEHAVIORAL_POLICY_GROUP_CONFIRMATION_INVALID")
        if self.min_source_classes_for_confirmation <= 0:
            raise BehavioralIntelligenceError("BEHAVIORAL_POLICY_CLASS_CONFIRMATION_INVALID")
        if not (0.0 < self.falling_ratio < 1.0 < self.rising_ratio < self.surge_ratio):
            raise BehavioralIntelligenceError("BEHAVIORAL_POLICY_ATTENTION_THRESHOLDS_INVALID")
        object.__setattr__(self, "version", version)

    @property
    def policy_id(self) -> str:
        payload = {
            "version": self.version,
            "max_freshness_seconds": self.max_freshness_seconds,
            "min_relevance": self.min_relevance,
            "min_confidence": self.min_confidence,
            "max_spam_risk": self.max_spam_risk,
            "max_bot_risk": self.max_bot_risk,
            "min_independent_groups_for_confirmation": self.min_independent_groups_for_confirmation,
            "min_source_classes_for_confirmation": self.min_source_classes_for_confirmation,
            "rising_ratio": self.rising_ratio,
            "surge_ratio": self.surge_ratio,
            "falling_ratio": self.falling_ratio,
            "sentiment_dispersion_warning": self.sentiment_dispersion_warning,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BehavioralIntelligenceState:
    security_id: str
    as_of: datetime
    policy_id: str
    status: ReadinessStatus
    sentiment_level: float | None
    sentiment_change: float | None
    sentiment_dispersion: float | None
    sentiment_regime: SentimentRegime | None
    attention_level: float | None
    attention_change: float | None
    mention_rate_per_minute: float | None
    mention_acceleration: float | None
    attention_regime: AttentionRegime
    fear_level: float | None
    uncertainty_level: float | None
    novelty_level: float | None
    source_diversity: int
    source_class_diversity: int
    cross_platform_confirmation: bool
    accepted_current_observation_ids: tuple[str, ...]
    accepted_baseline_observation_ids: tuple[str, ...]
    excluded_observation_ids: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    research_only: bool = True
    trading_authorized: bool = False
    capital_allocation_authorized: bool = False
    execution_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        policy_id = self.policy_id.strip().lower()
        boundary = _aware_utc(self.as_of, "BEHAVIORAL_STATE_AS_OF")
        if not security_id or not policy_id:
            raise BehavioralIntelligenceError("BEHAVIORAL_STATE_IDENTITY_REQUIRED")
        if (
            not self.research_only
            or self.trading_authorized
            or self.capital_allocation_authorized
            or self.execution_authorized
            or self.live_trading_enabled
        ):
            raise BehavioralIntelligenceError("BEHAVIORAL_STATE_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED:
            if self.sentiment_level is not None or self.attention_level is not None:
                raise BehavioralIntelligenceError("BLOCKED_BEHAVIORAL_STATE_CANNOT_HAVE_CANONICAL_LEVELS")
            if not self.blockers:
                raise BehavioralIntelligenceError("BLOCKED_BEHAVIORAL_STATE_REQUIRES_BLOCKER")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "accepted_current_observation_ids",
            tuple(sorted(set(self.accepted_current_observation_ids))),
        )
        object.__setattr__(
            self,
            "accepted_baseline_observation_ids",
            tuple(sorted(set(self.accepted_baseline_observation_ids))),
        )
        object.__setattr__(self, "excluded_observation_ids", tuple(sorted(set(self.excluded_observation_ids))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

    @property
    def state_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "as_of": self.as_of.isoformat(),
            "policy_id": self.policy_id,
            "status": self.status.value,
            "sentiment_level": self.sentiment_level,
            "sentiment_change": self.sentiment_change,
            "sentiment_dispersion": self.sentiment_dispersion,
            "sentiment_regime": self.sentiment_regime.value if self.sentiment_regime else None,
            "attention_level": self.attention_level,
            "attention_change": self.attention_change,
            "mention_rate_per_minute": self.mention_rate_per_minute,
            "mention_acceleration": self.mention_acceleration,
            "attention_regime": self.attention_regime.value,
            "fear_level": self.fear_level,
            "uncertainty_level": self.uncertainty_level,
            "novelty_level": self.novelty_level,
            "source_diversity": self.source_diversity,
            "source_class_diversity": self.source_class_diversity,
            "cross_platform_confirmation": self.cross_platform_confirmation,
            "accepted_current_observation_ids": list(self.accepted_current_observation_ids),
            "accepted_baseline_observation_ids": list(self.accepted_baseline_observation_ids),
            "excluded_observation_ids": list(self.excluded_observation_ids),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "capital_allocation_authorized": self.capital_allocation_authorized,
            "execution_authorized": self.execution_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def to_council_input_ref(self) -> CouncilInputRef:
        return CouncilInputRef(
            input_kind=CouncilInputKind.EVIDENCE,
            input_id=self.state_id,
            available_at=self.as_of,
            quality_label=f"BEHAVIORAL_{self.status.value}",
            status=self.status,
        )


class BehavioralIntelligenceEngine:
    def __init__(self, policy: BehavioralIntelligencePolicy | None = None) -> None:
        self.policy = policy or BehavioralIntelligencePolicy()

    def build(
        self,
        *,
        security_id: str,
        as_of: datetime,
        current: tuple[BehavioralObservation, ...],
        baseline: tuple[BehavioralObservation, ...] = (),
    ) -> BehavioralIntelligenceState:
        security = security_id.strip().upper()
        boundary = _aware_utc(as_of, "BEHAVIORAL_EVALUATION_AS_OF")
        if not security:
            raise BehavioralIntelligenceError("BEHAVIORAL_EVALUATION_SECURITY_REQUIRED")
        warnings: list[str] = []
        excluded: set[str] = set()
        current_selected = self._select(
            security=security,
            boundary=boundary,
            observations=current,
            warnings=warnings,
            excluded=excluded,
            label="CURRENT",
        )
        baseline_selected = self._select(
            security=security,
            boundary=boundary,
            observations=baseline,
            warnings=warnings,
            excluded=excluded,
            label="BASELINE",
        )
        if not current_selected:
            return BehavioralIntelligenceState(
                security_id=security,
                as_of=boundary,
                policy_id=self.policy.policy_id,
                status=ReadinessStatus.BLOCKED,
                sentiment_level=None,
                sentiment_change=None,
                sentiment_dispersion=None,
                sentiment_regime=None,
                attention_level=None,
                attention_change=None,
                mention_rate_per_minute=None,
                mention_acceleration=None,
                attention_regime=AttentionRegime.UNKNOWN,
                fear_level=None,
                uncertainty_level=None,
                novelty_level=None,
                source_diversity=0,
                source_class_diversity=0,
                cross_platform_confirmation=False,
                accepted_current_observation_ids=(),
                accepted_baseline_observation_ids=(),
                excluded_observation_ids=tuple(excluded),
                blockers=("NO_VALID_CURRENT_BEHAVIORAL_OBSERVATIONS",),
                warnings=tuple(warnings),
            )

        sentiment = self._weighted_mean(current_selected, "sentiment_score")
        attention = self._weighted_mean(current_selected, "attention_score")
        fear = self._weighted_mean(current_selected, "fear_score")
        uncertainty = self._weighted_mean(current_selected, "uncertainty_score")
        novelty = self._weighted_mean(current_selected, "novelty_score")
        mention_rate = sum(item.mention_rate_per_minute for item in current_selected)
        dispersion = statistics.pstdev(item.sentiment_score for item in current_selected)
        groups = {item.independence_group for item in current_selected}
        classes = {item.source_class for item in current_selected}

        baseline_sentiment = self._weighted_mean(baseline_selected, "sentiment_score") if baseline_selected else None
        baseline_attention = self._weighted_mean(baseline_selected, "attention_score") if baseline_selected else None
        baseline_rate = sum(item.mention_rate_per_minute for item in baseline_selected) if baseline_selected else None
        sentiment_change = sentiment - baseline_sentiment if baseline_sentiment is not None else None
        attention_change = attention - baseline_attention if baseline_attention is not None else None
        mention_acceleration = None
        if baseline_rate is not None and baseline_rate > 1e-12:
            mention_acceleration = mention_rate / baseline_rate
        elif baseline_selected:
            warnings.append("BASELINE_MENTION_RATE_ZERO")
        else:
            warnings.append("BEHAVIORAL_BASELINE_UNAVAILABLE")

        if len(groups) < self.policy.min_independent_groups_for_confirmation:
            warnings.append("BEHAVIORAL_SINGLE_INDEPENDENCE_GROUP")
        if dispersion > self.policy.sentiment_dispersion_warning:
            warnings.append("BEHAVIORAL_SENTIMENT_DISPERSION_HIGH")

        confirmation = self._cross_platform_confirmation(current_selected, classes, groups)
        regime = self._attention_regime(mention_acceleration)
        sentiment_regime = self._sentiment_regime(sentiment)
        status = ReadinessStatus.WARNING if warnings else ReadinessStatus.PASS
        return BehavioralIntelligenceState(
            security_id=security,
            as_of=boundary,
            policy_id=self.policy.policy_id,
            status=status,
            sentiment_level=sentiment,
            sentiment_change=sentiment_change,
            sentiment_dispersion=dispersion,
            sentiment_regime=sentiment_regime,
            attention_level=attention,
            attention_change=attention_change,
            mention_rate_per_minute=mention_rate,
            mention_acceleration=mention_acceleration,
            attention_regime=regime,
            fear_level=fear,
            uncertainty_level=uncertainty,
            novelty_level=novelty,
            source_diversity=len(groups),
            source_class_diversity=len(classes),
            cross_platform_confirmation=confirmation,
            accepted_current_observation_ids=tuple(item.observation_id for item in current_selected),
            accepted_baseline_observation_ids=tuple(item.observation_id for item in baseline_selected),
            excluded_observation_ids=tuple(excluded),
            warnings=tuple(warnings),
        )

    def _select(
        self,
        *,
        security: str,
        boundary: datetime,
        observations: tuple[BehavioralObservation, ...],
        warnings: list[str],
        excluded: set[str],
        label: str,
    ) -> tuple[BehavioralObservation, ...]:
        by_group: dict[str, BehavioralObservation] = {}
        for observation in observations:
            if observation.security_id != security:
                raise BehavioralIntelligenceError("BEHAVIORAL_SECURITY_MISMATCH")
            if observation.received_at > boundary:
                raise BehavioralIntelligenceError("FUTURE_BEHAVIORAL_OBSERVATION_NOT_ALLOWED")
            age = (boundary - observation.received_at).total_seconds()
            reason = None
            if age > self.policy.max_freshness_seconds:
                reason = "STALE"
            elif observation.relevance < self.policy.min_relevance:
                reason = "LOW_RELEVANCE"
            elif observation.confidence < self.policy.min_confidence:
                reason = "LOW_CONFIDENCE"
            elif observation.spam_risk > self.policy.max_spam_risk:
                reason = "SPAM_RISK"
            elif observation.bot_risk > self.policy.max_bot_risk:
                reason = "BOT_RISK"
            if reason:
                excluded.add(observation.observation_id)
                warnings.append(f"BEHAVIORAL_{label}_EXCLUDED:{observation.provider_id}:{reason}")
                continue
            existing = by_group.get(observation.independence_group)
            if existing is None or (observation.received_at, observation.provider_id) > (
                existing.received_at,
                existing.provider_id,
            ):
                if existing is not None:
                    excluded.add(existing.observation_id)
                    warnings.append(
                        f"BEHAVIORAL_FALSE_REDUNDANCY_COLLAPSED:{observation.independence_group}"
                    )
                by_group[observation.independence_group] = observation
            else:
                excluded.add(observation.observation_id)
                warnings.append(
                    f"BEHAVIORAL_FALSE_REDUNDANCY_COLLAPSED:{observation.independence_group}"
                )
        return tuple(sorted(by_group.values(), key=lambda item: item.independence_group))

    @staticmethod
    def _weighted_mean(observations: tuple[BehavioralObservation, ...], field_name: str) -> float:
        weighted = [(getattr(item, field_name), item.integrity_weight) for item in observations]
        denominator = sum(weight for _, weight in weighted)
        if denominator <= 1e-15:
            return sum(value for value, _ in weighted) / len(weighted)
        return sum(value * weight for value, weight in weighted) / denominator

    def _cross_platform_confirmation(
        self,
        observations: tuple[BehavioralObservation, ...],
        classes: set[BehavioralSourceClass],
        groups: set[str],
    ) -> bool:
        if len(groups) < self.policy.min_independent_groups_for_confirmation:
            return False
        if len(classes) < self.policy.min_source_classes_for_confirmation:
            return False
        directions = [
            1 if item.sentiment_score > 0.10 else -1 if item.sentiment_score < -0.10 else 0
            for item in observations
        ]
        positive = sum(direction > 0 for direction in directions)
        negative = sum(direction < 0 for direction in directions)
        required = self.policy.min_independent_groups_for_confirmation
        return max(positive, negative) >= required

    def _attention_regime(self, acceleration: float | None) -> AttentionRegime:
        if acceleration is None:
            return AttentionRegime.UNKNOWN
        if acceleration >= self.policy.surge_ratio:
            return AttentionRegime.SURGING
        if acceleration >= self.policy.rising_ratio:
            return AttentionRegime.RISING
        if acceleration <= self.policy.falling_ratio:
            return AttentionRegime.FALLING
        return AttentionRegime.QUIET

    @staticmethod
    def _sentiment_regime(sentiment: float) -> SentimentRegime:
        if sentiment <= -0.50:
            return SentimentRegime.STRONGLY_BEARISH
        if sentiment <= -0.15:
            return SentimentRegime.BEARISH
        if sentiment >= 0.50:
            return SentimentRegime.STRONGLY_BULLISH
        if sentiment >= 0.15:
            return SentimentRegime.BULLISH
        return SentimentRegime.NEUTRAL
