# ruff: noqa: I001

from datetime import UTC, datetime, timedelta

from daily_alpha import actionable_sector, agentic, equity_liquidity, ovtlyr, pine_ingress
from daily_alpha.agentic import adapters
from daily_alpha.agentic.contracts import EvidenceStatus


NOW = datetime(2026, 8, 21, 20, 5, tzinfo=UTC)
OBSERVED = NOW - timedelta(minutes=5)


def test_ovtlyr_adapter_preserves_existing_classification_without_reclassifying():
    classified = ovtlyr.ClassifiedRecord(
        symbol="DINO",
        status=ovtlyr.OvtlyrStatus.EMERGING,
        display_label="EMERGING",
        signal="BUY",
        previous_signal="",
        signal_date="2026-08-21",
        sector="Energy",
        industry="Oil & Gas Refining & Marketing",
        trend="UP",
        momentum="ACCELERATING",
        optionable=True,
        reason="New BUY with rising trend and accelerating momentum",
    )

    evidence = adapters.ovtlyr_to_evidence(
        classified,
        observed_at=OBSERVED,
        received_at=NOW,
        source_version="OVTLYR_2026-08-21",
        source_file="OVTLYR_2026-08-21.csv",
    )

    assert evidence.source == adapters.OVTLYR_EVIDENCE_SOURCE
    assert evidence.evidence_type == "OVTLYR_STATE"
    assert evidence.status is EvidenceStatus.COMPLETE
    assert evidence.value["status"] == "EMERGING"
    assert evidence.value["signal"] == "BUY"
    assert evidence.value["sector"] == "Energy"
    assert evidence.trading_authorized is False
    assert evidence.live_trading_enabled is False


def test_sector_adapter_preserves_server_authority_and_source_file():
    source = actionable_sector.ActionableSectorEvidence(
        symbol="DINO",
        sector="Energy",
        source_file="OVTLYR_2026-08-21.csv",
    )

    evidence = adapters.sector_to_evidence(
        source,
        observed_at=OBSERVED,
        received_at=NOW,
    )

    assert evidence.source == adapters.SECTOR_EVIDENCE_SOURCE
    assert evidence.value == {
        "sector": "Energy",
        "authority": actionable_sector.SECTOR_AUTHORITY,
    }
    assert ("source_file", "OVTLYR_2026-08-21.csv") in evidence.provenance


def test_liquidity_adapter_keeps_valid_negative_eligibility_as_complete_evidence():
    decision = equity_liquidity.LiquidityDecision(
        symbol="XYZ",
        allowed=False,
        security_type="COMPANY_EQUITY",
        reason="LIQUIDITY_FILTERED",
        detail="AT_OR_BELOW_THRESHOLD",
        average_daily_share_volume_30d=1_500_000.0,
        source_date="2026-08-21",
    )

    evidence = adapters.liquidity_to_evidence(
        decision,
        observed_at=OBSERVED,
        received_at=NOW,
    )

    assert evidence.status is EvidenceStatus.COMPLETE
    assert evidence.value["allowed"] is False
    assert evidence.value["detail"] == "AT_OR_BELOW_THRESHOLD"
    assert evidence.confidence == 1.0


def test_liquidity_adapter_distinguishes_stale_and_bad_source_evidence():
    stale = equity_liquidity.LiquidityDecision(
        symbol="DINO",
        allowed=False,
        security_type="UNKNOWN",
        reason="LIQUIDITY_FILTERED",
        detail="LIQUIDITY_EVIDENCE_STALE",
        average_daily_share_volume_30d=None,
        source_date="2026-08-10",
    )
    bad = equity_liquidity.LiquidityDecision(
        symbol="DINO",
        allowed=False,
        security_type="UNKNOWN",
        reason="LIQUIDITY_FILTERED",
        detail="LIQUIDITY_THRESHOLD_CONTRACT_MISMATCH",
        average_daily_share_volume_30d=None,
        source_date="2026-08-21",
    )

    stale_evidence = adapters.liquidity_to_evidence(
        stale,
        observed_at=OBSERVED,
        received_at=NOW,
    )
    bad_evidence = adapters.liquidity_to_evidence(
        bad,
        observed_at=OBSERVED,
        received_at=NOW,
    )

    assert stale_evidence.status is EvidenceStatus.STALE
    assert stale_evidence.confidence == 0.0
    assert bad_evidence.status is EvidenceStatus.DATA_ERROR
    assert bad_evidence.confidence == 0.0


