from daily_alpha.pine_historical_reference import (
    build_historical_v24_reference,
    evaluate_historical_v24_reference,
    HistoricalReferenceError,
)


MARKET_HEADER = (
    "time,symbol,open,high,low,close,volume,earnings_state,earnings_actual,"
    "earnings_known_at,source_id\n"
)
SIGNAL_HEADER = (
    "bar_time,symbol,action,price,entry_type,runner_stage,quantity_units,source_id\n"
)
OUTCOME_HEADER = (
    "bar_time,symbol,outcome_kind,signal_actions,rejection_reasons,entry_type,source_id\n"
)


def _market_csv() -> str:
    return MARKET_HEADER + (
        "2026-01-02T21:00:00+00:00,ABC,100,101,99,100.5,2000000,NONE,,,mkt-1\n"
        "2026-01-05T21:00:00+00:00,ABC,100.5,102,100,101.5,2100000,NONE,,,mkt-2\n"
    )


def _no_signal_csv() -> str:
    return SIGNAL_HEADER


def _no_trade_outcomes() -> str:
    return OUTCOME_HEADER + (
        "2026-01-02T21:00:00+00:00,ABC,NO_TRADE,,,NONE,out-1\n"
        "2026-01-05T21:00:00+00:00,ABC,NO_TRADE,,,NONE,out-2\n"
    )


def _build(
    *,
    market_csv: str | None = None,
    signal_csv: str | None = None,
    outcome_csv: str | None = None,
):
    return build_historical_v24_reference(
        symbol="ABC",
        market_csv=market_csv if market_csv is not None else _market_csv(),
        tradingview_signal_csv=(
            signal_csv if signal_csv is not None else _no_signal_csv()
        ),
        tradingview_bar_outcome_csv=(
            outcome_csv if outcome_csv is not None else _no_trade_outcomes()
        ),
        market_source="POINT_IN_TIME_MARKET_EXPORT",
        market_revision="market-r1",
        tradingview_source="TRADINGVIEW",
        tradingview_signal_revision="signals-r1",
        tradingview_bar_outcome_revision="outcomes-r1",
    )


def test_explicit_zero_signal_history_can_prove_exact_no_trade_parity() -> None:
    reference = _build()

    evaluation = evaluate_historical_v24_reference(reference)

    assert evaluation.exact is True
    assert evaluation.signal_report.reference_count == 0
    assert evaluation.signal_report.python_count == 0
    assert evaluation.bar_outcome_report.reference_count == 2
    assert evaluation.bar_outcome_report.exact_bar_count == 2
    assert reference.market_artifact.row_count == 2
    assert reference.signal_artifact.row_count == 0
    assert reference.bar_outcome_artifact.row_count == 2
    assert len(reference.reference_id) == 64


def test_missing_bar_outcome_cannot_be_interpreted_as_no_trade() -> None:
    incomplete = OUTCOME_HEADER + (
        "2026-01-02T21:00:00+00:00,ABC,NO_TRADE,,,NONE,out-1\n"
    )

    try:
        _build(outcome_csv=incomplete)
    except HistoricalReferenceError as exc:
        assert str(exc) == "BAR_OUTCOME_COVERAGE_MUST_MATCH_EVERY_MARKET_BAR"
    else:
        raise AssertionError("missing explicit bar outcome must fail closed")


def test_future_known_earnings_event_is_rejected() -> None:
    market = MARKET_HEADER + (
        "2026-01-02T21:00:00+00:00,ABC,100,101,99,100.5,2000000,KNOWN,1.25,"
        "2026-01-02T22:00:00+00:00,mkt-1\n"
    )
    outcomes = OUTCOME_HEADER + (
        "2026-01-02T21:00:00+00:00,ABC,NO_TRADE,,,NONE,out-1\n"
    )

    try:
        _build(market_csv=market, outcome_csv=outcomes)
    except HistoricalReferenceError as exc:
        assert str(exc) == "EARNINGS_EVENT_WAS_NOT_KNOWN_BY_BAR_CLOSE"
    else:
        raise AssertionError("future earnings knowledge must fail closed")


def test_signal_stream_and_bar_outcome_stream_must_agree() -> None:
    signals = SIGNAL_HEADER + (
        "2026-01-05T21:00:00+00:00,ABC,ENTRY_LONG,101.5,NORMAL_BREAKOUT,,2,sig-1\n"
    )

    try:
        _build(signal_csv=signals)
    except HistoricalReferenceError as exc:
        assert str(exc) == "BAR_OUTCOME_SIGNAL_STREAM_DISAGREEMENT"
    else:
        raise AssertionError("signal/outcome disagreement must fail closed")


def test_same_source_artifacts_produce_stable_reference_identity() -> None:
    first = _build()
    second = _build()

    assert first.reference_id == second.reference_id
    assert first.market_artifact.sha256 == second.market_artifact.sha256
    assert first.signal_artifact.sha256 == second.signal_artifact.sha256
