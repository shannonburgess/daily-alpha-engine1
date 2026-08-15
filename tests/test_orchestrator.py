from daily_alpha.orchestrator import (
    STAGE_ORDER,
    DailyAlphaOrchestrator,
    RunContext,
    RunMode,
    Stage,
    StageResult,
    StageStatus,
)


def context():
    return RunContext(
        "run-1", "2026-08-15", "daily-alpha-v2", RunMode.PAPER, {"raw": 1}
    )


def passing_handlers(call_order):
    def handler(stage):
        def execute(_context, payload):
            call_order.append(stage)
            return StageResult(
                stage, StageStatus.PASSED, "OK", 1, 1, {**payload, stage.value: True}
            )

        return execute

    return {stage: handler(stage) for stage in STAGE_ORDER}


def test_complete_run_executes_every_stage_in_order_and_can_publish():
    calls = []
    result = DailyAlphaOrchestrator(passing_handlers(calls)).run(context())
    assert calls == list(STAGE_ORDER)
    assert result.successful is True
    assert result.publication_allowed is True
    assert result.final_payload["PUBLISH"] is True


def test_orats_data_error_stops_risk_ledger_packet_and_publication():
    calls = []
    handlers = passing_handlers(calls)
    handlers[Stage.ORATS_ENRICHMENT] = lambda _context, _payload: StageResult(
        Stage.ORATS_ENRICHMENT,
        StageStatus.DATA_ERROR,
        "ORATS_STALE",
    )
    result = DailyAlphaOrchestrator(handlers).run(context())
    assert result.publication_allowed is False
    assert result.final_payload is None
    assert result.stages[4].status == StageStatus.SKIPPED
    assert Stage.PORTFOLIO_RISK not in calls
    assert Stage.PUBLISH not in calls


def test_missing_stage_handler_fails_closed():
    handlers = passing_handlers([])
    del handlers[Stage.PINE_SIGNALS]
    result = DailyAlphaOrchestrator(handlers).run(context())
    failed = result.stages[2]
    assert failed.status == StageStatus.FAILED
    assert failed.reason == "STAGE_HANDLER_MISSING"
    assert result.publication_allowed is False


def test_adapter_exception_is_audited_without_partial_publication():
    handlers = passing_handlers([])

    def broken(_context, _payload):
        raise TimeoutError("source unavailable")

    handlers[Stage.INGEST] = broken
    result = DailyAlphaOrchestrator(handlers).run(context())
    assert result.stages[0].reason == "UNHANDLED_STAGE_ERROR:TimeoutError"
    assert all(stage.status == StageStatus.SKIPPED for stage in result.stages[1:])
    assert result.publication_allowed is False


def test_handler_cannot_return_result_for_wrong_stage():
    handlers = passing_handlers([])
    handlers[Stage.INGEST] = lambda _context, _payload: StageResult(
        Stage.PUBLISH, StageStatus.PASSED, "WRONG"
    )
    result = DailyAlphaOrchestrator(handlers).run(context())
    assert result.stages[0].reason == "STAGE_IDENTITY_MISMATCH"
    assert result.publication_allowed is False