def test_pine_adapter_uses_validated_ingress_timestamps_and_signal_identity():
    ingress = pine_ingress.PineIngressRecord(
        schema_version="2026-08-18-v5",
        source="TRADINGVIEW_PINE",
        signal_id="DINO-1787342400000-ENTRY_LONG",
        symbol="DINO",
        action="ENTRY_LONG",
        strategy="DA_TURTLE_ADAPTIVE_TREND",
        strategy_version="2.4",
        timeframe="1D",
        price=32.04,
        bar_time="2026-08-21T20:00:00+00:00",
        received_at="2026-08-21T20:01:24+00:00",
        model_id="PAPER_SHADOW_V24",
        forward_test_start="2026-08-19",
        replay_max_price=32.50,
        stock_stop_price=31.02,
        entry_type="NORMAL_BREAKOUT",
    )

    evidence = adapters.pine_to_evidence(ingress)

    assert evidence.source == adapters.PINE_EVIDENCE_SOURCE
    assert evidence.evidence_type == "PINE_SIGNAL"
    assert evidence.observed_at == datetime(2026, 8, 21, 20, 0, tzinfo=UTC)
    assert evidence.received_at == datetime(2026, 8, 21, 20, 1, 24, tzinfo=UTC)
    assert evidence.value["signal_id"] == "DINO-1787342400000-ENTRY_LONG"
    assert evidence.value["model_id"] == "PAPER_SHADOW_V24"
    assert evidence.status is EvidenceStatus.COMPLETE


def test_adapter_outputs_feed_existing_foundation_supervisor_without_execution():
    classified = ovtlyr.ClassifiedRecord(
        symbol="DINO",
        status=ovtlyr.OvtlyrStatus.EMERGING,
        display_label="EMERGING",
        signal="BUY",
        previous_signal="",
        signal_date="2026-08-21",
        sector="Energy",
        industry="Oil & Gas Refining & Marketing",
        trend="UP",
        momentum="ACCELERATING",
        optionable=True,
        reason="New BUY with rising trend and accelerating momentum",
    )
    sector = actionable_sector.ActionableSectorEvidence(
        symbol="DINO",
        sector="Energy",
        source_file="OVTLYR_2026-08-21.csv",
    )
    liquidity = equity_liquidity.LiquidityDecision(
        symbol="DINO",
        allowed=True,
        security_type="COMPANY_EQUITY",
        reason="ELIGIBLE",
        detail="COMPANY_VOLUME_STRICTLY_ABOVE_1_5M",
        average_daily_share_volume_30d=3_290_000.0,
        source_date="2026-08-21",
    )

    records = (
        adapters.ovtlyr_to_evidence(
            classified,
            observed_at=OBSERVED,
            received_at=NOW,
            source_version="OVTLYR_2026-08-21",
        ),
        adapters.sector_to_evidence(sector, observed_at=OBSERVED, received_at=NOW),
        adapters.liquidity_to_evidence(liquidity, observed_at=OBSERVED, received_at=NOW),
    )

    store = agentic.InMemoryEvidenceStore()
    store.put_many(records)
    packet = agentic.DataSupervisor(
        registry=agentic.daily_alpha_v1_registry(),
        store=store,
    ).evaluate("DINO", NOW)

    assert packet.status is agentic.ReadinessStatus.PASS
    assert packet.trading_authorized is False
    assert packet.live_trading_enabled is False
    assert any(
        assessment.source == adapters.PINE_EVIDENCE_SOURCE
        and assessment.required is False
        and assessment.status is EvidenceStatus.SOURCE_UNAVAILABLE
        for assessment in packet.assessments
    )
