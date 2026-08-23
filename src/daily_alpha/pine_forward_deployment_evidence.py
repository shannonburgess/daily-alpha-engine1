from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA = (
    "DAILY_ALPHA_FORWARD_PARITY_DEPLOYMENT_RECEIPT_V1"
)
EXPECTED_REPOSITORY = "shannonburgess/daily-alpha-engine1"
PROJECTION_MINIMUM_COMMIT = "32b4626a9b1138d4a1e9788f533d6a06ac5f929a"
EXPECTED_PROCESSOR = "daily-alpha-pine-processor"
EXPECTED_HANDLER = "lambda_handlers.pine_processor.lambda_handler"
EXPECTED_BOOKS = ("PAPER_SHADOW_V24", "PAPER_SHADOW_V25")
EXPECTED_STRATEGY = "DA_TURTLE_ADAPTIVE_TREND"
EXPECTED_SOURCE = "TRADINGVIEW_PINE"
EXPECTED_STRATEGY_VERSION = {
    "PAPER_SHADOW_V24": "2.4",
    "PAPER_SHADOW_V25": "2.5",
}
CANONICAL_DAILY_TIMEFRAMES = frozenset({"D", "1D"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ForwardPersistedEventEvidence:
    """Immutable sanitized source-event evidence retained in a trusted deployment receipt."""

    account_id: str
    signal_id: str
    fields: tuple[tuple[str, Any], ...]

    def __post_init__(self) -> None:
        if self.account_id not in EXPECTED_BOOKS:
            raise ValueError("forward persisted event account is not an isolated parity book")
        if not self.signal_id:
            raise ValueError("forward persisted event signal_id is required")
        payload = dict(self.fields)
        if payload.get("signal_id") != self.signal_id:
            raise ValueError("forward persisted event signal_id is inconsistent")
        if payload.get("model_id") != self.account_id:
            raise ValueError("forward persisted event crossed the requested model book")
        if payload.get("source") != EXPECTED_SOURCE:
            raise ValueError("forward persisted event source is not TradingView Pine")
        if payload.get("strategy") != EXPECTED_STRATEGY:
            raise ValueError("forward persisted event strategy is not canonical")
        expected_version = EXPECTED_STRATEGY_VERSION[self.account_id]
        if payload.get("strategy_version") != expected_version:
            raise ValueError("forward persisted event strategy version crossed its book")
        if payload.get("timeframe") not in CANONICAL_DAILY_TIMEFRAMES:
            raise ValueError("forward persisted event timeframe is not canonical daily")
        if payload.get("trading_authorized") is not False:
            raise ValueError("forward persisted event trading_authorized must remain false")
        if payload.get("live_trading_enabled") is not False:
            raise ValueError("forward persisted event live_trading_enabled must remain false")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.fields)


@dataclass(frozen=True, slots=True)
class ForwardParityBookEvidence:
    """Complete bounded persisted-event evidence for one isolated shadow book."""

    account_id: str
    event_count_visible: int
    event_count_scanned: int
    event_history_omitted: int
    event_limit: int
    scan_pages: int
    scan_items_evaluated: int
    open_count: int
    armed_count_visible: int
    events: tuple[ForwardPersistedEventEvidence, ...]

    def __post_init__(self) -> None:
        if self.account_id not in EXPECTED_BOOKS:
            raise ValueError("forward deployment book is not an isolated parity book")
        for value in (
            self.event_count_visible,
            self.event_count_scanned,
            self.event_history_omitted,
            self.scan_items_evaluated,
            self.open_count,
            self.armed_count_visible,
        ):
            if value < 0:
                raise ValueError("forward deployment book count is invalid")
        if self.event_limit < 1 or self.scan_pages < 1:
            raise ValueError("forward deployment book bounds are invalid")
        if self.event_count_visible != len(self.events):
            raise ValueError("forward deployment visible event count does not match events")
        if self.event_count_scanned != self.event_count_visible + self.event_history_omitted:
            raise ValueError("forward deployment event scan counts do not reconcile")
        if self.event_history_omitted != 0:
            raise ValueError("forward deployment receipt omitted persisted event history")
        if self.event_limit < self.event_count_visible:
            raise ValueError("forward deployment event limit is below visible event count")
        signal_ids = tuple(event.signal_id for event in self.events)
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("forward deployment receipt contains duplicate signal_id evidence")
        if any(event.account_id != self.account_id for event in self.events):
            raise ValueError("forward deployment receipt event crossed its model book")

    def to_reference_book_state(self) -> dict[str, Any]:
        """Project trusted receipt evidence into the strict forward-reference adapter contract."""
        return {
            "events": [event.to_dict() for event in self.events],
            "event_count_visible": self.event_count_visible,
            "event_limit": self.event_limit,
            "scan_items_evaluated": self.scan_items_evaluated,
            "scan_truncated": False,
        }


@dataclass(frozen=True, slots=True)
class ForwardParityDeploymentEvidence:
    """Validated, sanitized staging proof for the persisted-source monitor deployment."""

    repository: str
    commit_sha: str
    workflow_run_id: str
    workflow_run_attempt: str
    processor_version: str
    processor_code_sha256: str
    sh24: ForwardParityBookEvidence
    sh25: ForwardParityBookEvidence
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.repository != EXPECTED_REPOSITORY:
            raise ValueError("forward deployment receipt repository is not canonical")
        if not _SHA_RE.fullmatch(self.commit_sha):
            raise ValueError("forward deployment receipt commit SHA is invalid")
        if not self.workflow_run_id or not self.workflow_run_attempt:
            raise ValueError("forward deployment receipt workflow identity is incomplete")
        if not self.processor_version or not self.processor_code_sha256:
            raise ValueError("forward deployment receipt processor identity is incomplete")
        if self.sh24.account_id != "PAPER_SHADOW_V24":
            raise ValueError("forward deployment SH24 evidence is misbound")
        if self.sh25.account_id != "PAPER_SHADOW_V25":
            raise ValueError("forward deployment SH25 evidence is misbound")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("forward deployment evidence cannot authorize trading")

    @property
    def monitor_deployed(self) -> bool:
        return True

    @property
    def sh24_event_count_visible(self) -> int:
        return self.sh24.event_count_visible

    @property
    def sh25_event_count_visible(self) -> int:
        return self.sh25.event_count_visible


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a list")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{field} is below its minimum")
    return parsed


