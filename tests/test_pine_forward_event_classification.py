from daily_alpha.pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardPersistedEventEvidence,
)
from daily_alpha.pine_forward_event_classification import (
    EXPLICIT_STAGING_E2E_SIGNAL_IDS,
    partition_forward_events,
)


def _event(signal_id: str, symbol: str = "DINO") -> ForwardPersistedEventEvidence:
    fields = {
        "signal_id": signal_id,
        "symbol": symbol,
        "action": "ENTRY_LONG" if symbol == "DINO" else "ADD",
        "source": "TRADINGVIEW_PINE",
        "strategy": "DA_TURTLE_ADAPTIVE_TREND",
        "strategy_version": "2.5",
        "model_id": "PAPER_SHADOW_V25",
        "timeframe": "1D" if symbol == "DINO" else "D",
        "price": 97.32,
        "bar_time": "2026-08-21T20:00:00+00:00",
        "entry_type": "NORMAL_BREAKOUT" if symbol == "DINO" else None,
        "runner_stage": None if symbol == "DINO" else "ADD_1_ATR",
        "trading_authorized": False,
        "live_trading_enabled": False,
    }
    return ForwardPersistedEventEvidence(
        account_id="PAPER_SHADOW_V25",
        signal_id=signal_id,
        fields=tuple(sorted(fields.items())),
    )


def _book(events: tuple[ForwardPersistedEventEvidence, ...]) -> ForwardParityBookEvidence:
    return ForwardParityBookEvidence(
        account_id="PAPER_SHADOW_V25",
        event_count_visible=len(events),
        event_count_scanned=len(events),
        event_history_omitted=0,
        event_limit=100,
        scan_pages=1,
        scan_items_evaluated=len(events),
        open_count=0,
        armed_count_visible=0,
        events=events,
    )


def test_exact_retained_e2e_ids_are_separated_without_deleting_history() -> None:
    natural = _event("DINO-1787342400000-ENTRY_LONG")
    test_events = tuple(_event(signal_id, "DAE2E") for signal_id in sorted(EXPLICIT_STAGING_E2E_SIGNAL_IDS))
    book = _book((natural, *test_events))

    partition = partition_forward_events(book)

    assert partition.reference_candidate_count == 1
    assert partition.reference_candidates == (natural,)
    assert partition.explicit_staging_test_count == 3
    assert {event.signal_id for event in partition.explicit_staging_tests} == EXPLICIT_STAGING_E2E_SIGNAL_IDS
    assert book.event_count_visible == 4


def test_future_or_lookalike_ids_are_never_excluded_by_fuzzy_heuristic() -> None:
    future = _event("FUTURE-E2E-LIKE-BUT-NOT-REGISTERED", "DAE2E")
    partition = partition_forward_events(_book((future,)))

    assert partition.reference_candidates == (future,)
    assert partition.explicit_staging_tests == ()
