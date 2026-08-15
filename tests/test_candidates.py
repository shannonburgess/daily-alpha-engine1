from daily_alpha.candidates import (
    CandidateBucket,
    assess_candidate,
    rank_candidates,
    write_candidate_outputs,
)
from daily_alpha.models import OptionCandidate
from daily_alpha.ovtlyr import OvtlyrRecord, compare_universes


def record(symbol="AAA", **overrides):
    values = {
        "symbol": symbol,
        "signal": "BUY",
        "sector": "Technology",
        "trend": "UPTREND",
        "momentum": "MOVING UP",
        "price": 100,
        "average_volume": 1_000_000,
    }
    values.update(overrides)
    return OvtlyrRecord(**values)


def option(symbol="AAA", **overrides):
    values = {
        "symbol": symbol,
        "expiration": "2026-10-16",
        "strike": 100,
        "option_type": "CALL",
        "dte": 62,
        "bid": 4.8,
        "ask": 5.2,
        "open_interest": 500,
        "volume": 600,
        "delta": 0.55,
    }
    values.update(overrides)
    return OptionCandidate(**values)


def classified(source):
    return compare_universes([], [source])[0]


def test_qualified_option_becomes_top_setup():
    source = record()
    item = assess_candidate(
        classified=classified(source),
        source=source,
        options=[option()],
        option_data_available=True,
        option_data_fresh=True,
        pine_entry=True,
        risk_gate_passed=True,
        sector_net_score=100,
    )
    assert item.bucket == CandidateBucket.OPTION_SETUP
    assert item.selected_delta == 0.55
    assert item.unusual_options_activity is True


def test_failed_contract_can_use_liquid_stock():
    source = record()
    item = assess_candidate(
        classified=classified(source),
        source=source,
        options=[option(open_interest=1)],
        option_data_available=True,
        option_data_fresh=True,
        pine_entry=True,
        risk_gate_passed=True,
    )
    assert item.bucket == CandidateBucket.STOCK_FALLBACK


def test_stale_orats_is_data_error_not_stock_fallback():
    source = record()
    item = assess_candidate(
        classified=classified(source),
        source=source,
        options=[],
        option_data_available=True,
        option_data_fresh=False,
        pine_entry=True,
        risk_gate_passed=True,
    )
    assert item.bucket == CandidateBucket.DATA_ERROR


def test_no_pine_entry_stays_on_watch():
    source = record()
    item = assess_candidate(
        classified=classified(source),
        source=source,
        options=[option()],
        option_data_available=True,
        option_data_fresh=True,
        pine_entry=False,
        risk_gate_passed=True,
    )
    assert item.bucket == CandidateBucket.ENTRY_WATCH


def test_rank_and_write_outputs(tmp_path):
    assessments = []
    for symbol, sector_score in (("LOW", 0), ("HIGH", 100)):
        source = record(symbol)
        assessments.append(
            assess_candidate(
                classified=classified(source),
                source=source,
                options=[option(symbol)],
                option_data_available=True,
                option_data_fresh=True,
                pine_entry=True,
                risk_gate_passed=True,
                sector_net_score=sector_score,
            )
        )
    ranked = rank_candidates(assessments)
    assert ranked[0].symbol == "HIGH"
    outputs = write_candidate_outputs(tmp_path, assessments)
    assert all(path.exists() for path in outputs.values())