def _event_evidence(raw: Any, account_id: str, index: int) -> ForwardPersistedEventEvidence:
    event = _mapping(raw, f"{account_id}.events[{index}]")
    for field, value in event.items():
        if isinstance(value, (Mapping, list, tuple, set)):
            raise TypeError(f"{account_id}.events[{index}].{field} must be scalar")
    signal_id = _text(event.get("signal_id"), f"{account_id}.events[{index}].signal_id")
    normalized = tuple(sorted((str(key), value) for key, value in event.items()))
    return ForwardPersistedEventEvidence(
        account_id=account_id,
        signal_id=signal_id,
        fields=normalized,
    )


def _book_evidence(book: Mapping[str, Any], account_id: str) -> ForwardParityBookEvidence:
    if book.get("scan_truncated") is not False:
        raise ValueError(f"{account_id} deployment evidence must be complete")
    events_raw = _sequence(book.get("events"), f"{account_id}.events")
    events = tuple(
        _event_evidence(raw, account_id, index) for index, raw in enumerate(events_raw)
    )
    return ForwardParityBookEvidence(
        account_id=account_id,
        event_count_visible=_integer(
            book.get("event_count_visible"), f"{account_id}.event_count_visible"
        ),
        event_count_scanned=_integer(
            book.get("event_count_scanned"), f"{account_id}.event_count_scanned"
        ),
        event_history_omitted=_integer(
            book.get("event_history_omitted"), f"{account_id}.event_history_omitted"
        ),
        event_limit=_integer(book.get("event_limit"), f"{account_id}.event_limit", minimum=1),
        scan_pages=_integer(book.get("scan_pages"), f"{account_id}.scan_pages", minimum=1),
        scan_items_evaluated=_integer(
            book.get("scan_items_evaluated"), f"{account_id}.scan_items_evaluated"
        ),
        open_count=_integer(book.get("open_count"), f"{account_id}.open_count"),
        armed_count_visible=_integer(
            book.get("armed_count_visible"), f"{account_id}.armed_count_visible"
        ),
        events=events,
    )


