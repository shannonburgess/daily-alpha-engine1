from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from .pine_forward_deployment_evidence import ForwardParityDeploymentEvidence
from .pine_forward_reference import parse_forward_deployment_reference_snapshot
from .pine_historical_reference import _parse_market_rows
from .pine_historical_reference_locked import build_locked_historical_v24_reference
from .pine_parameter_manifest import parse_parameter_manifest
from .pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_STRATEGY_VERSION,
    V24Parameters,
)


class EvidenceArtifactState(StrEnum):
    MISSING = "MISSING"
    INVALID = "INVALID"
    PRESENT = "PRESENT"


@dataclass(frozen=True, slots=True)
class ForwardV24EvidenceReadiness:
    """Machine-readable inventory for the exact artifacts required by locked SH24 forward replay."""

    symbol: str
    reference_signal_ids: tuple[str, ...]
    reference_bar_times: tuple[str, ...]
    market_evidence_state: EvidenceArtifactState
    parameter_manifest_state: EvidenceArtifactState
    market_evidence_sha256: str | None
    parameter_manifest_sha256: str | None
    blockers: tuple[str, ...]
    diagnostics: tuple[str, ...]
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("evidence readiness cannot authorize trading")
        if self.ready_for_locked_replay and not self.reference_signal_ids:
            raise ValueError("locked forward replay cannot be ready without genuine reference events")

    @property
    def ready_for_locked_replay(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class HistoricalV24EvidenceReadiness:
    """Machine-readable inventory for the four independent SH24 historical proof artifacts."""

    symbol: str
    market_evidence_state: EvidenceArtifactState
    tradingview_signal_state: EvidenceArtifactState
    tradingview_bar_outcome_state: EvidenceArtifactState
    parameter_manifest_state: EvidenceArtifactState
    locked_reference_id: str | None
    blockers: tuple[str, ...]
    diagnostics: tuple[str, ...]
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("historical evidence readiness cannot authorize trading")
        if self.ready_for_locked_reference and self.locked_reference_id is None:
            raise ValueError("ready historical evidence requires a locked reference id")

    @property
    def ready_for_locked_reference(self) -> bool:
        return not self.blockers


def _present(text: str | None) -> bool:
    return bool(text and text.strip())


def _diagnostic(code: str, exc: Exception) -> str:
    detail = str(exc).strip().replace("\n", " ")
    return f"{code}:{type(exc).__name__}:{detail}" if detail else f"{code}:{type(exc).__name__}"


def assess_forward_v24_evidence_readiness(
    *,
    deployment: ForwardParityDeploymentEvidence,
    symbol: str,
    market_csv: str | None = None,
    parameter_manifest_json: str | None = None,
    market_source: str | None = None,
    market_revision: str | None = None,
    python_engine_revision: str | None = None,
) -> ForwardV24EvidenceReadiness:
    """Report exactly what is still missing before the trusted SH24 forward replay can run.

    This assessment never substitutes defaults, inferred market history, or reconstructed Pine settings.
    It validates supplied artifacts only; actual parity remains the responsibility of the locked replay
    evaluator after this readiness gate is complete.
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")

    snapshot = parse_forward_deployment_reference_snapshot(
        deployment.sh24,
        expected_model_id=PINE_V24_MODEL_ID,
        expected_strategy_version=PINE_V24_STRATEGY_VERSION,
    )
    if any(signal.symbol.upper() != normalized_symbol for signal in snapshot.signals):
        raise ValueError("forward receipt contains genuine events outside the requested symbol")

    reference_signal_ids = tuple(str(signal.source_id) for signal in snapshot.signals)
    reference_bar_times = tuple(signal.bar_time.isoformat() for signal in snapshot.signals)
    blockers: list[str] = []
    diagnostics: list[str] = []
    if not reference_signal_ids:
        blockers.append("NO_GENUINE_FORWARD_REFERENCE_EVENTS")

    market_state = EvidenceArtifactState.MISSING
    market_sha256: str | None = None
    market_bar_times = set()
    if not _present(market_csv):
        blockers.append("POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_MISSING")
    else:
        try:
            _normalized_rows, bar_times, _earnings_count = _parse_market_rows(
                market_csv or "",
                symbol=normalized_symbol,
            )
        except (TypeError, ValueError) as exc:
            market_state = EvidenceArtifactState.INVALID
            blockers.append("POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_INVALID")
            diagnostics.append(_diagnostic("MARKET_EVIDENCE", exc))
        else:
            market_state = EvidenceArtifactState.PRESENT
            market_sha256 = hashlib.sha256((market_csv or "").encode("utf-8")).hexdigest()
            market_bar_times = set(bar_times)
            missing_times = tuple(
                bar_time for bar_time in reference_bar_times if bar_time not in market_bar_times
            )
            if missing_times:
                blockers.append("REFERENCE_EVENT_BAR_MISSING_FROM_MARKET_EVIDENCE")
                diagnostics.append("MISSING_REFERENCE_BARS:" + ",".join(missing_times))

    if not (market_source and market_source.strip()):
        blockers.append("MARKET_SOURCE_IDENTITY_MISSING")
    if not (market_revision and market_revision.strip()):
        blockers.append("MARKET_SOURCE_REVISION_MISSING")
    if not (python_engine_revision and python_engine_revision.strip()):
        blockers.append("PYTHON_ENGINE_REVISION_MISSING")

    manifest_state = EvidenceArtifactState.MISSING
    manifest_sha256: str | None = None
    if not _present(parameter_manifest_json):
        blockers.append("EXACT_PINE_PARAMETER_MANIFEST_MISSING")
    else:
        try:
            manifest = parse_parameter_manifest(
                parameter_manifest_json or "",
                parameter_type=V24Parameters,
                expected_model_id=PINE_V24_MODEL_ID,
                expected_strategy_version=PINE_V24_STRATEGY_VERSION,
                expected_source_blob_sha=PINE_V24_SOURCE_BLOB_SHA,
                datetime_fields=frozenset({"start_time", "end_time"}),
            )
        except (TypeError, ValueError) as exc:
            manifest_state = EvidenceArtifactState.INVALID
            blockers.append("EXACT_PINE_PARAMETER_MANIFEST_INVALID")
            diagnostics.append(_diagnostic("PARAMETER_MANIFEST", exc))
        else:
            manifest_state = EvidenceArtifactState.PRESENT
            manifest_sha256 = manifest.sha256

    return ForwardV24EvidenceReadiness(
        symbol=normalized_symbol,
        reference_signal_ids=reference_signal_ids,
        reference_bar_times=reference_bar_times,
        market_evidence_state=market_state,
        parameter_manifest_state=manifest_state,
        market_evidence_sha256=market_sha256,
        parameter_manifest_sha256=manifest_sha256,
        blockers=tuple(dict.fromkeys(blockers)),
        diagnostics=tuple(diagnostics),
    )


def assess_historical_v24_evidence_readiness(
    *,
    symbol: str,
    market_csv: str | None = None,
    tradingview_signal_csv: str | None = None,
    tradingview_bar_outcome_csv: str | None = None,
    parameter_manifest_json: str | None = None,
    market_source: str | None = None,
    market_revision: str | None = None,
    tradingview_source: str | None = None,
    tradingview_signal_revision: str | None = None,
    tradingview_bar_outcome_revision: str | None = None,
) -> HistoricalV24EvidenceReadiness:
    """Inventory and validate the exact artifacts required for a locked SH24 historical reference."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")

    blockers: list[str] = []
    diagnostics: list[str] = []

    market_state = EvidenceArtifactState.PRESENT if _present(market_csv) else EvidenceArtifactState.MISSING
    signal_state = (
        EvidenceArtifactState.PRESENT
        if _present(tradingview_signal_csv)
        else EvidenceArtifactState.MISSING
    )
    bar_outcome_state = (
        EvidenceArtifactState.PRESENT
        if _present(tradingview_bar_outcome_csv)
        else EvidenceArtifactState.MISSING
    )
    manifest_state = (
        EvidenceArtifactState.PRESENT
        if _present(parameter_manifest_json)
        else EvidenceArtifactState.MISSING
    )

    if market_state is EvidenceArtifactState.MISSING:
        blockers.append("POINT_IN_TIME_MARKET_EARNINGS_EVIDENCE_MISSING")
    if signal_state is EvidenceArtifactState.MISSING:
        blockers.append("TRADINGVIEW_SIGNAL_REFERENCE_MISSING")
    if bar_outcome_state is EvidenceArtifactState.MISSING:
        blockers.append("TRADINGVIEW_BAR_OUTCOME_REFERENCE_MISSING")
    if manifest_state is EvidenceArtifactState.MISSING:
        blockers.append("EXACT_PINE_PARAMETER_MANIFEST_MISSING")

    metadata = {
        "MARKET_SOURCE_IDENTITY_MISSING": market_source,
        "MARKET_SOURCE_REVISION_MISSING": market_revision,
        "TRADINGVIEW_SOURCE_IDENTITY_MISSING": tradingview_source,
        "TRADINGVIEW_SIGNAL_REVISION_MISSING": tradingview_signal_revision,
        "TRADINGVIEW_BAR_OUTCOME_REVISION_MISSING": tradingview_bar_outcome_revision,
    }
    for code, value in metadata.items():
        if not (value and value.strip()):
            blockers.append(code)

    locked_reference_id: str | None = None
    if not blockers:
        try:
            locked = build_locked_historical_v24_reference(
                symbol=normalized_symbol,
                market_csv=market_csv or "",
                tradingview_signal_csv=tradingview_signal_csv or "",
                tradingview_bar_outcome_csv=tradingview_bar_outcome_csv or "",
                parameter_manifest_json=parameter_manifest_json or "",
                market_source=market_source or "",
                market_revision=market_revision or "",
                tradingview_source=tradingview_source or "",
                tradingview_signal_revision=tradingview_signal_revision or "",
                tradingview_bar_outcome_revision=tradingview_bar_outcome_revision or "",
            )
        except (TypeError, ValueError) as exc:
            blockers.append("HISTORICAL_EVIDENCE_BUNDLE_INVALID")
            diagnostics.append(_diagnostic("HISTORICAL_BUNDLE", exc))
            detail = str(exc)
            if "market" in detail.lower() or "earnings" in detail.lower():
                market_state = EvidenceArtifactState.INVALID
            if "signal" in detail.lower():
                signal_state = EvidenceArtifactState.INVALID
            if "bar" in detail.lower() and "outcome" in detail.lower():
                bar_outcome_state = EvidenceArtifactState.INVALID
            if "parameter" in detail.lower() or "PROCESS_ORDERS_ON_CLOSE" in detail:
                manifest_state = EvidenceArtifactState.INVALID
        else:
            locked_reference_id = locked.reference_id

    return HistoricalV24EvidenceReadiness(
        symbol=normalized_symbol,
        market_evidence_state=market_state,
        tradingview_signal_state=signal_state,
        tradingview_bar_outcome_state=bar_outcome_state,
        parameter_manifest_state=manifest_state,
        locked_reference_id=locked_reference_id,
        blockers=tuple(dict.fromkeys(blockers)),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "EvidenceArtifactState",
    "ForwardV24EvidenceReadiness",
    "HistoricalV24EvidenceReadiness",
    "assess_forward_v24_evidence_readiness",
    "assess_historical_v24_evidence_readiness",
]
