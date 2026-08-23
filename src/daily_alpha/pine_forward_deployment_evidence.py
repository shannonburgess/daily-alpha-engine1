from __future__ import annotations

import re
from collections.abc import Mapping
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
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ForwardParityDeploymentEvidence:
    """Validated, sanitized staging proof for the persisted-source monitor deployment."""

    repository: str
    commit_sha: str
    workflow_run_id: str
    workflow_run_attempt: str
    processor_version: str
    processor_code_sha256: str
    sh24_event_count_visible: int
    sh25_event_count_visible: int
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
        if self.sh24_event_count_visible < 0 or self.sh25_event_count_visible < 0:
            raise ValueError("forward deployment receipt event count is invalid")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("forward deployment evidence cannot authorize trading")

    @property
    def monitor_deployed(self) -> bool:
        return True


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _count(book: Mapping[str, Any], account_id: str) -> int:
    if book.get("scan_truncated") is not False:
        raise ValueError(f"{account_id} deployment evidence must be complete")
    value = int(book.get("event_count_visible", -1))
    if value < 0:
        raise ValueError(f"{account_id} event_count_visible is invalid")
    return value


def parse_forward_parity_deployment_receipt(
    receipt: Mapping[str, Any],
) -> ForwardParityDeploymentEvidence:
    """Validate the machine receipt produced by the trusted staging deployment workflow.

    The workflow itself verifies full Git ancestry before deployment. This parser refuses to turn a
    caller-supplied boolean into proof: the exact schema, canonical repository, pinned projection
    commit, processor identity, isolated books, complete monitor scans and hard-false safety state
    must all be present in one receipt.
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
    sh24 = _mapping(books["PAPER_SHADOW_V24"], "PAPER_SHADOW_V24")
    sh25 = _mapping(books["PAPER_SHADOW_V25"], "PAPER_SHADOW_V25")

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
        sh24_event_count_visible=_count(sh24, "PAPER_SHADOW_V24"),
        sh25_event_count_visible=_count(sh25, "PAPER_SHADOW_V25"),
    )


__all__ = [
    "EXPECTED_REPOSITORY",
    "FORWARD_PARITY_DEPLOYMENT_RECEIPT_SCHEMA",
    "PROJECTION_MINIMUM_COMMIT",
    "ForwardParityDeploymentEvidence",
    "parse_forward_parity_deployment_receipt",
]
