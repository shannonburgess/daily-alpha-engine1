from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .pine_bar_outcome_compare import (
    BarOutcomeReport,
    ReferenceBarOutcome,
    compare_bar_outcomes,
)
from .pine_historical_reference import (
    HistoricalSourceArtifact,
    _artifact,
    _parse_bar_outcomes,
    _parse_market_rows,
    _parse_signal_rows,
    _required_text,
)
from .pine_parameter_manifest import PineParameterManifest, parse_parameter_manifest
from .pine_parity_compare import ParityReport
from .pine_parity_evidence import (
    PARITY_EVIDENCE_SCHEMA_VERSION,
    ParityEvidenceBundle,
    parse_parity_evidence_bundle,
)
from .pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_BLOB_SHA,
    PINE_V25_STRATEGY_VERSION,
    V25Parameters,
    run_v25_parity,
)
from .pine_v25_parity_evidence import evaluate_v25_evidence


@dataclass(frozen=True, slots=True)
class HistoricalV25Reference:
    bundle: ParityEvidenceBundle
    reference_bar_outcomes: tuple[ReferenceBarOutcome, ...]
    parameter_manifest: PineParameterManifest
    market_artifact: HistoricalSourceArtifact
    signal_artifact: HistoricalSourceArtifact
    bar_outcome_artifact: HistoricalSourceArtifact

    @property
    def reference_id(self) -> str:
        payload = {
            "model_id": self.bundle.model_id,
            "strategy_version": self.bundle.strategy_version,
            "strategy_source_revision": self.bundle.source_revision,
            "symbol": self.bundle.symbol,
            "parameter_sha256": self.parameter_manifest.sha256,
            "market_sha256": self.market_artifact.sha256,
            "signal_sha256": self.signal_artifact.sha256,
            "bar_outcome_sha256": self.bar_outcome_artifact.sha256,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalV25Evaluation:
    reference_id: str
    signal_report: ParityReport
    bar_outcome_report: BarOutcomeReport

    @property
    def exact(self) -> bool:
        return self.signal_report.exact and self.bar_outcome_report.exact


def build_historical_v25_reference(
    *,
    symbol: str,
    market_csv: str,
    tradingview_signal_csv: str,
    tradingview_bar_outcome_csv: str,
    parameter_manifest_json: str,
    market_source: str,
    market_revision: str,
    tradingview_source: str,
    tradingview_signal_revision: str,
    tradingview_bar_outcome_revision: str,
) -> HistoricalV25Reference:
    """Build a fully parameter-locked SH25 point-in-time historical reference."""
    normalized_symbol = _required_text(symbol, "SYMBOL").upper()
    bars, bar_times, _earnings_count = _parse_market_rows(
        market_csv,
        symbol=normalized_symbol,
    )
    signals, signal_actions_by_time = _parse_signal_rows(
        tradingview_signal_csv,
        symbol=normalized_symbol,
        bar_times=bar_times,
    )
    bar_outcomes = _parse_bar_outcomes(
        tradingview_bar_outcome_csv,
        symbol=normalized_symbol,
        bar_times=bar_times,
        signal_actions_by_time=signal_actions_by_time,
    )
    manifest = parse_parameter_manifest(
        parameter_manifest_json,
        parameter_type=V25Parameters,
        expected_model_id=PINE_V25_MODEL_ID,
        expected_strategy_version=PINE_V25_STRATEGY_VERSION,
        expected_source_blob_sha=PINE_V25_SOURCE_BLOB_SHA,
        datetime_fields=frozenset(
            {"start_time", "end_time", "shadow_forward_start"}
        ),
    )
    bundle = parse_parity_evidence_bundle(
        {
            "schema_version": PARITY_EVIDENCE_SCHEMA_VERSION,
            "source": _required_text(tradingview_source, "TRADINGVIEW_SOURCE"),
            "source_revision": PINE_V25_SOURCE_BLOB_SHA,
            "model_id": PINE_V25_MODEL_ID,
            "strategy_version": PINE_V25_STRATEGY_VERSION,
            "symbol": normalized_symbol,
            "bars": bars,
            "reference_signals": signals,
        }
    )
    return HistoricalV25Reference(
        bundle=bundle,
        reference_bar_outcomes=bar_outcomes,
        parameter_manifest=manifest,
        market_artifact=_artifact(
            market_source,
            market_revision,
            market_csv,
            len(bars),
        ),
        signal_artifact=_artifact(
            tradingview_source,
            tradingview_signal_revision,
            tradingview_signal_csv,
            len(signals),
        ),
        bar_outcome_artifact=_artifact(
            tradingview_source,
            tradingview_bar_outcome_revision,
            tradingview_bar_outcome_csv,
            len(bar_outcomes),
        ),
    )


def evaluate_historical_v25_reference(
    reference: HistoricalV25Reference,
) -> HistoricalV25Evaluation:
    """Compare SH25 signals and explicit no-trade/rejection outcomes using frozen inputs."""
    parameters = reference.parameter_manifest.parameters
    signal_report = evaluate_v25_evidence(reference.bundle, parameters)
    python_results = run_v25_parity(
        reference.bundle.symbol,
        reference.bundle.bars,
        parameters,
    )
    bar_report = compare_bar_outcomes(
        reference.reference_bar_outcomes,
        python_results,
    )
    return HistoricalV25Evaluation(
        reference_id=reference.reference_id,
        signal_report=signal_report,
        bar_outcome_report=bar_report,
    )


__all__ = [
    "HistoricalV25Evaluation",
    "HistoricalV25Reference",
    "build_historical_v25_reference",
    "evaluate_historical_v25_reference",
]
