from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from .pine_forward_locked_replay import LockedForwardV24Evaluation
from .pine_historical_reference_locked import LockedHistoricalV24Evaluation
from .pine_paired_evidence_capture import PairedHistoricalEvidenceReadiness
from .pine_parity_proof_gate import V24ParityProofGate
from .pine_v25_forward_locked_replay import LockedForwardV25Evaluation
from .pine_v25_historical_reference import HistoricalV25Evaluation
from .pine_v25_parity_proof_gate import V25ParityProofGate


class PairedParityProofStatus(StrEnum):
    """Outcome classification that never confuses absent evidence with failed parity."""

    MISSING_EXTERNAL_EVIDENCE = "MISSING_EXTERNAL_EVIDENCE"
    FAILED_PARITY = "FAILED_PARITY"
    PASSED = "PASSED"


_DIRECT_PARITY_MISMATCH_BLOCKERS = frozenset(
    {
        "HISTORICAL_PARITY_MISMATCH",
        "FORWARD_PARITY_MISMATCH",
    }
)


@dataclass(frozen=True, slots=True)
class PairedPineParityProofGate:
    """Fail-closed CONTROL/CHALLENGER proof bound to exact paired evidence inputs."""

    status: PairedParityProofStatus
    paired_capture_id: str | None
    sh24_parity_evidence_complete: bool
    sh25_parity_evidence_complete: bool
    shared_forward_market_sha256: str | None
    shared_forward_market_revision: str | None
    shared_forward_deployment_commit_sha: str | None
    sh24_forward_replay_evidence_id: str | None
    sh25_forward_replay_evidence_id: str | None
    blockers: tuple[str, ...]
    proof_id: str | None
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.promotion_authorized:
            raise ValueError("paired parity proof cannot authorize promotion")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("paired parity proof cannot authorize trading")
        if self.status is PairedParityProofStatus.PASSED:
            if self.blockers:
                raise ValueError("passed paired parity proof cannot carry blockers")
            if not self.paired_capture_id or not self.proof_id:
                raise ValueError("passed paired parity proof requires exact evidence identities")
            if not self.sh24_parity_evidence_complete or not self.sh25_parity_evidence_complete:
                raise ValueError("passed paired parity proof requires both strategy proof gates")
            if not self.shared_forward_market_sha256 or not self.shared_forward_market_revision:
                raise ValueError("passed paired parity proof requires one shared forward market")
            if not self.shared_forward_deployment_commit_sha:
                raise ValueError("passed paired parity proof requires one deployment commit")
            if not self.sh24_forward_replay_evidence_id or not self.sh25_forward_replay_evidence_id:
                raise ValueError("passed paired parity proof requires both replay identities")
            if self.sh24_forward_replay_evidence_id == self.sh25_forward_replay_evidence_id:
                raise ValueError("CONTROL and CHALLENGER replay identities must be distinct")
        elif self.proof_id is not None:
            raise ValueError("incomplete paired parity proof cannot mint proof identity")


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prefix(prefix: str, blockers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{prefix}:{blocker}" for blocker in blockers)


def _direct_parity_failed(gate: V24ParityProofGate | V25ParityProofGate) -> bool:
    return any(blocker in _DIRECT_PARITY_MISMATCH_BLOCKERS for blocker in gate.blockers)


def evaluate_paired_pine_parity_proof_gate(
    *,
    historical_readiness: PairedHistoricalEvidenceReadiness | None,
    sh24_historical_evaluation: LockedHistoricalV24Evaluation | None,
    sh25_historical_evaluation: HistoricalV25Evaluation | None,
    sh24_forward_evaluation: LockedForwardV24Evaluation | None,
    sh25_forward_evaluation: LockedForwardV25Evaluation | None,
    sh24_gate: V24ParityProofGate,
    sh25_gate: V25ParityProofGate,
) -> PairedPineParityProofGate:
    """Bind both frozen parity gates to one paired historical and forward evidence cohort.

    The two strategy-specific proof gates remain authoritative for their individual parity checks.
    This layer prevents a CONTROL proof and CHALLENGER proof from being combined when they were
    produced from different historical captures, point-in-time forward market artifacts, processor
    deployments, or replay identities. Missing/invalid/cross-wired evidence is deliberately kept
    separate from an observed Pine/Python parity mismatch.
    """
    blockers: list[str] = []
    paired_capture_id: str | None = None
    paired_history_ready = historical_readiness is not None and historical_readiness.ready

    if historical_readiness is None:
        blockers.append("PAIRED_HISTORICAL_EVIDENCE_MISSING")
    elif not historical_readiness.ready:
        blockers.append("PAIRED_HISTORICAL_EVIDENCE_NOT_READY")
        blockers.extend(_prefix("PAIRED_HISTORY", historical_readiness.blockers))
    else:
        paired_capture_id = historical_readiness.paired_capture_id
        if not paired_capture_id:
            blockers.append("PAIRED_HISTORICAL_CAPTURE_ID_MISSING")

        if sh24_historical_evaluation is None:
            blockers.append("SH24_LOCKED_HISTORICAL_EVALUATION_MISSING")
        elif sh24_historical_evaluation.reference_id != historical_readiness.sh24.locked_reference_id:
            blockers.append("SH24_HISTORICAL_EVALUATION_NOT_BOUND_TO_PAIRED_CAPTURE")
        else:
            if sh24_gate.historical_exact != sh24_historical_evaluation.exact:
                blockers.append("SH24_GATE_HISTORICAL_RESULT_NOT_BOUND_TO_EVALUATION")
            if (
                sh24_gate.historical_reference_signal_count
                != sh24_historical_evaluation.signal_report.reference_count
            ):
                blockers.append("SH24_GATE_HISTORICAL_COUNT_NOT_BOUND_TO_EVALUATION")

        if sh25_historical_evaluation is None:
            blockers.append("SH25_LOCKED_HISTORICAL_EVALUATION_MISSING")
        elif sh25_historical_evaluation.reference_id != historical_readiness.sh25.locked_reference_id:
            blockers.append("SH25_HISTORICAL_EVALUATION_NOT_BOUND_TO_PAIRED_CAPTURE")
        else:
            if sh25_gate.historical_exact != sh25_historical_evaluation.exact:
                blockers.append("SH25_GATE_HISTORICAL_RESULT_NOT_BOUND_TO_EVALUATION")
            if (
                sh25_gate.historical_reference_signal_count
                != sh25_historical_evaluation.signal_report.reference_count
            ):
                blockers.append("SH25_GATE_HISTORICAL_COUNT_NOT_BOUND_TO_EVALUATION")

    shared_forward_market_sha256: str | None = None
    shared_forward_market_revision: str | None = None
    shared_forward_deployment_commit_sha: str | None = None

    if sh24_forward_evaluation is None:
        blockers.append("SH24_LOCKED_FORWARD_EVALUATION_MISSING")
    else:
        if sh24_gate.forward_replay_evidence_id != sh24_forward_evaluation.replay_provenance.evidence_id:
            blockers.append("SH24_GATE_FORWARD_REPLAY_NOT_BOUND_TO_EVALUATION")
        if sh24_gate.forward_exact != sh24_forward_evaluation.exact:
            blockers.append("SH24_GATE_FORWARD_RESULT_NOT_BOUND_TO_EVALUATION")
        if sh24_gate.forward_reference_signal_count != sh24_forward_evaluation.report.reference_count:
            blockers.append("SH24_GATE_FORWARD_COUNT_NOT_BOUND_TO_EVALUATION")
        if sh24_gate.forward_deployment_commit_sha != sh24_forward_evaluation.deployment_commit_sha:
            blockers.append("SH24_GATE_FORWARD_DEPLOYMENT_NOT_BOUND_TO_EVALUATION")

    if sh25_forward_evaluation is None:
        blockers.append("SH25_LOCKED_FORWARD_EVALUATION_MISSING")
    else:
        if sh25_gate.forward_replay_evidence_id != sh25_forward_evaluation.replay_provenance.evidence_id:
            blockers.append("SH25_GATE_FORWARD_REPLAY_NOT_BOUND_TO_EVALUATION")
        if sh25_gate.forward_exact != sh25_forward_evaluation.exact:
            blockers.append("SH25_GATE_FORWARD_RESULT_NOT_BOUND_TO_EVALUATION")
        if sh25_gate.forward_reference_signal_count != sh25_forward_evaluation.report.reference_count:
            blockers.append("SH25_GATE_FORWARD_COUNT_NOT_BOUND_TO_EVALUATION")
        if sh25_gate.forward_deployment_commit_sha != sh25_forward_evaluation.deployment_commit_sha:
            blockers.append("SH25_GATE_FORWARD_DEPLOYMENT_NOT_BOUND_TO_EVALUATION")

    if sh24_forward_evaluation is not None and sh25_forward_evaluation is not None:
        sh24_market = sh24_forward_evaluation.market_artifact
        sh25_market = sh25_forward_evaluation.market_artifact
        market_identity_matches = (
            sh24_market.sha256 == sh25_market.sha256
            and sh24_market.revision == sh25_market.revision
            and sh24_market.row_count == sh25_market.row_count
            and sh24_forward_evaluation.market_start_iso == sh25_forward_evaluation.market_start_iso
            and sh24_forward_evaluation.market_end_iso == sh25_forward_evaluation.market_end_iso
        )
        if market_identity_matches:
            shared_forward_market_sha256 = sh24_market.sha256
            shared_forward_market_revision = sh24_market.revision
        else:
            blockers.append("CONTROL_CHALLENGER_FORWARD_MARKET_EVIDENCE_NOT_IDENTICAL")

        same_deployment = (
            sh24_forward_evaluation.deployment_commit_sha
            == sh25_forward_evaluation.deployment_commit_sha
            and sh24_forward_evaluation.processor_code_sha256
            == sh25_forward_evaluation.processor_code_sha256
        )
        if same_deployment:
            shared_forward_deployment_commit_sha = sh24_forward_evaluation.deployment_commit_sha
        else:
            blockers.append("CONTROL_CHALLENGER_FORWARD_DEPLOYMENT_NOT_IDENTICAL")

        if (
            sh24_forward_evaluation.replay_provenance.evidence_id
            == sh25_forward_evaluation.replay_provenance.evidence_id
        ):
            blockers.append("CONTROL_CHALLENGER_FORWARD_REPLAY_IDENTITIES_NOT_DISTINCT")

    blockers.extend(_prefix("SH24", sh24_gate.blockers))
    blockers.extend(_prefix("SH25", sh25_gate.blockers))
    normalized_blockers = tuple(dict.fromkeys(blockers))

    if not paired_history_ready:
        status = PairedParityProofStatus.MISSING_EXTERNAL_EVIDENCE
    elif _direct_parity_failed(sh24_gate) or _direct_parity_failed(sh25_gate):
        status = PairedParityProofStatus.FAILED_PARITY
    elif normalized_blockers:
        status = PairedParityProofStatus.MISSING_EXTERNAL_EVIDENCE
    else:
        status = PairedParityProofStatus.PASSED

    proof_id: str | None = None
    if status is PairedParityProofStatus.PASSED:
        proof_id = _digest(
            {
                "schema": "DAILY_ALPHA_PAIRED_PINE_PARITY_PROOF_V1",
                "paired_capture_id": paired_capture_id,
                "shared_forward_market_sha256": shared_forward_market_sha256,
                "shared_forward_market_revision": shared_forward_market_revision,
                "shared_forward_deployment_commit_sha": shared_forward_deployment_commit_sha,
                "sh24_forward_replay_evidence_id": sh24_gate.forward_replay_evidence_id,
                "sh25_forward_replay_evidence_id": sh25_gate.forward_replay_evidence_id,
                "sh24_parity_evidence_complete": sh24_gate.parity_evidence_complete,
                "sh25_parity_evidence_complete": sh25_gate.parity_evidence_complete,
                "promotion_authorized": False,
                "trading_authorized": False,
                "live_trading_enabled": False,
            }
        )

    return PairedPineParityProofGate(
        status=status,
        paired_capture_id=paired_capture_id,
        sh24_parity_evidence_complete=sh24_gate.parity_evidence_complete,
        sh25_parity_evidence_complete=sh25_gate.parity_evidence_complete,
        shared_forward_market_sha256=shared_forward_market_sha256,
        shared_forward_market_revision=shared_forward_market_revision,
        shared_forward_deployment_commit_sha=shared_forward_deployment_commit_sha,
        sh24_forward_replay_evidence_id=sh24_gate.forward_replay_evidence_id,
        sh25_forward_replay_evidence_id=sh25_gate.forward_replay_evidence_id,
        blockers=normalized_blockers,
        proof_id=proof_id,
    )


__all__ = [
    "PairedParityProofStatus",
    "PairedPineParityProofGate",
    "evaluate_paired_pine_parity_proof_gate",
]