def parse_forward_parity_deployment_receipt(
    receipt: Mapping[str, Any],
) -> ForwardParityDeploymentEvidence:
    """Validate the machine receipt produced by the trusted staging deployment workflow.

    The workflow verifies Git ancestry before deployment. This parser requires the exact schema,
    canonical repository, pinned projection commit, processor identity, isolated books, complete
    persisted-event history and hard-false safety state in one receipt.
    """
    if not isinstance(receipt, Mapping):
        raise TypeError("forward deployment receipt must be an object")
    if receipt.get("schema") != FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA:
        raise ValueError("forward deployment receipt schema is unsupported")
    if receipt.get("repository") != EXPECTED_REPOSITORY:
        raise ValueError("forward deployment receipt repository is not canonical")
    if receipt.get("projection_minimum_commit") != PROJECTION_MINIMUM_COMMIT:
        raise ValueError("forward deployment receipt projection lineage is not canonical")
    if receipt.get("projection_ancestor_verified") is not True:
        raise ValueError("forward deployment receipt projection ancestry is unverified")
    if receipt.get("trading_authorized") is not False:
        raise ValueError("forward deployment receipt trading_authorized must remain false")
    if receipt.get("live_trading_enabled") is not False:
        raise ValueError("forward deployment receipt live_trading_enabled must remain false")

    processor = _mapping(receipt.get("processor"), "processor")
    if processor.get("function_name") != EXPECTED_PROCESSOR:
        raise ValueError("forward deployment receipt processor function is not canonical")
    if processor.get("handler") != EXPECTED_HANDLER:
        raise ValueError("forward deployment receipt processor handler is not canonical")
    if processor.get("last_update_status") != "Successful":
        raise ValueError("forward deployment receipt processor update is not successful")

    books = _mapping(receipt.get("books"), "books")
    if set(books) != set(EXPECTED_BOOKS):
        raise ValueError("forward deployment receipt books are not exactly SH24 and SH25")
    sh24 = _book_evidence(
        _mapping(books["PAPER_SHADOW_V24"], "PAPER_SHADOW_V24"),
        "PAPER_SHADOW_V24",
    )
    sh25 = _book_evidence(
        _mapping(books["PAPER_SHADOW_V25"], "PAPER_SHADOW_V25"),
        "PAPER_SHADOW_V25",
    )

    commit_sha = _text(receipt.get("commit_sha"), "commit_sha").lower()
    if not _SHA_RE.fullmatch(commit_sha):
        raise ValueError("forward deployment receipt commit SHA is invalid")

    return ForwardParityDeploymentEvidence(
        repository=EXPECTED_REPOSITORY,
        commit_sha=commit_sha,
        workflow_run_id=_text(receipt.get("workflow_run_id"), "workflow_run_id"),
        workflow_run_attempt=_text(
            receipt.get("workflow_run_attempt"), "workflow_run_attempt"
        ),
        processor_version=_text(processor.get("version"), "processor.version"),
        processor_code_sha256=_text(
            processor.get("code_sha256"), "processor.code_sha256"
        ),
        sh24=sh24,
        sh25=sh25,
    )


__all__ = [
    "CANONICAL_DAILY_TIMEFRAMES",
    "EXPECTED_REPOSITORY",
    "FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA",
    "PROJECTION_MINIMUM_COMMIT",
    "ForwardParityBookEvidence",
    "ForwardParityDeploymentEvidence",
    "ForwardPersistedEventEvidence",
    "parse_forward_parity_deployment_receipt",
]
