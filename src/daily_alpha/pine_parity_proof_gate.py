from __future__ import annotations

from dataclasses import dataclass

from .pine_forward_deployment_evidence import ForwardParityDeploymentEvidence
from .pine_forward_event_classification import partition_forward_events
from .pine_forward_reference import ReceiptBoundForwardParityEvaluation
from .pine_historical_reference import HistoricalV24Evaluation
from .pine_historical_reference_locked import LockedHistoricalV24Evaluation
from .pine_v24_parity import PINE_V24_SOURCE_BLOB_SHA


@dataclass(frozen=True, slots=True)
class V24ParityProofGate:
    """Fail-closed evidence gate for SH24 server-native source promotion."""

    historical_exact: bool
    historical_reference_signal_count: int
    historical_parameter_manifest_locked: bool
    forward_exact: bool
    forward_reference_signal_count: int
    forward_monitor_deployed: bool
    forward_deployment_commit_sha: str | None
    forward_replay_inputs_locked: bool
    forward_replay_evidence_id: str | None
    blockers: tuple[str, ...]
    parity_evidence_complete: bool
    promotion_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.historical_reference_signal_count < 0:
            raise ValueError("historical_reference_signal_count must be non-negative")
        if self.forward_reference_signal_count < 0:
            raise ValueError("forward_reference_signal_count must be non-negative")
        if self.forward_monitor_deployed != bool(self.forward_deployment_commit_sha):
            raise ValueError("forward monitor deployment state must carry exact commit evidence")
        if self.forward_replay_inputs_locked != bool(self.forward_replay_evidence_id):
            raise ValueError("forward replay lock state must carry exact replay evidence identity")
        if self.promotion_authorized:
            raise ValueError("parity proof gate cannot authorize promotion")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("parity proof gate cannot authorize trading")
        if self.parity_evidence_complete and self.blockers:
            raise ValueError("complete parity evidence cannot carry blockers")
        if self.parity_evidence_complete and not (
            self.historical_exact
            and self.historical_reference_signal_count > 0
            and self.historical_parameter_manifest_locked
            and self.forward_exact
            and self.forward_reference_signal_count > 0
            and self.forward_monitor_deployed
            and self.forward_deployment_commit_sha
            and self.forward_replay_inputs_locked
            and self.forward_replay_evidence_id
        ):
            raise ValueError("complete parity evidence is inconsistent with required proof gates")


def evaluate_v24_parity_proof_gate(
    *,
    historical_evaluation: HistoricalV24Evaluation | LockedHistoricalV24Evaluation | None,
    forward_evaluation: ReceiptBoundForwardParityEvaluation | None,
    forward_deployment_evidence: ForwardParityDeploymentEvidence | None,
) -> V24ParityProofGate:
    """Evaluate SH24 proof using receipt-bound events and locked replay-input provenance."""
    blockers: list[str] = []

    if historical_evaluation is None:
        historical_exact = False
        historical_reference_signal_count = 0
        historical_parameter_manifest_locked = False
        blockers.append("HISTORICAL_PARITY_EVIDENCE_MISSING")
    else:
        historical_exact = historical_evaluation.exact
        historical_reference_signal_count = historical_evaluation.signal_report.reference_count
        historical_parameter_manifest_locked = isinstance(
            historical_evaluation, LockedHistoricalV24Evaluation
        )
        if not historical_exact:
            blockers.append("HISTORICAL_PARITY_MISMATCH")
        if historical_reference_signal_count == 0:
            blockers.append("HISTORICAL_GENUINE_SIGNAL_EVIDENCE_EMPTY")
        if not historical_parameter_manifest_locked:
            blockers.append("HISTORICAL_PARAMETER_MANIFEST_NOT_LOCKED")

    forward_monitor_deployed = forward_deployment_evidence is not None
    forward_deployment_commit_sha = (
        forward_deployment_evidence.commit_sha if forward_deployment_evidence is not None else None
    )
    if not forward_monitor_deployed:
        blockers.append("FORWARD_PARITY_MONITOR_DEPLOYMENT_EVIDENCE_MISSING")

    if forward_evaluation is None:
        forward_exact = False
        forward_reference_signal_count = 0
        forward_replay_inputs_locked = False
        forward_replay_evidence_id = None
        blockers.append("FORWARD_PARITY_EVIDENCE_MISSING")
    else:
        forward_exact = forward_evaluation.exact
        forward_reference_signal_count = forward_evaluation.report.reference_count
        forward_replay_inputs_locked = forward_evaluation.replay_inputs_locked
        forward_replay_evidence_id = (
            forward_evaluation.replay_provenance.evidence_id
            if forward_evaluation.replay_provenance is not None
            else None
        )
        if forward_evaluation.model_id != "PAPER_SHADOW_V24":
            blockers.append("FORWARD_PARITY_BOOK_MISMATCH")
        if forward_evaluation.strategy_version != "2.4":
            blockers.append("FORWARD_PARITY_VERSION_MISMATCH")
        if not forward_replay_inputs_locked:
            blockers.append("FORWARD_REPLAY_INPUT_EVIDENCE_NOT_LOCKED")
        elif (
            forward_evaluation.replay_provenance is not None
            and forward_evaluation.replay_provenance.strategy_source_blob_sha
            != PINE_V24_SOURCE_BLOB_SHA
        ):
            blockers.append("FORWARD_REPLAY_SOURCE_MISMATCH")
        if forward_deployment_evidence is None:
            blockers.append("FORWARD_PARITY_EVALUATION_NOT_DEPLOYMENT_BOUND")
        else:
            if forward_evaluation.deployment_commit_sha != forward_deployment_evidence.commit_sha:
                blockers.append("FORWARD_PARITY_DEPLOYMENT_COMMIT_MISMATCH")
            if (
                forward_evaluation.processor_code_sha256
                != forward_deployment_evidence.processor_code_sha256
            ):
                blockers.append("FORWARD_PARITY_PROCESSOR_CODE_MISMATCH")
            genuine_count = partition_forward_events(
                forward_deployment_evidence.sh24
            ).reference_candidate_count
            if forward_evaluation.reference_snapshot.event_count_visible != genuine_count:
                blockers.append("FORWARD_PARITY_RECEIPT_EVENT_COUNT_MISMATCH")
        if not forward_exact:
            blockers.append("FORWARD_PARITY_MISMATCH")
        if forward_reference_signal_count == 0:
            blockers.append("FORWARD_GENUINE_SIGNAL_EVIDENCE_EMPTY")

    normalized_blockers = tuple(dict.fromkeys(blockers))
    return V24ParityProofGate(
        historical_exact=historical_exact,
        historical_reference_signal_count=historical_reference_signal_count,
        historical_parameter_manifest_locked=historical_parameter_manifest_locked,
        forward_exact=forward_exact,
        forward_reference_signal_count=forward_reference_signal_count,
        forward_monitor_deployed=forward_monitor_deployed,
        forward_deployment_commit_sha=forward_deployment_commit_sha,
        forward_replay_inputs_locked=forward_replay_inputs_locked,
        forward_replay_evidence_id=forward_replay_evidence_id,
        blockers=normalized_blockers,
        parity_evidence_complete=not normalized_blockers,
    )


__all__ = ["V24ParityProofGate", "evaluate_v24_parity_proof_gate"]
