from __future__ import annotations

from .pine_parity_compare import ParityReport, compare_pine_signals
from .pine_parity_evidence import ParityEvidenceBundle
from .pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_STRATEGY_VERSION,
    V25Parameters,
    run_v25_parity,
)


def evaluate_v25_evidence(
    bundle: ParityEvidenceBundle,
    parameters: V25Parameters | None = None,
    *,
    price_abs_tolerance: float = 1e-8,
    price_rel_tolerance: float = 1e-9,
) -> ParityReport:
    """Run audited SH25 Python replay against a provenance-locked Pine reference bundle."""
    if bundle.model_id != PINE_V25_MODEL_ID:
        raise ValueError("bundle model_id is not SH25 CHALLENGER")
    if bundle.strategy_version != PINE_V25_STRATEGY_VERSION:
        raise ValueError("bundle strategy_version is not v2.5")

    results = run_v25_parity(bundle.symbol, bundle.bars, parameters)
    python_signals = tuple(signal for result in results for signal in result.signals)
    return compare_pine_signals(
        bundle.reference_signals,
        python_signals,
        price_abs_tolerance=price_abs_tolerance,
        price_rel_tolerance=price_rel_tolerance,
    )


__all__ = ["evaluate_v25_evidence"]
