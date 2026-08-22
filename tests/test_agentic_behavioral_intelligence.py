from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.behavioral_intelligence import (
    AttentionRegime,
    BehavioralIntelligenceEngine,
    BehavioralIntelligenceError,
    BehavioralIntelligencePolicy,
    BehavioralObservation,
    BehavioralSourceClass,
    SentimentRegime,
)
from daily_alpha.agentic.contracts import ReadinessStatus

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def _observation(
    provider: str,
    group: str,
    source_class: BehavioralSourceClass,
    *,
    minutes_ago: int = 5,
    mentions: int = 100,
    sentiment: float = 0.4,
    attention: float = 0.7,
    spam: float = 0.0,
    bot: float = 0.0,
    relevance: float = 0.9,
    confidence: float = 0.9,
) -> BehavioralObservation:
    end = NOW - timedelta(minutes=minutes_ago)
    start = end - timedelta(minutes=10)
    return BehavioralObservation(
        security_id="DAI-SEC-0001",
        provider_id=provider,
        independence_group=group,
        source_class=source_class,
        window_start=start,
        window_end=end,
        received_at=end + timedelta(seconds=5),
        mention_count=mentions,
        positive_mentions=int(mentions * 0.6),
        negative_mentions=int(mentions * 0.2),
        unique_authors=max(1, int(mentions * 0.4)),
        sentiment_score=sentiment,
        attention_score=attention,
        fear_score=0.2,
        uncertainty_score=0.3,
        novelty_score=0.7,
        relevance=relevance,
        confidence=confidence,
        spam_risk=spam,
        bot_risk=bot,
        source_version="V1",
    )


def _baseline(
    provider: str,
    group: str,
    source_class: BehavioralSourceClass,
    *,
    mentions: int = 30,
    sentiment: float = 0.1,
    attention: float = 0.3,
) -> BehavioralObservation:
    end = NOW - timedelta(minutes=20)
    start = end - timedelta(minutes=10)
    return BehavioralObservation(
        security_id="DAI-SEC-0001",
        provider_id=provider,
        independence_group=group,
        source_class=source_class,
        window_start=start,
        window_end=end,
        received_at=end + timedelta(seconds=5),
        mention_count=mentions,
        positive_mentions=int(mentions * 0.4),
        negative_mentions=int(mentions * 0.2),
        unique_authors=max(1, int(mentions * 0.4)),
        sentiment_score=sentiment,
        attention_score=attention,
        fear_score=0.2,
        uncertainty_score=0.3,
        novelty_score=0.4,
        relevance=0.9,
        confidence=0.9,
        source_version="V1",
    )


def test_multi_platform_acceleration_creates_confirmed_surging_state():
    current = (
        _observation("NEWS_VENDOR", "NEWS_UPSTREAM", BehavioralSourceClass.NEWS, mentions=120),
        _observation("SOCIAL_X", "X_DIRECT", BehavioralSourceClass.SOCIAL, mentions=180),
        _observation("SEARCH", "SEARCH_DIRECT", BehavioralSourceClass.SEARCH, mentions=90),
    )
    baseline = (
        _baseline("NEWS_VENDOR", "NEWS_UPSTREAM", BehavioralSourceClass.NEWS, mentions=30),
        _baseline("SOCIAL_X", "X_DIRECT", BehavioralSourceClass.SOCIAL, mentions=45),
        _baseline("SEARCH", "SEARCH_DIRECT", BehavioralSourceClass.SEARCH, mentions=20),
    )
    state = BehavioralIntelligenceEngine().build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=current,
        baseline=baseline,
    )
    assert state.status is ReadinessStatus.PASS
    assert state.attention_regime is AttentionRegime.SURGING
    assert state.sentiment_regime in {SentimentRegime.BULLISH, SentimentRegime.STRONGLY_BULLISH}
    assert state.mention_acceleration is not None and state.mention_acceleration > 2.0
    assert state.cross_platform_confirmation is True
    assert state.source_diversity == 3
    assert state.source_class_diversity == 3


def test_single_source_is_warning_grade_not_trade_authority():
    state = BehavioralIntelligenceEngine().build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(_observation("SOCIAL_X", "X_DIRECT", BehavioralSourceClass.SOCIAL),),
        baseline=(_baseline("SOCIAL_X", "X_DIRECT", BehavioralSourceClass.SOCIAL),),
    )
    assert state.status is ReadinessStatus.WARNING
    assert "BEHAVIORAL_SINGLE_INDEPENDENCE_GROUP" in state.warnings
    assert state.cross_platform_confirmation is False
    assert state.trading_authorized is False
    assert state.capital_allocation_authorized is False
    assert state.execution_authorized is False
    assert state.live_trading_enabled is False


def test_same_upstream_group_does_not_create_false_redundancy():
    current = (
        _observation("VENDOR_A", "SHARED_UPSTREAM", BehavioralSourceClass.VENDOR_COMPOSITE),
        _observation(
            "VENDOR_B",
            "SHARED_UPSTREAM",
            BehavioralSourceClass.SOCIAL,
            minutes_ago=4,
        ),
    )
    state = BehavioralIntelligenceEngine().build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=current,
    )
    assert state.source_diversity == 1
    assert state.cross_platform_confirmation is False
    assert any(item.startswith("BEHAVIORAL_FALSE_REDUNDANCY_COLLAPSED") for item in state.warnings)


