from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .pine_bar_outcome_compare import BarOutcomeReport
from .pine_historical_reference import (
    HistoricalV24Reference,
    build_historical_v24_reference,
    evaluate_historical_v24_reference,
)
from .pine_parameter_manifest import PineParameterManifest, parse_parameter_manifest
from .pine_parity_compare import ParityReport
from .pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_STRATEGY_VERSION,
    V24Parameters,
)


@dataclass(frozen=True, slots=True)
class LockedHistoricalV24Reference:
    reference: HistoricalV24Reference
    parameter_manifest: PineParameterManifest

    @property
    def reference_id(self) -> str:
        identity = f"{self.reference.reference_id}:{self.parameter_manifest.sha256}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LockedHistoricalV24Evaluation:
    """Historical parity evaluation that proves the exact Pine inputs were part of evidence."""

    reference_id: str
    parameter_manifest_sha256: str
    signal_report: ParityReport
    bar_outcome_report: BarOutcomeReport

    def __post_init__(self) -> None:
        if len(self.parameter_manifest_sha256) != 64:
            raise ValueError("parameter_manifest_sha256 must be a SHA-256 hex digest")
        try:
            int(self.parameter_manifest_sha256, 16)
        except ValueError as exc:
            raise ValueError("parameter_manifest_sha256 must be a SHA-256 hex digest") from exc

    @property
    def exact(self) -> bool:
        return self.signal_report.exact and self.bar_outcome_report.exact


def build_locked_historical_v24_reference(
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
) -> LockedHistoricalV24Reference:
    """Require exact Pine input settings in addition to source and historical evidence."""
    reference = build_historical_v24_reference(
        symbol=symbol,
        market_csv=market_csv,
        tradingview_signal_csv=tradingview_signal_csv,
        tradingview_bar_outcome_csv=tradingview_bar_outcome_csv,
        market_source=market_source,
        market_revision=market_revision,
        tradingview_source=tradingview_source,
        tradingview_signal_revision=tradingview_signal_revision,
        tradingview_bar_outcome_revision=tradingview_bar_outcome_revision,
    )
    manifest = parse_parameter_manifest(
        parameter_manifest_json,
        parameter_type=V24Parameters,
        expected_model_id=PINE_V24_MODEL_ID,
        expected_strategy_version=PINE_V24_STRATEGY_VERSION,
        expected_source_blob_sha=PINE_V24_SOURCE_BLOB_SHA,
        datetime_fields=frozenset({"start_time", "end_time"}),
    )
    return LockedHistoricalV24Reference(
        reference=reference,
        parameter_manifest=manifest,
    )


def evaluate_locked_historical_v24_reference(
    reference: LockedHistoricalV24Reference,
) -> LockedHistoricalV24Evaluation:
    """Evaluate using only the parameter set embedded in the hashed historical evidence."""
    evaluation = evaluate_historical_v24_reference(
        reference.reference,
        reference.parameter_manifest.parameters,
    )
    return LockedHistoricalV24Evaluation(
        reference_id=reference.reference_id,
        parameter_manifest_sha256=reference.parameter_manifest.sha256,
        signal_report=evaluation.signal_report,
        bar_outcome_report=evaluation.bar_outcome_report,
    )


__all__ = [
    "LockedHistoricalV24Evaluation",
    "LockedHistoricalV24Reference",
    "build_locked_historical_v24_reference",
    "evaluate_locked_historical_v24_reference",
]
