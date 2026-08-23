from __future__ import annotations

from dataclasses import dataclass

from .pine_forward_deployment_evidence import ForwardParityDeploymentEvidence
from .pine_parity_compare import ParityReport
from .pine_v25_historical_reference import HistoricalV25Evaluation


@dataclass(frozen=True, slots=True)
class V25ParityProofGate:
    """Fail-closed evidence gate for SH25 challenger parity completion.

    The gate is evidence-only. It cannot authorize promotion, PAPER execution, broker routing, or
    live trading. Historical proof must be exact, parameter-locked, and contain at least one
    genuine TradingView strategy event. Forward proof must be exact, non-empty, and bound to a
    validated machine deployment receipt for the persisted-source monitor.
    """

    historical_exact: bool
    historical_reference_signal_count: int
    historical_parameter_manifest_locked: bool
    forward_exact: bool
    forward_reference_signal_count: int
    forward_monitor_deployed: bool
    forward_deployment_commit_sha: str | None
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
        ):
            raise ValueError("complete parity evidence is inconsistent with required proof gates")


def evaluate_v25_parity_proof_gate(
    *,
    historical_evaluation: HistoricalV25Evaluation | None,
    forward_report: ParityReport | None,
    forward_deployment_evidence: ForwardParityDeploymentEvidence | None,
) -> V25ParityProofGate:
    """Evaluate minimum SH25 evidence while preserving strict book/source isolation.

    A caller cannot assert deployment with a free boolean. The forward monitor must already have
    been validated from the trusted staging receipt, including canonical repository/processor
    identity, exact SH24/SH25 books, complete scans and hard-false trading/live flags.
    """
    blockers: list[str] = []

    if historical_evaluation is None:
        historical_exact = False
        historical_reference_signal_count = 0
        historical_parameter_manifest_locked = False
        blockers.append("HISTORICAL_PARITY_EVIDENCE_MISSING")
    else:
        historical_exact = historical_evaluation.exact
        historical_reference_signal_count = historical_evaluation.signal_report.reference_count
        historical_parameter_manifest_locked = bool(
            historical_evaluation.parameter_manifest_sha256
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

    if forward_report is None:
        forward_exact = False
        forward_reference_signal_count = 0
        blockers.append("FORWARD_PARITY_EVIDENCE_MISSING")
    else:
        forward_exact = forward_report.exact
        forward_reference_signal_count = forward_report.reference_count
        if not forward_exact:
            blockers.append("FORWARD_PARITY_MISMATCH")
        if forward_reference_signal_count == 0:
            blockers.append("FORWARD_GENUINE_SIGNAL_EVIDENCE_EMPTY")

    normalized_blockers = tuple(dict.fromkeys(blockers))
    return V25ParityProofGate(
        historical_exact=historical_exact,
        historical_reference_signal_count=historical_reference_signal_count,
        historical_parameter_manifest_locked=historical_parameter_manifest_locked,
        forward_exact=forward_exact,
        forward_reference_signal_count=forward_reference_signal_count,
        forward_monitor_deployed=forward_monitor_deployed,
        forward_deployment_commit_sha=forward_deployment_commit_sha,
        blockers=normalized_blockers,
        parity_evidence_complete=not normalized_blockers,
    )


__all__ = ["V25ParityProofGate", "evaluate_v25_parity_proof_gate"]
