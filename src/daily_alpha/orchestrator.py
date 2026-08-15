"""Fail-closed end-to-end orchestration for Daily Alpha research runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RunMode(StrEnum):
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"


class Stage(StrEnum):
    INGEST = "INGEST"
    COMPARE_AND_RANK = "COMPARE_AND_RANK"
    PINE_SIGNALS = "PINE_SIGNALS"
    ORATS_ENRICHMENT = "ORATS_ENRICHMENT"
    PORTFOLIO_RISK = "PORTFOLIO_RISK"
    PAPER_LEDGER = "PAPER_LEDGER"
    RESEARCH_PACKET = "RESEARCH_PACKET"
    PUBLISH = "PUBLISH"


STAGE_ORDER = tuple(Stage)


class StageStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    DATA_ERROR = "DATA_ERROR"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class StageResult:
    stage: Stage
    status: StageStatus
    reason: str
    records_in: int = 0
    records_out: int = 0
    payload: Any = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("stage result requires a reason")
        if min(self.records_in, self.records_out) < 0:
            raise ValueError("stage record counts cannot be negative")

    @property
    def passed(self) -> bool:
        return self.status == StageStatus.PASSED


@dataclass(frozen=True)
class RunContext:
    run_id: str
    report_date: str
    methodology_version: str
    mode: RunMode
    initial_payload: Any = None

    def __post_init__(self) -> None:
        if not all((self.run_id, self.report_date, self.methodology_version)):
            raise ValueError("run identity, date, and methodology version are required")


@dataclass(frozen=True)
class OrchestrationResult:
    context: RunContext
    stages: tuple[StageResult, ...]
    publication_allowed: bool
    final_payload: Any = None

    @property
    def successful(self) -> bool:
        return self.publication_allowed and all(result.passed for result in self.stages)


StageHandler = Callable[[RunContext, Any], StageResult]


class DailyAlphaOrchestrator:
    """Execute injected production modules in one deterministic, audited order."""

    def __init__(self, handlers: Mapping[Stage, StageHandler]) -> None:
        self.handlers = dict(handlers)

    def run(self, context: RunContext) -> OrchestrationResult:
        payload = context.initial_payload
        results: list[StageResult] = []
        blocked = False

        for stage in STAGE_ORDER:
            if blocked:
                results.append(
                    StageResult(stage, StageStatus.SKIPPED, "UPSTREAM_STAGE_BLOCKED")
                )
                continue
            handler = self.handlers.get(stage)
            if handler is None:
                result = StageResult(stage, StageStatus.FAILED, "STAGE_HANDLER_MISSING")
            else:
                result = self._execute(handler, stage, context, payload)
            results.append(result)
            if result.stage != stage:
                result = StageResult(
                    stage, StageStatus.FAILED, "STAGE_IDENTITY_MISMATCH"
                )
                results[-1] = result
            if result.passed:
                payload = result.payload
            else:
                blocked = True

        publication = (
            not blocked
            and len(results) == len(STAGE_ORDER)
            and results[-1].stage == Stage.PUBLISH
            and results[-1].passed
        )
        return OrchestrationResult(
            context, tuple(results), publication, payload if publication else None
        )

    @staticmethod
    def _execute(
        handler: StageHandler,
        stage: Stage,
        context: RunContext,
        payload: Any,
    ) -> StageResult:
        try:
            return handler(context, payload)
        except Exception as exc:  # noqa: BLE001 - fail closed at adapter boundary
            return StageResult(
                stage, StageStatus.FAILED, f"UNHANDLED_STAGE_ERROR:{type(exc).__name__}"
            )