def test_high_spam_and_bot_risk_are_excluded_before_aggregation():
    good = _observation("NEWS", "NEWS_DIRECT", BehavioralSourceClass.NEWS, sentiment=0.2)
    spam = _observation(
        "SOCIAL_SPAM",
        "SOCIAL_SPAM",
        BehavioralSourceClass.SOCIAL,
        sentiment=1.0,
        spam=0.9,
    )
    bot = _observation(
        "SOCIAL_BOT",
        "SOCIAL_BOT",
        BehavioralSourceClass.SOCIAL,
        sentiment=1.0,
        bot=0.9,
    )
    state = BehavioralIntelligenceEngine().build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(good, spam, bot),
    )
    assert state.sentiment_level == pytest.approx(0.2)
    assert spam.observation_id in state.excluded_observation_ids
    assert bot.observation_id in state.excluded_observation_ids


def test_future_observation_is_hard_rejected():
    future = BehavioralObservation(
        security_id="DAI-SEC-0001",
        provider_id="FUTURE",
        independence_group="FUTURE",
        source_class=BehavioralSourceClass.NEWS,
        window_start=NOW,
        window_end=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=1, seconds=1),
        mention_count=10,
        positive_mentions=5,
        negative_mentions=2,
        unique_authors=5,
        sentiment_score=0.4,
        attention_score=0.5,
    )
    with pytest.raises(BehavioralIntelligenceError, match="FUTURE_BEHAVIORAL_OBSERVATION_NOT_ALLOWED"):
        BehavioralIntelligenceEngine().build(
            security_id="DAI-SEC-0001",
            as_of=NOW,
            current=(future,),
        )


def test_all_stale_sources_block_state():
    stale = _observation(
        "OLD_SOCIAL",
        "OLD_SOCIAL",
        BehavioralSourceClass.SOCIAL,
        minutes_ago=120,
    )
    state = BehavioralIntelligenceEngine(
        BehavioralIntelligencePolicy(max_freshness_seconds=900)
    ).build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(stale,),
    )
    assert state.status is ReadinessStatus.BLOCKED
    assert state.sentiment_level is None
    assert "NO_VALID_CURRENT_BEHAVIORAL_OBSERVATIONS" in state.blockers


def test_missing_baseline_preserves_current_state_but_warns():
    state = BehavioralIntelligenceEngine().build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(
            _observation("NEWS", "NEWS", BehavioralSourceClass.NEWS),
            _observation("SEARCH", "SEARCH", BehavioralSourceClass.SEARCH),
        ),
    )
    assert state.status is ReadinessStatus.WARNING
    assert state.mention_acceleration is None
    assert state.attention_regime is AttentionRegime.UNKNOWN
    assert "BEHAVIORAL_BASELINE_UNAVAILABLE" in state.warnings


def test_sentiment_disagreement_is_visible_as_warning():
    policy = BehavioralIntelligencePolicy(sentiment_dispersion_warning=0.4)
    current = (
        _observation("NEWS", "NEWS", BehavioralSourceClass.NEWS, sentiment=0.9),
        _observation("FORUM", "FORUM", BehavioralSourceClass.FORUM, sentiment=-0.9),
    )
    state = BehavioralIntelligenceEngine(policy).build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=current,
    )
    assert state.status is ReadinessStatus.WARNING
    assert "BEHAVIORAL_SENTIMENT_DISPERSION_HIGH" in state.warnings
    assert state.cross_platform_confirmation is False


def test_state_id_is_deterministic_across_input_order():
    news = _observation("NEWS", "NEWS", BehavioralSourceClass.NEWS)
    social = _observation("SOCIAL", "SOCIAL", BehavioralSourceClass.SOCIAL)
    base_news = _baseline("NEWS", "NEWS", BehavioralSourceClass.NEWS)
    base_social = _baseline("SOCIAL", "SOCIAL", BehavioralSourceClass.SOCIAL)
    engine = BehavioralIntelligenceEngine()
    left = engine.build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(news, social),
        baseline=(base_news, base_social),
    )
    right = engine.build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(social, news),
        baseline=(base_social, base_news),
    )
    assert left.state_id == right.state_id


def test_behavioral_state_converts_to_governed_council_evidence_ref():
    state = BehavioralIntelligenceEngine().build(
        security_id="DAI-SEC-0001",
        as_of=NOW,
        current=(
            _observation("NEWS", "NEWS", BehavioralSourceClass.NEWS),
            _observation("SOCIAL", "SOCIAL", BehavioralSourceClass.SOCIAL),
        ),
        baseline=(
            _baseline("NEWS", "NEWS", BehavioralSourceClass.NEWS),
            _baseline("SOCIAL", "SOCIAL", BehavioralSourceClass.SOCIAL),
        ),
    )
    ref = state.to_council_input_ref()
    assert ref.input_kind.value == "EVIDENCE"
    assert ref.input_id == state.state_id
    assert ref.status is state.status
